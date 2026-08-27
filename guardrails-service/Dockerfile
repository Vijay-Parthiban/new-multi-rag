# syntax=docker/dockerfile:1
# ── Builder stage ────────────────────────────────────────────────────
# Uses python:3.12-slim so lxml 4.9.x has pre-built manylinux wheels
# (no apt-get install libxml2-dev needed → works behind firewalls).
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_ROOT_USER_ACTION=ignore
ENV NLTK_DATA=/usr/local/share/nltk_data
ENV TRANSFORMERS_VERBOSITY=error

WORKDIR /app

COPY pyproject.toml .

RUN pip install --no-cache-dir .

RUN mkdir -p "${NLTK_DATA}" \
    && python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

# Tokens come from .env.guardrails via Compose build secret (not ${VAR} interpolation).
RUN --mount=type=secret,id=guardrails_env \
    set -a && . /run/secrets/guardrails_env && set +a && \
    GUARDRAILS_TOKEN=$(printf '%s' "$GUARDRAILS_TOKEN" | tr -d '\r') && \
    export HF_TOKEN=$(printf '%s' "$HF_TOKEN" | tr -d '\r') && \
    test -n "$GUARDRAILS_TOKEN" || { echo "GUARDRAILS_TOKEN is empty — check .env.guardrails"; exit 1; } && \
    guardrails configure --enable-metrics --enable-remote-inferencing --token "${GUARDRAILS_TOKEN}" && \
    guardrails hub install hub://guardrails/ban_list && \
    guardrails hub install hub://guardrails/detect_pii && \
    guardrails hub install hub://guardrails/toxic_language

# Presidio (from detect_pii) needs a spaCy pipeline; sm keeps the image small.
RUN python -m spacy download en_core_web_sm

# Registry lives at /app/.guardrails (cwd); lazy hub imports need it at runtime.
RUN python -c "from guardrails.hub import BanList, DetectPII, ToxicLanguage"

# ── Runtime stage ────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV LOGLEVEL="DEBUG"
ENV GUARDRAILS_LOG_LEVEL="DEBUG"
ENV NLTK_DATA=/usr/local/share/nltk_data

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/share/nltk_data /usr/local/share/nltk_data
COPY --from=builder /usr/local/bin /usr/local/bin

COPY --from=builder /app/.guardrails /app/.guardrails
COPY --from=builder /root/.guardrailsrc /root/.guardrailsrc

COPY ./config.py ./config.py
COPY ./server.py ./server.py

ENV GR_CONFIG_FILE_PATH=/app/config.py

EXPOSE 8000

CMD ["uvicorn", "server:app", "--workers", "1", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "20", "--timeout-graceful-shutdown", "60"]
