from __future__ import annotations
"""Spawn agent tool — lets the agent create and run subagents on the fly.

This is what makes it a true clone: the agent can delegate work to
specialized subagents, run pipelines, or parallelize tasks — just like
the real Kiro does with its subagent system.

Includes:
  - SpawnAgentTool  — single subagent with optional multi-turn conversation
  - SpawnPipelineTool — multi-stage DAG pipeline via kiro.pipeline
"""

import sys
from .base import BaseTool

# Follow-up prompts used when turns > 1 to drive the conversation forward
_FOLLOWUP_PROMPTS = [
    "Continue. Elaborate on the most important parts.",
    "Go deeper on any areas that need more detail or clarification.",
    "Summarize the key takeaways and any remaining open questions.",
]


class SpawnAgentTool(BaseTool):
    name = "spawn_agent"
    description = (
        "Create and run a subagent to handle a specific task. "
        "The subagent gets its own conversation, tools, and system prompt. "
        "Use this to delegate specialized work, run tasks in parallel, or break "
        "complex problems into focused sub-tasks. Returns the subagent's final output. "
        "Set turns > 1 to have the subagent continue with follow-up exchanges for "
        "richer, more thorough responses."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The task or question to give the subagent.",
            },
            "system": {
                "type": "string",
                "description": (
                    "Optional system prompt to specialize the subagent. "
                    "e.g. 'You are a senior Python developer. Be concise and write clean code.'"
                ),
            },
            "model": {
                "type": "string",
                "description": (
                    "Optional model override for this subagent. "
                    "Defaults to the same model as the parent agent."
                ),
            },
            "provider": {
                "type": "string",
                "description": (
                    "Optional provider override (openai/anthropic/ollama/groq/...). "
                    "Defaults to the same provider as the parent agent."
                ),
            },
            "turns": {
                "type": "integer",
                "description": (
                    "Number of back-and-forth exchanges for the subagent conversation. "
                    "Default is 1 (single exchange). When > 1, the subagent is sent "
                    "follow-up prompts to elaborate and go deeper. Maximum is 5."
                ),
            },
            "context": {
                "type": "string",
                "description": (
                    "Optional additional context to inject at the start of the subagent's "
                    "task. Prepended to the task with a separator, e.g. background "
                    "information, prior research, or relevant code snippets."
                ),
            },
            "stream_output": {
                "type": "boolean",
                "description": (
                    "Whether to print intermediate output to stdout as the subagent "
                    "streams its responses. Default is true. Set to false to suppress "
                    "all intermediate output and only return the final combined result."
                ),
            },
        },
        "required": ["task"],
    }

    def __init__(self, parent_provider=None, parent_registry=None):
        """
        parent_provider: the provider instance from the parent agent (used as default).
        parent_registry: the tool registry (subagents get the same tools).
        """
        self._parent_provider = parent_provider
        self._parent_registry = parent_registry

    def execute(
        self,
        task: str,
        system: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        turns: int = 1,
        context: str | None = None,
        stream_output: bool = True,
    ) -> str:
        from kiro.agent import Agent, TextChunk, ToolCallStart, AgentDone
        from kiro.tools.base import build_default_registry

        # Cap turns to a sensible maximum
        turns = max(1, min(turns, 5))

        # Resolve provider
        if provider or model:
            from kiro.providers import get_provider as _get_provider
            provider_name = (
                provider
                or self._parent_provider.__class__.__name__
                    .replace("Provider", "")
                    .lower()
            )
            model_name = model or (
                self._parent_provider.model if self._parent_provider else "gpt-4o"
            )
            api_key = getattr(self._parent_provider, "api_key", None)
            try:
                llm_provider = _get_provider(provider_name, model=model_name, api_key=api_key)
            except Exception as e:
                return f"Error creating subagent provider: {e}"
        else:
            llm_provider = self._parent_provider

        if llm_provider is None:
            return "Error: No provider available for subagent."

        # Subagents get their own registry (same tools, fresh state)
        registry = self._parent_registry or build_default_registry()

        subagent = Agent(
            provider=llm_provider,
            registry=registry,
            system=system,
            name="subagent",
            max_iterations=15,
        )

        # Build the initial message, injecting optional context
        initial_task = task
        if context:
            initial_task = f"Context:\n{context}\n\n---\n\n{task}"

        all_parts: list[str] = []

        def _run_turn(message: str, turn_index: int) -> str:
            """Run a single turn, streaming output to stdout and returning collected text."""
            turn_parts: list[str] = []

            if stream_output:
                # Print a turn header so the user can follow along
                if turns > 1:
                    prefix = f"[subagent turn {turn_index + 1}/{turns}] "
                else:
                    prefix = "[subagent] "
                sys.stdout.write(prefix)
                sys.stdout.flush()

            for event in subagent.run(message):
                if isinstance(event, TextChunk):
                    turn_parts.append(event.text)
                    if stream_output:
                        # Stream each text chunk to stdout in real time
                        sys.stdout.write(event.text)
                        sys.stdout.flush()
                elif isinstance(event, ToolCallStart):
                    if stream_output:
                        # Notify the user that the subagent is calling a tool
                        sys.stdout.write(f"\n[subagent calling: {event.name}]\n")
                        sys.stdout.flush()

            if stream_output:
                # Clean newline after each turn's streamed output
                print("")

            return "".join(turn_parts).strip()

        # First turn — send the actual task
        first_response = _run_turn(initial_task, turn_index=0)
        all_parts.append(first_response)

        # Subsequent turns — drive the subagent to elaborate
        for turn_idx in range(1, turns):
            if not first_response:
                # Nothing came back — no point continuing
                break

            followup = _FOLLOWUP_PROMPTS[min(turn_idx - 1, len(_FOLLOWUP_PROMPTS) - 1)]
            response = _run_turn(followup, turn_index=turn_idx)
            if response:
                all_parts.append(response)

        # Combine all turns with clear separators when multi-turn
        if len(all_parts) == 1:
            combined = all_parts[0]
        else:
            sections = []
            for i, part in enumerate(all_parts):
                sections.append(f"--- Turn {i + 1} ---\n{part}")
            combined = "\n\n".join(sections)

        return combined if combined else "(subagent returned no output)"


