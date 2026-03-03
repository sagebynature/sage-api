# sage-api

A FastAPI service that wraps the [sage-agent](https://github.com/sagebynature/sage-agent) framework. It exposes agents as HTTP endpoints via REST and the Agent-to-Agent (A2A) protocol, with Redis-backed session persistence.

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Agent Setup](#agent-setup)
- [REST API](#rest-api)
  - [Authentication](#authentication)
  - [Agent Discovery](#agent-discovery)
  - [Sessions](#sessions)
  - [Messages](#messages)
  - [Health](#health)
- [A2A Protocol](#a2a-protocol)
- [Session Persistence (Redis)](#session-persistence-redis)
- [Development](#development)
- [Docker & Kubernetes](#docker--kubernetes)

## Quick Start

### Docker (recommended)

```bash
cp .env.example .env
# Edit .env — set SAGE_API_API_KEY, AZURE_AI_API_KEY, AZURE_AI_API_BASE

make docker-build
make docker-up
```

The server starts on `http://localhost:8080`. Verify with:

```bash
curl http://localhost:8080/health/ready
```

### Local

```bash
# Install dependencies
make install

# Configure
cp .env.example .env
# Edit .env — set SAGE_API_API_KEY, AZURE_AI_API_KEY, AZURE_AI_API_BASE

# Start Redis
redis-server --daemonize yes

# Start the API
make start
```

The server starts on `http://localhost:8000`. Verify with:

```bash
curl http://localhost:8000/health/ready
```

## Architecture

Each subdirectory under `agents/` is a self-contained sage-agent instance with its own `config.toml`, agent definitions, and skills. The registry discovers these at startup and exposes the primary agent from each instance as an API endpoint.

```
agents/
  coder/                     # Instance name becomes the API agent name
    config.toml              # Central config (model, defaults, primary agent)
    agents/                  # Agent .md files
      orchestrator.md        # Primary agent (delegates to subagents)
      explorer.md            # Read-only codebase analyst
      implementer.md         # Code writer
      reviewer.md            # Code reviewer
    skills/                  # Skill definitions
      clean-code/SKILL.md
      python-pro/SKILL.md
```

Key design patterns:

- **Self-contained instances** — Each agent directory has everything it needs. Drop in a new directory to add an agent.
- **Redis-backed sessions** — Conversation history persists in Redis with TTL-based expiration. Enables horizontal scaling across replicas.
- **Concurrency control** — Per-session `asyncio.Lock` prevents race conditions. Concurrent requests to the same session return `409 Conflict`.
- **Hot reload** — File watcher monitors the agents directory. Config changes apply without restart.

## Configuration

Environment variables with `SAGE_API_` prefix, loaded from `.env`:

| Variable | Default | Description |
|---|---|---|
| `SAGE_API_API_KEY` | *(required)* | API key for `X-API-Key` header authentication |
| `SAGE_API_REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `SAGE_API_AGENTS_DIR` | `./agents` | Path to agent instance directories |
| `SAGE_API_SESSION_TTL_SECONDS` | `1800` | Session idle timeout in seconds |
| `SAGE_API_REQUEST_TIMEOUT_SECONDS` | `120` | Per-request LLM timeout in seconds |
| `SAGE_API_LOG_LEVEL` | `INFO` | Log level: `DEBUG` `INFO` `WARNING` `ERROR` `CRITICAL` |
| `SAGE_API_HOST` | `0.0.0.0` | Bind host (local dev only) |
| `SAGE_API_PORT` | `8000` | Bind port (local dev only) |

LLM provider credentials (read by agent `config.toml` via `[env]` substitution):

| Variable | Description |
|---|---|
| `AZURE_AI_API_KEY` | Azure AI API key |
| `AZURE_AI_API_BASE` | Azure AI endpoint URL |

> **Docker port:** When running via Docker/docker-compose the port is controlled by the `PORT` environment variable (default `8080`), not `SAGE_API_PORT`. Set `PORT=9000` to change it.

Each agent instance also has its own `config.toml` for model, permissions, and LLM parameters — see [Agent Setup](#agent-setup).

## Agent Setup

Create a directory under `agents/` with a `config.toml` and an `agents/` subdirectory:

```toml
# agents/my-agent/config.toml
skills_dir = "skills"
agents_dir = "agents"
primary = "assistant"

[defaults]
model = "azure_ai/claude-sonnet-4-6"
max_turns = 20

[defaults.model_params]
temperature = 0.0
max_tokens = 8192
```

```markdown
<!-- agents/my-agent/agents/assistant.md -->
---
name: assistant
description: A helpful coding assistant
extensions:
  - file_read
  - shell
max_turns: 10
---

You are a helpful AI assistant.
```

The service discovers this on startup (or hot-reload) and exposes it as `my-agent` in the API.

## REST API

### Endpoint Summary

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/v1/agents` | Yes | List agents |
| GET | `/v1/agents/{name}` | Yes | Get agent details |
| POST | `/v1/agents/{name}/sessions` | Yes | Create session |
| GET | `/v1/agents/{name}/sessions/{id}` | Yes | Get session info |
| DELETE | `/v1/agents/{name}/sessions/{id}` | Yes | Delete session |
| POST | `/v1/agents/{name}/sessions/{id}/messages` | Yes | Send message (sync) |
| POST | `/v1/agents/{name}/sessions/{id}/messages/stream` | Yes | Send message (SSE) |
| GET | `/health/live` | No | Liveness probe |
| GET | `/health/ready` | No | Readiness probe |
| GET | `/.well-known/agent-card.json` | No | A2A agent card |
| POST | `/a2a` | Yes | A2A JSON-RPC endpoint |

### Authentication

All endpoints except health checks and the agent card require an `X-API-Key` header:

```bash
curl -H "X-API-Key: your-key" http://localhost:8000/v1/agents
```

Requests without a valid key receive `401 Unauthorized`.

### Agent Discovery

**List all agents:**

```bash
curl -s -H "X-API-Key: $API_KEY" http://localhost:8000/v1/agents
```

```json
[
  {
    "name": "coder",
    "description": "Primary agent — routes tasks to specialist agents",
    "model": "azure_ai/claude-sonnet-4-6",
    "skills_count": 3,
    "subagents_count": 3
  }
]
```

**Get agent details:**

```bash
curl -s -H "X-API-Key: $API_KEY" http://localhost:8000/v1/agents/coder
```

### Sessions

**Create a session:**

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}' \
  http://localhost:8000/v1/agents/coder/sessions
```

```json
{
  "session_id": "ee1c713a-bc7d-4236-9069-4629762f7e6c",
  "agent_name": "coder",
  "created_at": "2026-03-02T05:41:28.009564Z",
  "last_active_at": "2026-03-02T05:41:28.009564Z",
  "message_count": 0
}
```

**Get session info:**

```bash
curl -s -H "X-API-Key: $API_KEY" \
  http://localhost:8000/v1/agents/coder/sessions/$SESSION_ID
```

**Delete a session:**

```bash
curl -s -X DELETE -H "X-API-Key: $API_KEY" \
  http://localhost:8000/v1/agents/coder/sessions/$SESSION_ID
# Returns 204 No Content
```

### Messages

**Send a message (synchronous):**

Blocks until the agent produces a complete response.

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "What is 2 + 2?"}' \
  http://localhost:8000/v1/agents/coder/sessions/$SESSION_ID/messages
```

```json
{
  "session_id": "ee1c713a-bc7d-4236-9069-4629762f7e6c",
  "message": "4",
  "metadata": null
}
```

**Send a message (streaming):**

Returns a Server-Sent Events stream. Tokens arrive as they are generated.

```bash
curl -N -X POST \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Say hello in 3 words."}' \
  http://localhost:8000/v1/agents/coder/sessions/$SESSION_ID/messages/stream
```

```
event: message
data: Hello

event: message
data:  there

event: message
data: , friend!

event: done
data: {}
```

### Health

```bash
# Liveness — is the process running?
curl http://localhost:8000/health/live
# {"status": "alive"}

# Readiness — is Redis connected and are agents loaded?
curl http://localhost:8000/health/ready
# {"status": "ready", "redis": "connected", "agents_loaded": 1}
```

## A2A Protocol

The [Agent-to-Agent protocol](https://google.github.io/A2A/) lets agents from different frameworks discover and communicate with each other through a standard JSON-RPC 2.0 interface.

**Discover the agent card:**

```bash
curl -s http://localhost:8000/.well-known/agent-card.json
```

```json
{
  "name": "sage-api",
  "description": "AI agent service powered by sage",
  "url": "http://localhost:8000/a2a",
  "version": "1.0.0",
  "capabilities": { "streaming": true, "pushNotifications": false },
  "skills": [
    { "id": "coder", "name": "coder", "description": "Primary agent — routes tasks to specialist agents" }
  ],
  "defaultInputModes": ["text"],
  "defaultOutputModes": ["text"]
}
```

**Send a message (auto-creates session):**

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "What is 2 + 2?"}]
      }
    }
  }' \
  http://localhost:8000/a2a
```

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "id": "ee1c713a-bc7d-4236-9069-4629762f7e6c",
    "status": { "state": "completed" },
    "artifacts": [{ "parts": [{ "text": "4" }] }]
  }
}
```

**Continue a conversation (pass sessionId):**

```bash
curl -s -X POST \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "2",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "Now multiply that by 10"}]
      },
      "sessionId": "ee1c713a-bc7d-4236-9069-4629762f7e6c"
    }
  }' \
  http://localhost:8000/a2a
```

**Stream a response:**

```bash
curl -N -X POST \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "3",
    "method": "message/stream",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "Explain what you can do."}]
      }
    }
  }' \
  http://localhost:8000/a2a
```

```
event: message
data: {"kind": "status-update", "status": {"state": "working"}}

event: message
data: {"kind": "artifact-update", "artifact": {"parts": [{"text": "I can "}]}}

event: message
data: {"kind": "artifact-update", "artifact": {"parts": [{"text": "help you write code."}]}}

event: done
data: {"kind": "status-update", "status": {"state": "completed"}}
```

## Session Persistence (Redis)

All session state lives in Redis, not in process memory. This enables:

- **Horizontal scaling** — Multiple API replicas share the same Redis. Any replica can serve any session.
- **Crash recovery** — If a process restarts, agent instances are rebuilt from the conversation history stored in Redis.
- **Automatic cleanup** — Sessions expire after the configured TTL (default 30 minutes of inactivity).

Inspect sessions directly:

```bash
# List active sessions
redis-cli keys 'session:*'

# View a session's data
redis-cli get 'session:<session-id>'

# Check TTL remaining
redis-cli ttl 'session:<session-id>'
```

## Development

```bash
make install      # Install dependencies (frozen lockfile)
make start        # Start dev server with --reload
make test         # Run tests with coverage
make lint         # Ruff check + fix
make format       # Ruff format
make type-check   # mypy strict mode
```

### Project Structure

```
sage-api/
├── sage_api/
│   ├── main.py              # App factory, lifespan, router mounting
│   ├── config.py            # Pydantic Settings (env vars)
│   ├── logging.py           # Structured logging (logging.conf + structlog)
│   ├── api/                 # REST endpoints (agents, sessions, messages, health)
│   ├── a2a/                 # A2A protocol (JSON-RPC routes, agent card)
│   ├── services/            # Business logic
│   │   ├── agent_registry.py    # Instance discovery and agent construction
│   │   ├── session_manager.py   # Session lifecycle and message handling
│   │   ├── session_store.py     # Redis persistence
│   │   └── hot_reload.py        # File watcher for config changes
│   ├── models/schemas.py    # Request/response Pydantic models
│   └── middleware/           # Auth, error handling, request logging
├── agents/                  # Agent instance directories
├── tests/                   # pytest suite (194 tests)
├── k8s/                     # Kubernetes manifests
├── Makefile
└── Dockerfile
```

## Docker & Kubernetes

### Docker Compose

The `docker-compose.yml` includes the API and a Redis service. The `agents/` directory is mounted at runtime — not baked into the image.

```bash
cp .env.example .env
# Edit .env

make docker-build   # Build the image
make docker-up      # Start API + Redis
make docker-logs    # Tail API logs
make docker-down    # Stop and remove containers
```

The API is available at `http://localhost:8080` by default.

**Override the port:**

```bash
PORT=9000 docker compose up
```

**Mount a custom agents directory:**

By default `./agents` is mounted to `/app/agents`. To use a different path, edit the `volumes` entry in `docker-compose.yml` or override with:

```bash
docker compose run -v /path/to/agents:/app/agents api
```

### Kubernetes

Manifests in `k8s/`:

```bash
kubectl apply -f k8s/configmap.yaml
kubectl create secret generic sage-api-secret --from-literal=api-key=your-key
kubectl apply -f k8s/deployment.yaml -f k8s/service.yaml
```

The deployment runs 2 replicas with liveness (`/health/live`) and readiness (`/health/ready`) probes.
