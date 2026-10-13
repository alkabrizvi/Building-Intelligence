# Manual tests

## Story 1.1 — Architecture and project seed

**What it adds:** a FastAPI seed with `/healthz`, `/v1/query`, `/v1/models` and `/v1/chat/completions`, plus six selectable modes that all return an honest `not_implemented` placeholder.

Prerequisite: start the API with `uv run uvicorn building_with_rag.main:app --port 8000`. No `.env` credentials are needed. The commands below use POSIX quoting (Git Bash); in PowerShell call `curl.exe` and escape the JSON quotes.

```bash
# Health
curl http://127.0.0.1:8000/healthz

# Models
curl http://127.0.0.1:8000/v1/models

# Query: success (semantic)
curl -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the punishment for murder?", "pattern": "semantic"}'

# Query: the other five modes
curl -X POST http://127.0.0.1:8000/v1/query -H "Content-Type: application/json" -d '{"question": "What is the punishment for murder?", "pattern": "hybrid"}'
curl -X POST http://127.0.0.1:8000/v1/query -H "Content-Type: application/json" -d '{"question": "What is the punishment for murder?", "pattern": "hybrid-reranked"}'
curl -X POST http://127.0.0.1:8000/v1/query -H "Content-Type: application/json" -d '{"question": "What is the punishment for murder?", "pattern": "structured"}'
curl -X POST http://127.0.0.1:8000/v1/query -H "Content-Type: application/json" -d '{"question": "What is the punishment for murder?", "pattern": "decomposition"}'
curl -X POST http://127.0.0.1:8000/v1/query -H "Content-Type: application/json" -d '{"question": "What is the punishment for murder?", "pattern": "hyde"}'

# Query: invalid input (empty question, unknown pattern)
curl -i -X POST http://127.0.0.1:8000/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "", "pattern": "unknown"}'

# Chat completions: non-streaming
curl -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "rag-semantic", "messages": [{"role": "user", "content": "What is the punishment for murder?"}]}'

# Chat completions: streaming
curl -N -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "rag-semantic", "stream": true, "messages": [{"role": "user", "content": "What is the punishment for murder?"}]}'

# Chat completions: unknown model
curl -i -X POST http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "rag-unknown", "messages": [{"role": "user", "content": "Hello"}]}'
```

Expected results:

- `/healthz` returns `{"status":"ok"}`.
- `/v1/models` lists six models: `rag-semantic`, `rag-hybrid`, `rag-hybrid-reranked`, `rag-structured`, `rag-decomposition`, `rag-hyde`.
- Each `/v1/query` call returns `status` `not_implemented`, `results` empty, and a `message` saying the selected mode (for example `semantic`) is not implemented yet. `pattern` echoes the selected mode.
- The invalid `/v1/query` call returns HTTP 422 with a `detail` list that names the failing fields.
- Non-streaming chat returns `object` `chat.completion` with the placeholder text in `choices[0].message.content`.
- Streaming chat returns SSE frames (role, content, stop) and ends with `data: [DONE]`.
- The unknown model returns HTTP 404 with an OpenAI-style `error` envelope (`code` `model_not_found`).
