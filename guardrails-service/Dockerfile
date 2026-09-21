# syntax=docker/dockerfile:1
# ── Builder stage ────────────────────────────────────────────────────
# Uses python:3.12-slim because guardrails-ai, Presidio and spaCy need wheels that exist
# for 3.12. Build-time network access is required: pip pulls the real Hub validators from
# public PyPI, and spaCy pulls its English model from GitHub releases.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_ROOT_USER_ACTION=ignore
ENV NLTK_DATA=/usr/local/share/nltk_data
ENV TRANSFORMERS_VERBOSITY=error

WORKDIR /app

COPY pyproject.toml .

# Installs guardrails-ai and the real Hub validators (guardrails-ai-<name>).
RUN pip install --no-cache-dir .

# DetectPII runs Presidio, which loads a spaCy pipeline. Presidio's default config asks for
# en_core_web_lg (about 590 MB). The small model is 12 MB and detects the same pattern-based
# entities, so point the default config at it. Fail the build if the file ever changes shape.
RUN python -m spacy download en_core_web_sm \
    && python - <<'PY'
import pathlib
import presidio_analyzer

conf = pathlib.Path(presidio_analyzer.__file__).parent / "conf" / "default.yaml"
text = conf.read_text()
if "model_name: en_core_web_lg" not in text:
    raise SystemExit("presidio default.yaml no longer pins en_core_web_lg; update the Dockerfile")
conf.write_text(text.replace("model_name: en_core_web_lg", "model_name: en_core_web_sm"))
print("presidio now uses en_core_web_sm")
PY

RUN mkdir -p "${NLTK_DATA}" \
    && python -c "import nltk; nltk.download('punkt', quiet=True); nltk.download('punkt_tab', quiet=True)"

# A missing ~/.guardrailsrc makes every Validator constructor raise.
RUN touch /root/.guardrailsrc \
    && printf 'enable_metrics=false\nuse_remote_inferencing=false\n' > /root/.guardrailsrc

# ── Runtime stage ────────────────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV NLTK_DATA=/usr/local/share/nltk_data
# Span export to the collector is not configured inside this container, so silence it.
ENV OTEL_SDK_DISABLED=true

WORKDIR /app

COPY --from=builder /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=builder /usr/local/share/nltk_data /usr/local/share/nltk_data
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.guardrailsrc /root/.guardrailsrc

COPY ./config.py ./config.py
COPY ./server.py ./server.py

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "20", "--timeout-graceful-shutdown", "60"]
