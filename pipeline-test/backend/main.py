"""Policy-site chatbot backend.

Every pipeline this chatbot may use is described in `.env`. Nothing about a
pipeline is hard-coded here, so pointing the assistant at another pipeline is an
edit to one line of `.env` and a restart.

One entry is one chatbot:

    CHATBOT_1_LABEL=TCS Policy Assistant
    CHATBOT_1_ENDPOINT=http://localhost:8001/api/assistants/tcs-chat

The endpoint is the assistant root. This service appends `/chat`, `/chat/stream` and
`/sessions/{id}`, because those three routes belong to the same pipeline.

The page presents one conversation. When `.env` holds more than one entry, the
page offers a picker; it does not compare them.

This is the production path. Every request goes to the pipeline endpoint and carries no
trace-mode header, so the platform records the turns as production and tags them
`prod-session` or `prod-stateless`. The tag is derived by the platform from whether that
pipeline's Knowledge Product keeps a conversation, never from anything sent here.

`MEMORY_STATE` says which kind of project this is. It decides the page's words and its
buttons, and it is compared against what the pipeline reports, so a project that declares
memory it cannot get is told so on the page rather than silently answering stateless.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("chatbot")
logging.basicConfig(level=logging.INFO)

# Generation takes seconds and the stream stays open for the whole answer.
TIMEOUT_S = float(os.getenv("RAG_API_TIMEOUT_S", "300"))

# The project's declaration of which kind of assistant it is. It chooses the words the page
# uses — Start Session and End Session, or Start Chat and End Chat — and it is checked against
# what the pipeline can actually do, so the page never promises memory the pipeline cannot keep.
#
#   enabled   every conversation is a session, and it is ended explicitly
#   disabled  each question is answered on its own
MEMORY_STATE = (os.getenv("MEMORY_STATE", "enabled") or "").strip().lower()
if MEMORY_STATE not in ("enabled", "disabled"):
    logger.warning("MEMORY_STATE=%r is neither enabled nor disabled; using enabled", MEMORY_STATE)
    MEMORY_STATE = "enabled"


@dataclass(frozen=True)
class Chatbot:
    """One configured pipeline."""

    id: str
    label: str
    endpoint: str

    def route(self, suffix: str = "") -> str:
        return f"{self.endpoint}{suffix}"


def load_chatbots() -> list[Chatbot]:
    """Read the chatbot list from the environment.

    The list ends at the first number with no endpoint, so a commented-out pair
    at the bottom of `.env` is inert and adding a pipeline is a copy of two lines.
    """
    chatbots: list[Chatbot] = []
    index = 1
    while True:
        endpoint = (os.getenv(f"CHATBOT_{index}_ENDPOINT") or "").strip()
        if not endpoint:
            break
        label = (os.getenv(f"CHATBOT_{index}_LABEL") or "").strip() or f"Chatbot {index}"
        chatbots.append(Chatbot(id=str(index), label=label, endpoint=endpoint.rstrip("/")))
        index += 1
    return chatbots


CHATBOTS: list[Chatbot] = load_chatbots()

# Reported once, at import. A missing endpoint is the first thing to notice on a
# failed start, so it is logged rather than raised: the page then explains it.
if not CHATBOTS:
    logger.error("No chatbot is configured. Set CHATBOT_1_ENDPOINT in backend/.env.")
for _configured in CHATBOTS:
    logger.info("chatbot %s -> %s (%s)", _configured.id, _configured.endpoint, _configured.label)

app = FastAPI(title="Policy site chatbot", version="0.2.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def _bot(chatbot_id: str) -> Chatbot:
    for bot in CHATBOTS:
        if bot.id == chatbot_id:
            return bot
    raise HTTPException(status_code=404, detail=f"Unknown chatbot '{chatbot_id}'.")


def _default_bot() -> Chatbot:
    if not CHATBOTS:
        raise HTTPException(
            status_code=503,
            detail=(
                "No chatbot is configured. Copy backend/.env.example to backend/.env, set "
                "CHATBOT_1_ENDPOINT to the assistant you want, and restart."
            ),
        )
    return CHATBOTS[0]


def _resolve(chatbot_id: str | None) -> Chatbot:
    return _default_bot() if not chatbot_id else _bot(chatbot_id)


def _as_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"detail": response.text}


def _relay(response: httpx.Response) -> JSONResponse:
    """Pass a retrieval-API response through with its own status and body.

    A 422 from a session route is a normal answer: it is how the API reports that
    the pipeline has no session memory. The page needs the code and the message.
    """
    return JSONResponse(status_code=response.status_code, content=_as_json(response))


class ChatBody(BaseModel):
    message: str = Field(..., min_length=1)
    session_id: str | None = Field(
        default=None, description="Send this back to continue the same conversation."
    )
    chatbot: str | None = Field(
        default=None, description="Configured chatbot id. Defaults to the first one."
    )


def _payload(body: ChatBody) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": body.message}
    if body.session_id:
        payload["session_id"] = body.session_id
    return payload


@app.get("/api/assistants")
async def list_chatbots() -> dict[str, Any]:
    """Every configured chatbot, with the state its pipeline reports.

    The page renders its labels and badges from this, so a pipeline that gains or
    loses its Redis destination shows up without a frontend change.
    """
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for bot in CHATBOTS:
            entry: dict[str, Any] = {"id": bot.id, "label": bot.label}
            try:
                response = await client.get(bot.route())
                if response.status_code == 200:
                    entry.update(_as_json(response))
                else:
                    entry["error"] = f"HTTP {response.status_code}"
            except Exception as exc:  # noqa: BLE001 - report it, do not fail the page
                entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["label"] = bot.label  # the .env label wins over the pipeline name
            out.append(entry)

    error = None if CHATBOTS else (
        "No chatbot is configured. Copy backend/.env.example to backend/.env, set "
        "CHATBOT_1_ENDPOINT, and restart the backend."
    )
    return {
        "chatbots": out,
        # The project's declared mode, from .env. The page uses it for its words and buttons.
        "memory_state": MEMORY_STATE,
        # True when the declaration and the pipeline agree, per chatbot.
        "error": error,
    }


@app.post("/api/session/{session_id}/close")
async def close_session(session_id: str, chatbot: str | None = None) -> Any:
    """End the conversation on the pipeline endpoint, which is the production path.

    No trace-mode header is sent, so the platform records everything as production. When the
    pipeline keeps a conversation, the platform writes the whole session out as one trace and
    drops the memory; when it does not, there is nothing to export and nothing to clear. The
    response says which happened.
    """
    bot = _resolve(chatbot)
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.post(bot.route(f"/sessions/{session_id}/close"))
    return _relay(response)


@app.post("/api/chat")
async def chat(body: ChatBody) -> Any:
    """One question, one answer."""
    bot = _resolve(body.chatbot)
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        response = await client.post(bot.route("/chat"), json=_payload(body))
    return _relay(response)


@app.post("/api/chat/stream")
async def chat_stream(body: ChatBody) -> StreamingResponse:
    """The same turn, streamed.

    The retrieval API already emits server-sent events, so the bytes pass through
    unchanged. Re-encoding them here would only add a way to get it wrong.
    """
    bot = _resolve(body.chatbot)
    payload = _payload(body)

    async def frames() -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            async with client.stream("POST", bot.route("/chat/stream"), json=payload) as response:
                if response.status_code >= 400:
                    text = (await response.aread()).decode(errors="replace")
                    yield f"data: {json.dumps({'type': 'error', 'content': text})}\n\n".encode()
                    return
                async for chunk in response.aiter_raw():
                    yield chunk

    return StreamingResponse(
        frames(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/session/{session_id}")
async def read_session(session_id: str, chatbot: str | None = None) -> Any:
    """What the pipeline remembers for one session.

    422 when the Knowledge Product has no Redis destination. That is the answer
    the page shows as 'this pipeline keeps no conversation'.
    """
    bot = _resolve(chatbot)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(bot.route(f"/sessions/{session_id}"))
    return _relay(response)


@app.delete("/api/session/{session_id}")
async def end_session(session_id: str, chatbot: str | None = None) -> Any:
    """End the session and drop everything it remembered. Idempotent."""
    bot = _resolve(chatbot)
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.delete(bot.route(f"/sessions/{session_id}"))
    if response.status_code >= 400:
        return _relay(response)
    return {"ended": True, "session_id": session_id, "chatbot": bot.id}


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "memory_state": MEMORY_STATE,
        "chatbots": [{"id": b.id, "label": b.label, "endpoint": b.endpoint} for b in CHATBOTS],
    }
