# docker-pi

Run the [Pi coding-agent](https://github.com/earendil-works/pi) headless in Docker, one Pi
instance per container, and spawn **N** of them in parallel from Python. Pi is
one-session-per-process by design, so parallelism means one container per instance.

## Before you build: set your Azure endpoint in `models.json`

The provider `baseUrl` in [`models.json`](models.json) is **hardcoded** and baked into the image at
build time. pi only interpolates `$ENV_VAR` references in the `apiKey` and `headers` fields — **not**
in `baseUrl` — so a `"baseUrl": "$AZURE_API_BASE"` is passed through literally and the agent fails
every request with `Invalid URL` (empty responses, 0 tokens). You must edit `models.json` to your own
Azure AI endpoint before `docker build`:

```jsonc
{
  "providers": {
    "azure-anthropic": {
      // EDIT THIS to your Azure AI resource's Anthropic endpoint (origin + /anthropic).
      // pi appends the /v1/messages path itself.
      "baseUrl": "https://<your-resource>.services.ai.azure.com/anthropic",
      "api": "anthropic-messages",
      "apiKey": "$AZURE_API_KEY",   // resolved from the container env at runtime (never baked in)
      "headers": { "anthropic-version": "2023-06-01" },
      "models": [ /* ... */ ]
    }
  }
}
```

The `apiKey` stays as `$AZURE_API_KEY` — that field *is* env-interpolated, and the key is forwarded
into each container via `-e AZURE_API_KEY` (never written into the image). Only the `baseUrl` needs a
literal value. After editing, rebuild the image so the new `models.json` is baked in.

## Files

| File | Role |
|------|------|
| `Dockerfile` | Headless Pi image, **built from local monorepo source** (multi-stage: build → `npm pack` → install tarball), RPC mode, Azure config baked in. Built from source so it includes the `skill_invocation` RPC event added to the harness. |
| `Dockerfile.dockerignore` | Keeps the source build context (the repo root) from dragging in `node_modules`/`dist`/`.git` |
| `models.json` | Azure provider config baked into `~/.pi/agent/models.json` (Claude Opus 4.6 via the `/anthropic` endpoint). **Edit `baseUrl` to your Azure endpoint before building** — see the setup note above. |
| `spawn_pi.py` | Stdlib Python: `PiContainer` (RPC-over-stdio client), `PiInstance`/`PiPool` (managed long-lived), `spawn_n(...)` |
| `pi_server.py` | **FastAPI HTTP gateway** — one server, many sessions; the interface your runner's live UserProxy drives over HTTP |
| `test_multi.py` | Standalone test: open N instances, ping each, print replies + stats, close all |

## The HTTP gateway (`pi_server.py`) — for a live UserProxy

If your evaluation runner has a **live UserProxy** (e.g. driving agent-inspect) that needs to hold
conversations over HTTP, run `pi_server.py`. One long-lived server process owns N Pi containers,
addressed by session id.

```bash
docker build -t pi-sandbox docker-pi/
export AZURE_API_KEY=...
pip install fastapi uvicorn
python docker-pi/pi_server.py --host 0.0.0.0 --port 8000
```

### Endpoints

| Method & path | Purpose |
|---------------|---------|
| `POST /sessions` | Create a session (spawns one Pi container). Body `{}` or `{"workspace": "/host/path"}`. Returns `{"session_id": ...}` |
| `POST /sessions/{sid}/ask` | Send a user utterance. Body `{"utterance": "...", "timeout"?: 600}`. Returns `{"answer", "steps", "usage"}` |
| `GET /sessions/{sid}/stats` | Running token/cost totals for the session |
| `POST /sessions/{sid}/abort` | Interrupt the in-flight turn |
| `DELETE /sessions/{sid}` | Close the session (removes the container) |
| `GET /sessions` | List live session ids |
| `GET /healthz` | Liveness + live session count |

### Driving it from the runner

```python
import requests
BASE = "http://localhost:8000"

sid = requests.post(f"{BASE}/sessions", json={}).json()["session_id"]
try:
    r = requests.post(f"{BASE}/sessions/{sid}/ask",
                      json={"utterance": "what is 2+2?"}).json()
    print(r["answer"])   # final assistant text
    print(r["steps"])    # per-turn structured steps (tool calls, thinking, text)
    print(r["usage"])    # {"input", "output", "cost"} for the turn
    r2 = requests.post(f"{BASE}/sessions/{sid}/ask",
                       json={"utterance": "multiply by 10"}).json()  # same conversation
finally:
    requests.delete(f"{BASE}/sessions/{sid}")
```

**Concurrency:** `/ask` runs **concurrently across different sessions** (each Pi container is a
separate process, driven on a worker thread so the event loop stays free) and is **serialized within
a session** (Pi handles one turn at a time per container) via a per-session `asyncio.Lock`. So the
runner can hold many independent conversations in parallel without them blocking each other, while
each individual conversation stays strictly ordered.

**`steps` shape** — each turn returns a list of steps reconstructed from Pi's RPC event stream,
shaped as building blocks for agent-inspect's `Step` (the server does **not** assemble the
`TurnTrace` — your runner does, since it owns turn ids, ordering, and `agent_input`):

