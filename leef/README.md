# Kiro CLI Clone

An AI agent terminal — a Python clone of Kiro CLI with multi-LLM support, tool use, and subagent pipelines. Use any LLM: OpenAI, Anthropic, local models via Ollama or LM Studio, Groq, and more.

---

## Features

- **Multi-LLM support** — OpenAI, Anthropic Claude, Ollama (local), Groq, Together, LM Studio, vLLM, OpenRouter, DeepSeek, Mistral
- **Agentic tool use** — reads/writes files, runs shell commands, searches the web and codebases
- **Subagent pipelines** — spawn parallel agents with dependency DAGs and reviewer loops
- **Interactive REPL** — persistent chat with history, slash commands, and rich UI
- **One-shot mode** — pipe commands straight from the terminal
- **Fully configurable** — `kiro.config.json` + environment variables

---

## Install

```bash
# Clone / copy to your machine
cd /workshop/agents

# Install dependencies
pip install -r requirements.txt

# (Optional) make the CLI available system-wide
chmod +x kiro-cli
ln -sf $(pwd)/kiro-cli /usr/local/bin/kiro
```

---

## Quick Start

```bash
# Set your API key
export OPENAI_API_KEY="sk-..."

# Start the REPL
python -m kiro

# One-shot query
python -m kiro "write a Python hello world to hello.py"

# Use Anthropic Claude
python -m kiro --provider anthropic --model claude-3-5-sonnet-20241022 "explain this code"

# Use a local Ollama model (no API key needed)
ollama pull llama3.2
python -m kiro --provider ollama --model llama3.2 "help me debug this"

# Use LM Studio (OpenAI-compatible, no API key needed)
python -m kiro --provider lmstudio "what is 2+2"

# Use Groq (fast inference)
export GROQ_API_KEY="gsk_..."
python -m kiro --provider groq --model llama-3.1-70b-versatile "fast task"
```

---

## Supported Providers

| Provider     | `--provider` flag | API Key Env Var         | Notes                        |
|-------------|-------------------|-------------------------|------------------------------|
| OpenAI       | `openai`          | `OPENAI_API_KEY`        | GPT-4o, GPT-4, GPT-3.5      |
| Anthropic    | `anthropic`       | `ANTHROPIC_API_KEY`     | Claude 3.5, Claude 3         |
| Ollama       | `ollama`          | —                       | Local: llama3.2, mistral...  |
| LM Studio    | `lmstudio`        | —                       | Local OpenAI-compatible      |
| Groq         | `groq`            | `GROQ_API_KEY`          | Very fast inference          |
| Together AI  | `together`        | `TOGETHER_API_KEY`      |                              |
| OpenRouter   | `openrouter`      | `OPENROUTER_API_KEY`    | 100+ models                  |
| DeepSeek     | `deepseek`        | `DEEPSEEK_API_KEY`      |                              |
| Mistral      | `mistral`         | `MISTRAL_API_KEY`       |                              |
| vLLM         | `vllm`            | —                       | Self-hosted                  |
| Fireworks    | `fireworks`       | `FIREWORKS_API_KEY`     |                              |

---

## CLI Flags

```
usage: kiro [-h] [--provider P] [--model M] [--api-key K] [--api-base B]
            [--system S] [--temperature T] [--max-tokens N]
            [--no-tools] [--quiet] [--config C]
            [message]

positional arguments:
  message               Message to send (omit for REPL mode)

options:
  --provider, -p        LLM provider (openai/anthropic/ollama/groq/...)
  --model, -m           Model name
  --api-key, -k         API key (overrides environment variable)
  --api-base, -b        Base URL for OpenAI-compatible APIs
  --system, -s          System prompt override
  --temperature, -t     Sampling temperature (0.0–1.0)
  --max-tokens          Max output tokens
  --no-tools            Disable all tools (pure chat)
  --quiet, -q           Hide tool call details
  --config, -c          Path to kiro.config.json
```

---

## REPL Slash Commands

| Command             | Description                            |
|---------------------|----------------------------------------|
| `/help`             | Show all commands                      |
| `/model <name>`     | Switch model mid-session               |
| `/provider <name>`  | Switch provider mid-session            |
| `/system <text>`    | Change the system prompt               |
| `/clear`            | Clear conversation history             |
| `/tools`            | List all available tools               |
| `/history`          | Show conversation history              |
| `/config`           | Show current configuration + usage     |
| `/models`           | List available Ollama models           |
| `/save <file>`      | Save conversation to JSON              |
| `/load <file>`      | Restore conversation from JSON         |
| `/pipeline`         | Show pipeline scripting help           |
| `/run <file.py>`    | Execute a pipeline script              |
| `/init`             | Write a default `kiro.config.json`     |
| `/exit`             | Quit                                   |

---

## Configuration

