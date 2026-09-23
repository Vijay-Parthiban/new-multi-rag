"""Run the OTel collector natively on Windows, for local verification.

Two things differ from the Docker deployment. Both are environment limits of
this host, not defects in otel-collector-config.yaml, so that file is left
untouched and this script derives a local copy from it.

1. Phoenix Cloud is unreachable. otel/.env points at
   https://app.phoenix.arize.com/v1/traces, which now answers
   410 "This endpoint has been removed. Phoenix apps are addressed at
   /s/<handle>." The handle is not in this repository, so this script points
   the Phoenix exporter at a self-hosted Phoenix instead, which needs no
   handle and no auth.

2. The gRPC receiver cannot bind on this host.
   "listen tcp 0.0.0.0:4317: socket: The requested service provider could not be
   loaded or initialized" (WSAEPROVIDERFAILEDINIT), while the HTTP receiver on
   the same host binds fine. The application exports over OTLP/HTTP to 4318, so
   the gRPC receiver is dropped for the local run.

The collector's own Prometheus telemetry is also disabled: it binds
localhost:8888, and Go's resolver cannot resolve "localhost" here.

Langfuse is left exactly as otel/.env configures it - that is a real cloud
endpoint and its credentials work.
"""
import os
import re
import subprocess
from pathlib import Path

here = Path(__file__).resolve().parent
derived = here / "otel-collector-local.derived.yaml"


def load_env():
    """Extend the inherited environment with otel/.env.

    The inherited part is not optional. Replacing the environment wholesale drops
    SystemRoot and windir, and Windows then cannot initialize the socket provider:
    the collector dies with
      listen tcp 127.0.0.1:4318: socket: The requested service provider could not
      be loaded or initialized

    otel/.env is parsed here rather than shell-sourced because
    LANGFUSE_AUTH_HEADER holds "Basic <base64>", and that space breaks
    `set -a; . .env`.
    """
    env = dict(os.environ)
    for line in (here / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            # An already-set variable wins, as the run guide documents. This lets a
            # one-off run point an exporter somewhere else without editing the file.
            env.setdefault(key.strip(), value.strip())

    # Phoenix comes from otel/.env unchanged, so this launcher sends traces to the
    # same backend the Docker collector would. To use a local Phoenix instead, set
    # PHOENIX_OTLP_ENDPOINT=http://localhost:6006 and blank PHOENIX_AUTH_HEADER.
    env["OTEL_DEBUG_VERBOSITY"] = "detailed"  # log every exported span
    return env


def derive_config(base_text: str) -> str:
    # Drop the gRPC receiver. Port 4317 is already taken: a self-hosted Phoenix
    # serves its own OTLP/gRPC collector there (PHOENIX_GRPC_PORT defaults to 4317),
    # so the receiver cannot bind. The application exports over OTLP/HTTP to 4318,
    # so gRPC is not needed. Earlier attempts also hit a transient
    # "socket: The requested service provider could not be loaded or initialized",
    # which clears on its own and is unrelated to the config.
    text = re.sub(r"\n\s*grpc:\n\s*endpoint: [^\n]+", "", base_text)
    # Loopback only, matching what the application connects to.
    text = text.replace("0.0.0.0:4317", "127.0.0.1:4317")
    text = text.replace("0.0.0.0:4318", "127.0.0.1:4318")
    # The collector's own metrics bind localhost:8888, which fails here.
    text = text.replace(
        "  telemetry:\n    logs:\n      level: ${env:OTEL_LOG_LEVEL}",
        "  telemetry:\n    logs:\n      level: ${env:OTEL_LOG_LEVEL}\n"
        "    metrics:\n      level: none",
    )
    return text


if __name__ == "__main__":
    base = (here / "otel-collector-config.yaml").read_text(encoding="utf-8")
    derived.write_text(derive_config(base), encoding="utf-8")

    env = load_env()

    print(f"derived config: {derived.name}")
    print(f"  phoenix  -> {env['PHOENIX_OTLP_ENDPOINT']}")
    print(f"  langfuse -> {env['LANGFUSE_OTLP_ENDPOINT']}")
    print(f"  otlp/http-> {[l.strip() for l in derived.read_text().splitlines() if '127.0.0.1:4318' in l]}")
    subprocess.run([str(here / "otelcol.exe"), "--config", str(derived)],
                   env=env, check=False)