```jsonc
{
  "id": "c1",                                  // tool step: toolCallId; else synthetic "s3"
  "parent_ids": ["c0"],                        // previous step's id — a linear chain
  "tool": "bash",
  "tool_input_args": [{"name": "command", "value": "echo hi"}],
  "tool_output": "hi",
  "is_error": false,
  "status": "OK",                              // "OK" | "ERROR" (tool steps)
  "error": null,                               // error text when is_error (else null)
  "agent_thought": "...",                      // thinking step: model reasoning text
  "text": "final answer",                      // text step: assistant prose
  "skill_calls": [{"skill_id": "skill:x", "skill_name": "x"}],  // attached to first step
  "latency_in_ms": 250.0                       // wall clock for tool steps (start→end)
}
```

Tool steps come from `tool_execution_start`/`tool_execution_end` (correlated by `toolCallId`);
thinking/text steps from the `turn_end` assistant message content blocks.

The `/ask` response also carries turn-level fields alongside `steps`:

- **`usage`** — `{input, output, total, cost}` summed for the turn (Pi reports tokens per message,
  not per step, so token accounting lives here, not on each step).
- **`skill_calls`** — skill invocations, captured in **both** of Pi's invocation modes:
  1. **Explicit** — the utterance contains `/skill:<name>` (Pi expands it before the turn runs);
     detected from the utterance and attached to the first step.
  2. **Model-driven** (the default path) — the model decides to use a skill and loads it by
     `read`/`bash`-ing its `.../skills/<name>/SKILL.md` (Pi lists each skill's path in the system
     prompt). Detected from the tool step that reads the `SKILL.md` and attached to that step.

  Both feed the turn-level `skill_calls` list (deduped by `skill_id`). Note mode 2 is an
  *inference* — Pi emits no skill-specific event, so a skill the model applies without reading its
  `SKILL.md` (e.g. already in context) won't be detected.
- **`latency_in_ms`** — whole-turn wall clock.

**Shutdown:** the server tears down every container on exit (FastAPI lifespan → `close_all()`).

## Prerequisites

- Docker on PATH
- `AZURE_API_KEY` exported in your shell (forwarded into every container; the baked
  `models.json` reads it via `apiKey: "$AZURE_API_KEY"` — the key is **never** baked into the image)
- For the HTTP gateway only: `pip install fastapi uvicorn`. The stdlib Python API
  (`spawn_pi.py`, `PiInstance`/`PiPool`) needs no third-party packages.

## Build

Built from the **local monorepo source** (not the published npm package), so the image carries the
harness change that emits the `skill_invocation` RPC event. The build context is the **repo root**
(the whole workspace is compiled in a builder stage), so pass `-f`:

```bash
# from the repo root:
docker build -t pi-sandbox -f docker-pi/Dockerfile .
```

The builder stage runs `npm ci` + `npm run build:offline` and `npm pack`s the coding-agent; the slim
runtime stage installs just that tarball. First build is a few minutes (full toolchain); rebuilds are
cached unless source changes. `Dockerfile.dockerignore` keeps `node_modules`/`dist`/`.git` out of the
context.

## Run

### One-off smoke test (no Python)

```bash
export AZURE_API_KEY=...
printf '%s\n%s\n' \
  '{"type":"prompt","message":"say hi in 3 words"}' \
  '{"type":"get_last_assistant_text"}' \
| docker run --rm -i -e AZURE_API_KEY pi-sandbox
```

You should see streamed events followed by a `get_last_assistant_text` response with non-null text.