Create `kiro.config.json` in your project root (or run `/init`):

```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "temperature": 0.7,
  "max_tokens": 4096,
  "max_iterations": 25,
  "show_tool_calls": true,
  "stream": true
}
```

For user-level defaults, place config at `~/.kiro/config.json`.

---

## Built-in Tools

| Tool            | Description                                      |
|----------------|--------------------------------------------------|
| `read_file`    | Read file contents with optional line range      |
| `write_file`   | Write or append to files                         |
| `list_directory` | Tree-view directory listing                    |
| `glob`         | Find files by glob pattern                       |
| `grep`         | Search file content by regex                     |
| `shell`        | Run shell commands                               |
| `web_search`   | Search the web via DuckDuckGo                    |
| `todo_list`    | Create and track task lists                      |

---

## Subagent Pipelines

Create a Python script and run it with `/run <file.py>` or directly with `python`:

```python
# pipeline_example.py
from kiro.pipeline import Pipeline, create_agent
from kiro.providers import get_provider
from kiro.tools.base import build_default_registry

provider = get_provider("openai", model="gpt-4o")  # uses OPENAI_API_KEY

pipeline = Pipeline(provider)

# Parallel stages (no dependencies — run simultaneously)
pipeline.add_stage("backend_research",  "Research best Python REST frameworks 2024")
pipeline.add_stage("frontend_research", "Research best JS frontend frameworks 2024")

# Sequential stage — waits for both research stages
pipeline.add_stage(
    "architect",
    "Design a full-stack app given:\nBackend: {backend_research}\nFrontend: {frontend_research}",
    depends_on=["backend_research", "frontend_research"],
)

# Implementer stage
pipeline.add_stage(
    "implementer",
    "Implement this architecture:\n{architect}",
    depends_on=["architect"],
)

# Reviewer with loop — loops back to implementer if it says NEEDS_CHANGES
pipeline.add_stage(
    "reviewer",
    "Review this code. If it needs work, write NEEDS_CHANGES then explain.\n\n{implementer}",
    depends_on=["implementer"],
    loop_to="implementer",
    loop_trigger="NEEDS_CHANGES",
    max_loop_iterations=3,
)

results = pipeline.run(
    on_text=lambda stage, text: print(f"[{stage}] {text}", end="", flush=True)
)

for name, result in results.items():
    print(f"\n\n{'='*50}\n{name} ({result.duration_s:.1f}s)\n{'='*50}")
    print(result.output)
```

---

## Use from Python

```python
from kiro.pipeline import create_agent

# Create an agent with any provider
agent = create_agent(
    provider_name="ollama",
    model="llama3.2",
    system="You are a senior Python developer. Be concise."
)

# Stream response with events
from kiro.agent import TextChunk, ToolCallStart, ToolCallResult

for event in agent.run("Read setup.py and tell me what this project does"):
    if isinstance(event, TextChunk):
        print(event.text, end="", flush=True)
    elif isinstance(event, ToolCallStart):
        print(f"\n[calling {event.name}]", flush=True)

# Or blocking one-liner
result = agent.chat("What is the airspeed velocity of an unladen swallow?")
print(result)

# Multi-turn
agent.add_user_message("Now write tests for that code")
```

---

## Writing Custom Tools

```python
from kiro.tools.base import BaseTool, build_default_registry
from kiro.pipeline import create_agent

class WeatherTool(BaseTool):
    name = "get_weather"
    description = "Get current weather for a city."
    parameters = {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "City name"},
        },
        "required": ["city"],
    }

    def execute(self, city: str) -> str:
        # Your real implementation here
        return f"It's 22°C and sunny in {city}."

# Add it to an agent
agent = create_agent("openai", model="gpt-4o")
agent.registry.register(WeatherTool())

result = agent.chat("What's the weather in Paris?")
print(result)
```

---

## Architecture

```
kiro/
├── providers/
│   ├── base.py              # BaseProvider, Message, ToolCall, LLMResponse
│   ├── openai_provider.py   # OpenAI + OpenAI-compatible APIs
│   ├── anthropic_provider.py
│   ├── ollama_provider.py   # Local LLMs
│   └── __init__.py          # get_provider() factory
├── tools/
│   ├── base.py              # BaseTool, ToolRegistry
│   ├── file_tools.py        # read_file, write_file, glob, list_directory
│   ├── shell_tools.py       # shell
│   ├── search_tools.py      # grep, web_search
│   ├── todo_tool.py         # todo_list
│   └── __init__.py
├── agent.py                 # Agent runtime (streaming agentic loop)
├── pipeline.py              # Multi-stage pipeline orchestrator
├── config.py                # Config loading (file + env vars)
├── cli.py                   # REPL + slash commands + argparse
└── utils.py                 # Rich/plain-text UI helpers
```

---

## License

MIT
