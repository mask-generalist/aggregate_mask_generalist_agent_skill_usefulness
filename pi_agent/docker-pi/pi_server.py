#!/usr/bin/env python3
"""HTTP gateway over a pool of Pi coding-agent containers.

One long-lived server process owns N Pi containers, addressed by session id. Your evaluation
runner (with its live UserProxy / agent-inspect loop) drives conversations over HTTP:

    POST   /sessions                      -> create a session (spawns one Pi container)
    POST   /sessions/{sid}/ask            -> send a user utterance, get {answer, steps, usage}
    GET    /sessions/{sid}/stats          -> running token/cost totals
    POST   /sessions/{sid}/abort          -> interrupt the in-flight turn
    DELETE /sessions/{sid}                 -> close the session (removes the container)
    GET    /sessions                      -> list session ids
    GET    /healthz                       -> liveness

Concurrency: /ask runs concurrently across DIFFERENT sessions (each Pi container is a separate
process, driven on a thread from a pool so the event loop stays free), and is serialized WITHIN
a session (Pi is single-session — one turn at a time per container). A per-session asyncio lock
enforces the in-session ordering.

Run:
    docker build -t pi-sandbox docker-pi/
    export AZURE_API_KEY=<your-key>
    pip install fastapi uvicorn
    python docker-pi/pi_server.py --host 0.0.0.0 --port 8000

Then from the runner:
    r = requests.post("http://localhost:8000/sessions", json={}).json()
    sid = r["session_id"]
    ans = requests.post(f"http://localhost:8000/sessions/{sid}/ask",
                        json={"utterance": "hello"}).json()
    requests.delete(f"http://localhost:8000/sessions/{sid}")
"""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from spawn_pi import PiInstance, PiError, DEFAULT_IMAGE, DEFAULT_PROMPT_TIMEOUT


# ── Session registry ──────────────────────────────────────────────────────────

class _Session:
    def __init__(self, instance: PiInstance) -> None:
        self.instance = instance
        # Serializes turns within this one session (Pi handles one turn at a time).
        self.lock = asyncio.Lock()


class SessionManager:
    def __init__(self, image: str, model: Optional[str]) -> None:
        self.image = image
        self.model = model
        self._sessions: dict[str, _Session] = {}
        self._registry_lock = asyncio.Lock()

    async def create(self, workspace: Optional[str] = None) -> str:
        sid = uuid.uuid4().hex[:12]
        inst = PiInstance(self.image, model=self.model, workspace=workspace,
                          name=f"pi-{sid}")
        # Container boot is blocking (docker run) — run it off the event loop.
        await asyncio.to_thread(inst.open)
        async with self._registry_lock:
            self._sessions[sid] = _Session(inst)
        return sid

    def get(self, sid: str) -> _Session:
        sess = self._sessions.get(sid)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"unknown session {sid!r}")
        return sess

    async def close(self, sid: str) -> None:
        async with self._registry_lock:
            sess = self._sessions.pop(sid, None)
        if sess is None:
            raise HTTPException(status_code=404, detail=f"unknown session {sid!r}")
        await asyncio.to_thread(sess.instance.close)

    async def close_all(self) -> None:
        async with self._registry_lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        await asyncio.gather(
            *(asyncio.to_thread(s.instance.close) for s in sessions),
            return_exceptions=True,
        )

    def ids(self) -> list[str]:
        return list(self._sessions.keys())


# ── Request/response models ─────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    workspace: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str


class AskRequest(BaseModel):
    utterance: str
    timeout: float = DEFAULT_PROMPT_TIMEOUT


class AskResponse(BaseModel):
    answer: str
    steps: list
    usage: dict
    skill_calls: list = []
    latency_in_ms: Optional[float] = None


# ── App factory ────────────────────────────────────────────────────────────────

def create_app(image: str = DEFAULT_IMAGE, model: Optional[str] = None) -> FastAPI:
    manager = SessionManager(image=image, model=model)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Ensure every container is torn down when the server stops.
        await manager.close_all()

    app = FastAPI(title="pi-gateway", lifespan=lifespan)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "sessions": len(manager.ids())}

    @app.get("/sessions")
    async def list_sessions() -> dict:
        return {"sessions": manager.ids()}

    @app.post("/sessions", response_model=CreateSessionResponse)
    async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
        sid = await manager.create(workspace=req.workspace)
        return CreateSessionResponse(session_id=sid)

    @app.post("/sessions/{sid}/ask", response_model=AskResponse)
    async def ask(sid: str, req: AskRequest) -> AskResponse:
        sess = manager.get(sid)
        # Serialize turns within this session; different sessions proceed concurrently
        # because each awaits its own lock and runs its blocking turn on its own thread.
        async with sess.lock:
            try:
                result = await asyncio.to_thread(
                    sess.instance.ask_detailed, req.utterance, req.timeout
                )
            except PiError as e:
                raise HTTPException(status_code=502, detail=str(e))
        return AskResponse(**result)

    @app.get("/sessions/{sid}/stats")
    async def stats(sid: str) -> dict:
        sess = manager.get(sid)
        return await asyncio.to_thread(sess.instance.stats)

    @app.post("/sessions/{sid}/abort")
    async def abort(sid: str) -> dict:
        sess = manager.get(sid)
        await asyncio.to_thread(sess.instance.abort)
        return {"aborted": True}

    @app.delete("/sessions/{sid}")
    async def delete_session(sid: str) -> dict:
        await manager.close(sid)
        return {"closed": sid}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="HTTP gateway over a pool of Pi containers.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Docker image tag")
    parser.add_argument("--model", default=None, help="override model (default: image CMD)")
    args = parser.parse_args()

    if "AZURE_API_KEY" not in os.environ:
        parser.error("AZURE_API_KEY is not set in the environment")

    import uvicorn
    uvicorn.run(create_app(image=args.image, model=args.model),
                host=args.host, port=args.port)


if __name__ == "__main__":
    main()
