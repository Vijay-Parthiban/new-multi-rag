# Pipeline Test — a policy site with a production chatbot

A demonstration project that calls a RAG pipeline's **own endpoint**, the way any future project
would. It is a corporate policy page for Tata Consultancy Services with one chat window.

Nothing here is a test harness: every request goes to the pipeline endpoint and carries no
trace-mode header, so the platform records all of it as production.

## The two conditions

Whether a conversation is remembered is decided by the pipeline's **Knowledge Product**: an
enabled Redis destination. This project does not decide it, and cannot override it.

| | Condition 1 | Condition 2 |
|---|---|---|
| Knowledge Product | Redis enabled | no Redis destination |
| `MEMORY_STATE` in `.env` | `enabled` | `disabled` |
| The window offers | **Start Session** | **Start Chat** |
| While it runs | the conversation is remembered | each question is answered alone |
| Ending it | **End Session** — confirmation, then the session closes, is exported as one trace, and its memory is removed | **End Chat** — confirmation, then the chat closes |
| Afterwards | back to **Start Session** | back to **Start Chat** |
| Traces | one per Q/A, tagged `prod-session` | one per Q/A, tagged `prod-stateless` |
| On ending | one more trace holding the whole conversation | none: each turn was already traced |
| Every trace carries | the complete pipeline config and the complete Knowledge Product config | the same |

## Configuration

`backend/.env` is the only place anything is named.

```ini
MEMORY_STATE=enabled
CHATBOT_1_LABEL=TCS Policy Assistant
CHATBOT_1_ENDPOINT=http://localhost:8001/api/assistants/tcs-chat
```

`MEMORY_STATE` is the project's declaration of which kind of assistant it is. It chooses the
words and the buttons.

The endpoint is the assistant root. The backend appends `/chat`, `/chat/stream` and
`/sessions/{id}`, because those routes belong to the same pipeline.

Add a second entry to offer a picker:

```ini
CHATBOT_2_LABEL=Resume Assistant
CHATBOT_2_ENDPOINT=http://localhost:8001/api/assistants/no-mem-pipeline
```

### The declaration is checked, not trusted

`MEMORY_STATE` does not switch memory on or off. The platform decides that, from the pipeline.
So the page compares the two and says so when they disagree, rather than promising memory it
cannot get:

| Declaration | Pipeline | What the page says |
|---|---|---|
| `enabled` | keeps the conversation | nothing. Start Session, End Session |
| `enabled` | does not keep one | a warning: it declares memory it cannot get, and the turns are tagged `prod-stateless` |
| `disabled` | does not keep one | nothing. Start Chat, End Chat |
| `disabled` | keeps the conversation | a warning: the platform still remembers, and the turns are tagged `prod-session` |

The End button always follows what the pipeline will actually do, so pressing it never does
something other than what its label promises.

## Run it

Prerequisites: both stacks running, and the two pipelines existing. Check one:

```bash
curl http://localhost:8001/api/assistants/tcs-chat
```

### Backend

```bash
cd pipeline-test/backend
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
cp .env.example .env
.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8090 --env-file .env
```

Port 8090. Keep `--env-file .env`: the application reads plain environment variables and does
not load the file by itself. On start it logs every configured endpoint.

### Frontend

```bash
cd pipeline-test/frontend
npm install
npm run dev
```

Open <http://localhost:5175>.

## The flow

```
        ┌──────────────────────────┐
        │  Start Session           │   the window waits here
        │  (or Start Chat)         │
        └────────────┬─────────────┘
                     │ press it
        ┌────────────▼─────────────┐
        │  empty chat + textbox    │   the first Q/A is remembered
        │  End Session             │   (condition 1 only)
        └────────────┬─────────────┘
                     │ press it, then confirm
        ┌────────────▼─────────────┐
        │  the session is exported │   one trace holding every Q/A
        │  the memory is removed   │
        └────────────┬─────────────┘
                     │
        back to ─────┘  Start Session, with what happened reported
```

**Check memory** reads the session back from the platform and reports the stored turns and the
remaining TTL. It is the deterministic proof: it does not depend on how the model answers.

## Files

| File | Purpose |
|---|---|
| `backend/main.py` | FastAPI proxy: chat, stream, session read and session close |
| `backend/.env.example` | `MEMORY_STATE` and the pipeline endpoints |
| `frontend/src/App.tsx` | The policy page and the chat window |
| `frontend/src/api.ts` | Types, the event-stream reader and the session calls |

## How a request reaches a pipeline

```
Browser  ->  /api/chat/stream                    (demo backend, port 8090)
         ->  {CHATBOT_1_ENDPOINT}/chat/stream    (retrieval API, port 8001)
         ->  the configured pipeline
```

The demo backend relays the server-sent events unchanged. Ending a conversation goes to
`{CHATBOT_1_ENDPOINT}/sessions/{id}/close`, which is the pipeline's own close route.

## Notes

- The policy text is illustrative sample content and is not an official TCS publication. The
  assistant answers from the knowledge base named on its panel, not from the text.
- Conversations are stored on the retrieval side, so they appear in the Chat page history and in
  Real Time Monitoring, tagged `prod`.
- The same e2e used for the Chat page covers this path:
  `python scripts/e2e_chat_session_traces.py prod` in `rag-retrieval-chat-manager/backend`.