class SpawnPipelineTool(BaseTool):
    name = "spawn_pipeline"
    description = (
        "Run a multi-stage agent pipeline. Each stage can depend on previous stages. "
        "Stages without dependencies run in parallel. "
        "Outputs from dependency stages are automatically injected into dependent stage "
        "prompts using {stage_name} placeholders. "
        "Returns all stage results or a combined summary."
    )
    parameters = {
        "type": "object",
        "properties": {
            "stages": {
                "type": "array",
                "description": (
                    "List of pipeline stages to execute. Each stage is an object with: "
                    "name (string, required) — unique stage identifier; "
                    "prompt (string, required) — task prompt, may use {stage_name} "
                    "placeholders to reference outputs of dependency stages; "
                    "depends_on (array of strings, optional) — names of stages that must "
                    "complete before this stage starts; "
                    "system (string, optional) — system prompt override for this stage."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Unique stage name.",
                        },
                        "prompt": {
                            "type": "string",
                            "description": (
                                "Task prompt for this stage. Use {stage_name} placeholders "
                                "to inject outputs from dependency stages."
                            ),
                        },
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Names of stages this stage depends on.",
                        },
                        "system": {
                            "type": "string",
                            "description": "Optional system prompt override for this stage.",
                        },
                    },
                    "required": ["name", "prompt"],
                },
            },
            "on_complete": {
                "type": "string",
                "description": (
                    "What to do with the results when the pipeline finishes. "
                    "'return_all' (default) — return every stage's output with labels. "
                    "'summarize' — return only the last stage's output as the final result."
                ),
            },
        },
        "required": ["stages"],
    }

    def __init__(self, parent_provider=None, parent_registry=None):
        """
        parent_provider: the provider instance from the parent agent (used as default).
        parent_registry: the tool registry passed to each pipeline stage agent.
        """
        self._parent_provider = parent_provider
        self._parent_registry = parent_registry

    def execute(
        self,
        stages: list[dict],
        on_complete: str = "return_all",
    ) -> str:
        from kiro.pipeline import Pipeline
        from kiro.tools.base import build_default_registry

        if self._parent_provider is None:
            return "Error: No provider available for pipeline."

        if not stages:
            return "Error: 'stages' must contain at least one stage."

        registry = self._parent_registry or build_default_registry()

        pipeline = Pipeline(
            provider=self._parent_provider,
            registry=registry,
        )

        # Register all stages
        for stage_def in stages:
            name = stage_def.get("name")
            prompt = stage_def.get("prompt")

            if not name or not prompt:
                return (
                    f"Error: Each stage must have 'name' and 'prompt'. "
                    f"Got: {stage_def!r}"
                )

            depends_on: list[str] = stage_def.get("depends_on") or []
            system: str | None = stage_def.get("system")

            pipeline.add_stage(
                name=name,
                prompt_template=prompt,
                system=system,
                depends_on=depends_on,
            )

        # Run the pipeline, streaming text to stdout
        def _on_text(stage_name: str, text: str) -> None:
            print(f"[pipeline:{stage_name}] {text}", end="", flush=True)

        try:
            results = pipeline.run(on_text=_on_text)
        except Exception as e:
            return f"Error running pipeline: {e}"

        if not results:
            return "(pipeline returned no results)"

        on_complete = (on_complete or "return_all").strip().lower()

        if on_complete == "summarize":
            # Return only the last stage's output (typically the synthesising stage)
            last_stage_name = stages[-1].get("name")
            if last_stage_name and last_stage_name in results:
                last = results[last_stage_name]
                status = "✓" if last.succeeded else "✗"
                return (
                    f"{status} Pipeline complete. "
                    f"Final stage '{last_stage_name}' ({last.duration_s:.1f}s):\n\n"
                    f"{last.output}"
                )
            # Fall through to return_all if the last stage isn't found
            on_complete = "return_all"

        # return_all — format each stage result with a header
        sections: list[str] = []
        for stage_def in stages:
            sname = stage_def.get("name", "")
            if sname not in results:
                continue
            r = results[sname]
            status = "✓" if r.succeeded else "✗"
            header = f"{status} [{sname}] ({r.duration_s:.1f}s)"
            if r.error:
                body = f"ERROR: {r.error}"
            else:
                body = r.output or "(no output)"
            sections.append(f"{header}\n{'-' * len(header)}\n{body}")

        return "\n\n".join(sections) if sections else "(pipeline returned no results)"