### N containers from Python (in-process, no HTTP)

Use this when the driver is a Python process on the same host and you don't need HTTP — otherwise
prefer the [HTTP gateway](#the-http-gateway-pi_serverpy--for-a-live-userproxy) above.


```bash
export AZURE_API_KEY=...
python docker-pi/spawn_pi.py --n 4 --image pi-sandbox --prompt "say hi in 3 words"
```

Prints each container's reply plus token/cost stats. `docker ps` shows N containers during the run
and none after (`--rm`).

### Long-lived instance (your runner pings it, then closes it)

This is the model to use when your agent runner wants to bring an instance up, send it user
utterances across one or more turns, then shut it down.

**From Python (recommended):**

```python
from spawn_pi import PiInstance

inst = PiInstance("pi-sandbox").open()      # brings the container up, stays alive
try:
    reply1 = inst.ask("what is 2+2?")        # ping with a user utterance
    reply2 = inst.ask("now multiply by 10")  # continues the SAME conversation
    print(reply1, reply2, inst.stats())
finally:
    inst.close()                             # shut it down when done

# or as a context manager (auto-closes):
with PiInstance("pi-sandbox") as inst:
    print(inst.ask("hello"))
```

`inst.ask(utterance)` blocks until that turn fully settles and returns the assistant text. Call it
as many times as you like — the in-memory conversation persists for the life of the instance.
`inst.abort()` interrupts an in-flight turn; `inst.stats()` returns running token/cost totals.

**Many long-lived instances, pinged by index** — one conversation per instance:

```python
from spawn_pi import PiPool

with PiPool(4, image="pi-sandbox") as pool:   # opens 4 containers concurrently
    print(pool.ask(0, "start conversation A"))
    print(pool.ask(1, "start conversation B"))
    print(pool.ask(0, "continue A"))          # instance 0 keeps its own session
# all four are closed on exit
```

**From the shell (line-oriented):** open one instance, feed one utterance per stdin line, Ctrl-D
to close.

```bash
export AZURE_API_KEY=...
python docker-pi/spawn_pi.py --serve --image pi-sandbox
```

### One-shot per-container logic (fire and tear down)

```python
from spawn_pi import PiContainer, spawn_n

with PiContainer("pi-sandbox") as pi:
    print(pi.prompt("list three prime numbers"))
    print(pi.stats())          # {'tokens': {...}, 'cost': ..., 'toolCalls': ...}

def task(pi):
    a = pi.prompt("what is 2+2?")
    b = pi.prompt("multiply that by 10")   # same session, multi-turn
    return a, b, pi.stats()

results = spawn_n(3, image="pi-sandbox", task=task, max_workers=3)
```

Each container gets its own workspace via `PiContainer(..., workspace="/host/path")`
(bind-mounted at `/workspace`). `PiInstance`/`PiPool` accept the same `workspace=` and `model=` kwargs.

## How it works

- **Transport:** `docker run -i` (no TTY needed). Python writes JSON commands to the container's
  stdin and reads JSON events/responses from stdout, one per line (LF-framed). See
  `packages/coding-agent/docs/rpc.md`.
- **Turn completion:** a prompt is considered done when the container emits `agent_settled`
  (fully settled — no retry/compaction/continuation pending), after which `get_last_assistant_text`
  returns the reply.
- **Response correlation:** each command carries an `id`; the matching `response` echoes it.
- **Shutdown:** there is no explicit RPC "exit" command — `close()` closes the container's stdin
  (EOF ends the Pi process) and then removes the container. Multi-turn conversation lives in the
  process's memory, so an instance stays coherent across `ask()` calls until you close it.

## Defaults (and how to change them)

The image launches Pi with `--mode rpc --no-extensions --no-session`:

- `--no-extensions` — guarantees **no human-in-the-loop / approval prompts**. Pi has no built-in
  approval gate; disabling extensions ensures none can be installed, so containers run fully
  autonomously.
- `--no-session` — stateless containers (no session files). Drop it and mount a writable
  `-v <vol>:/root/.pi/agent` if you want persistence.
- Model — defaults to `azure-anthropic/claude-opus-4-6` (image `CMD`). Override per run with
  `spawn_pi.py --model <provider/id>` or `PiContainer(..., model=...)`.

## Cleanup

```bash
docker rmi pi-sandbox
```

Nothing outside `docker-pi/` is created.
