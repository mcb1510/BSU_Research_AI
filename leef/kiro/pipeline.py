"""Subagent pipeline orchestrator.

Allows defining multi-stage agent pipelines (DAGs) where:
- Stages can run in parallel (no dependencies)
- Stages can depend on prior stage outputs
- Stages can loop (reviewer loops back to implementer on feedback)
- Each stage gets its own Agent with its own history

Example:
    pipeline = Pipeline(provider, registry)
    pipeline.add_stage("researcher", prompt="Research X")
    pipeline.add_stage("implementer", prompt="Implement: {researcher}", depends_on=["researcher"])
    pipeline.add_stage("reviewer", prompt="Review: {implementer}", depends_on=["implementer"],
                       loop_to="implementer", loop_trigger="NEEDS_CHANGES", max_iterations=3)
    results = pipeline.run()
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Any

from .providers.base import BaseProvider
from .tools.base import ToolRegistry, build_default_registry
from .agent import Agent, AgentEvent, TextChunk, ToolCallStart, ToolCallResult, AgentDone


@dataclass
class StageConfig:
    """Configuration for a single pipeline stage."""
    name: str
    prompt_template: str           # May reference {stage_name} placeholders
    system: str | None = None      # Override system prompt for this stage
    depends_on: list[str] = field(default_factory=list)
    loop_to: str | None = None     # Stage name to loop back to
    loop_trigger: str = "NEEDS_CHANGES"  # Text that triggers the loop
    max_loop_iterations: int = 3
    model: str | None = None       # Override model for this stage
    provider_name: str | None = None  # Override provider for this stage


@dataclass
class StageResult:
    """Result of a completed pipeline stage."""
    name: str
    output: str
    duration_s: float
    usage: dict
    iterations: int = 1
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


class PipelineEvent:
    pass


class StageStarted(PipelineEvent):
    def __init__(self, stage_name: str):
        self.stage_name = stage_name


class StageCompleted(PipelineEvent):
    def __init__(self, stage_name: str, result: StageResult):
        self.stage_name = stage_name
        self.result = result


class PipelineDone(PipelineEvent):
    def __init__(self, results: dict[str, StageResult]):
        self.results = results


class Pipeline:
    """
    Multi-stage agent pipeline with parallel execution and optional loops.

    Stages with no dependencies start immediately (in parallel).
    Stages with dependencies wait for all their dependencies to complete,
    then receive those outputs injected into their prompt templates.
    """

    def __init__(
        self,
        provider: BaseProvider,
        registry: ToolRegistry | None = None,
        on_event: Callable[[PipelineEvent], None] | None = None,
        default_system: str | None = None,
    ):
        self.provider = provider
        self.registry = registry or build_default_registry()
        self.on_event = on_event
        self.default_system = default_system
        self._stages: dict[str, StageConfig] = {}
        self._stage_order: list[str] = []

    def add_stage(
        self,
        name: str,
        prompt_template: str,
        system: str | None = None,
        depends_on: list[str] | None = None,
        loop_to: str | None = None,
        loop_trigger: str = "NEEDS_CHANGES",
        max_loop_iterations: int = 3,
        model: str | None = None,
        provider_name: str | None = None,
    ) -> "Pipeline":
        """Add a stage to the pipeline. Returns self for chaining."""
        self._stages[name] = StageConfig(
            name=name,
            prompt_template=prompt_template,
            system=system,
            depends_on=depends_on or [],
            loop_to=loop_to,
            loop_trigger=loop_trigger,
            max_loop_iterations=max_loop_iterations,
            model=model,
            provider_name=provider_name,
        )
        self._stage_order.append(name)
        return self

    def run(
        self,
        on_text: Callable[[str, str], None] | None = None,
        on_tool: Callable[[str, str, dict], None] | None = None,
    ) -> dict[str, StageResult]:
        """
        Run all stages respecting dependencies.

        Args:
            on_text: Called with (stage_name, text_chunk) during streaming.
            on_tool: Called with (stage_name, tool_name, arguments) on each tool call.

        Returns:
            Dict mapping stage_name → StageResult
        """
        results: dict[str, StageResult] = {}
        lock = threading.Lock()
        completed_event = threading.Event()

        def all_deps_done(stage: StageConfig) -> bool:
            with lock:
                return all(d in results for d in stage.depends_on)

        def run_stage(stage: StageConfig, loop_context: str | None = None, loop_count: int = 0):
            # Build prompt from template + dependency outputs
            with lock:
                dep_outputs = {d: results[d].output for d in stage.depends_on if d in results}

            prompt = stage.prompt_template
            for dep_name, dep_output in dep_outputs.items():
                prompt = prompt.replace(f"{{{dep_name}}}", dep_output)

            if loop_context:
                prompt = f"{prompt}\n\nFeedback from reviewer:\n{loop_context}"

            # Create a fresh agent for this stage
            provider = self._get_provider_for_stage(stage)
            agent = Agent(
                provider=provider,
                registry=self.registry,
                system=stage.system or self.default_system,
                name=stage.name,
            )

            if self.on_event:
                self.on_event(StageStarted(stage.name))

            t0 = time.perf_counter()
            output_text = ""

            for event in agent.run(prompt):
                if isinstance(event, TextChunk):
                    output_text += event.text
                    if on_text:
                        on_text(stage.name, event.text)
                elif isinstance(event, ToolCallStart):
                    if on_tool:
                        on_tool(stage.name, event.name, event.arguments)
                elif isinstance(event, AgentDone):
                    pass

            duration = time.perf_counter() - t0
            final_usage = agent.total_usage

            # Check for loop trigger
            if (
                stage.loop_to
                and stage.loop_trigger in output_text
                and loop_count < stage.max_loop_iterations
            ):
                # The reviewing stage triggered a loop — re-run the target stage
                target = self._stages.get(stage.loop_to)
                if target:
                    run_stage(target, loop_context=output_text, loop_count=loop_count + 1)

            with lock:
                results[stage.name] = StageResult(
                    name=stage.name,
                    output=output_text,
                    duration_s=duration,
                    usage=final_usage,
                    iterations=loop_count + 1,
                )

            if self.on_event:
                self.on_event(StageCompleted(stage.name, results[stage.name]))

        # Topological execution: keep picking stages whose deps are done
        pending = list(self._stage_order)
        running: list[threading.Thread] = []
        in_progress: set[str] = set()

        while pending or any(t.is_alive() for t in running):
            # Collect newly runnable stages
            to_launch = []
            for name in list(pending):
                stage = self._stages[name]
                if all_deps_done(stage) and name not in in_progress:
                    to_launch.append(name)
                    pending.remove(name)
                    in_progress.add(name)

            for name in to_launch:
                t = threading.Thread(target=run_stage, args=(self._stages[name],), daemon=True)
                running.append(t)
                t.start()

            # Clean up finished threads
            running = [t for t in running if t.is_alive()]
            time.sleep(0.05)

        # Wait for stragglers
        for t in running:
            t.join()

        if self.on_event:
            self.on_event(PipelineDone(results))

        return results

    def _get_provider_for_stage(self, stage: StageConfig) -> BaseProvider:
        """Return a potentially stage-specific provider."""
        if stage.model or stage.provider_name:
            from .providers import get_provider
            provider_name = stage.provider_name or self.provider.__class__.__name__.replace("Provider", "").lower()
            model = stage.model or self.provider.model
            try:
                return get_provider(provider_name, model=model, api_key=self.provider.api_key)
            except Exception:
                pass
        return self.provider

    def __repr__(self):
        return f"Pipeline(stages={list(self._stages.keys())})"


# ── Convenience: create an agent from config ──────────────────────────────────

def create_agent(
    provider_name: str = "openai",
    model: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    system: str | None = None,
    tools: list | None = None,
    name: str = "agent",
    **provider_kwargs,
) -> Agent:
    """
    Convenience factory to create a fully configured Agent.

    Examples:
        # OpenAI
        agent = create_agent("openai", model="gpt-4o", api_key="sk-...")
        # Anthropic
        agent = create_agent("anthropic", model="claude-3-5-sonnet-20241022", api_key="sk-...")
        # Local Ollama
        agent = create_agent("ollama", model="llama3.2")
        # Groq
        agent = create_agent("groq", model="llama-3.1-70b-versatile", api_key="gsk_...")
        # LM Studio
        agent = create_agent("lmstudio")
    """
    from .providers import get_provider
    from .tools.base import build_default_registry, ToolRegistry
    from .tools.base import BaseTool

    kwargs = {**provider_kwargs}
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base

    provider = get_provider(provider_name, model=model, **kwargs)

    registry = build_default_registry(provider=provider)

    # Register any extra custom tools
    if tools:
        for tool in tools:
            if isinstance(tool, BaseTool):
                registry.register(tool)

    return Agent(provider=provider, registry=registry, system=system, name=name)
