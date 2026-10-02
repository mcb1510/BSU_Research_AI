# BSU Research AI

A self-hosted AI chat platform for Boise State University researchers, built on [LibreChat](https://github.com/danny-avila/LibreChat).

Researchers log in, pick a model or a ready-made **Agent** from the library, and chat — no setup required on their end. Admins configure models, build agents, and extend capabilities through code and config, not a hosted dashboard.

## What's here

- **Models**: Muse Glimmer, Olmo3 Pretrained, and a quantized Muse Glimmer variant ("Spark SSH") — all served locally via vLLM on Boise State's Borah compute cluster and reached through SSH tunnels / Cloudflare Tunnel, not a third-party API.
- **Agents**: a researcher-facing library (left sidebar → **Agents**) of pre-built, single-purpose assistants — e.g. a Paper Summarizer that reads an uploaded PDF and returns a per-paragraph summary. Agents are defined in code (`packages/api/src/agents/defaults.ts`) and sync to the database automatically every time the backend starts — no admin UI click-through needed.
- **Web search**: a keyless DuckDuckGo-backed tool (no API key required), with built-in per-turn budget limits to keep context usage sane.
- **Access**: restricted to `@boisestate.edu` accounts.

## Running it locally

```bash
docker compose up -d mongodb   # or your own local MongoDB
npm run build:packages
npm run backend:dev
npm run frontend:dev
```

Then open `http://localhost:3090`.

## Configuration

Live runtime config lives in `librechat.yaml` (models, interface toggles, summarization, file handling) and `.env` (secrets, ports, feature flags). See **[CLAUDE.md](CLAUDE.md)** for the full map of what lives where, deployment conventions, and code style — read it before making changes.

## Credit

Built on [LibreChat](https://github.com/danny-avila/LibreChat), an open-source project by Danny Avila and contributors. See the [upstream repo](https://github.com/danny-avila/LibreChat) for the general-purpose platform this deployment is based on.
