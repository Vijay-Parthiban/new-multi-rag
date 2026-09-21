"""End-to-end check for the guardrails config surface and the offline evaluation.

Seeds the bundled ``golden/guardrails-dataset.json``, runs it against a guardrails config
built here, and checks the scores. Creates its own fixtures and deletes them in a
``finally`` block, so it is safe to re-run. Run from rag-retrieval-chat-manager/backend
against the live stack:

    uv run python scripts/e2e_guardrails.py

The guardrails service must be on 18000 and the retrieval API on 8001.
"""

from __future__ import annotations

import sys
import uuid

import httpx

from rag_shared.config import Settings

RUN_TAG = uuid.uuid4().hex[:6]
CONFIG_NAME = f"E2E Golden {RUN_TAG}"

# The config mirrors what the bundled dataset expects.
BANNED_WORDS = ["codename", "internal_only"]
PII_ENTITIES = ["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "US_SSN", "IP_ADDRESS"]

TRACE: list[str] = []
FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    TRACE.append(f"{'PASS' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    print(TRACE[-1], flush=True)
    if not ok:
        FAILURES.append(label)


class Api:
    """Fails loudly instead of returning a mock, so a down service is visible."""

    def __init__(self, settings: Settings) -> None:
        self.retrieval = f"http://localhost:{settings.api_port}"
        self.guardrails = settings.guardrails_url.rstrip("/")
        self.headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
        self.client = httpx.Client(timeout=300.0, headers=self.headers)

    def request(self, method: str, url: str, body: dict | None = None) -> tuple[int, object]:
        response = self.client.request(method, url, json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return response.status_code, payload


def main() -> int:
    settings = Settings()
    api = Api(settings)

    # ── The service catalog drives the Guard Config page ─────────────
    status, catalog = api.request("GET", f"{api.guardrails}/catalog")
    check("catalog is served", status == 200, f"HTTP {status}")
    validators = catalog.get("validators", []) if isinstance(catalog, dict) else []
    check("catalog lists validators", len(validators) >= 10, f"{len(validators)} validators")

    unavailable = [v["id"] for v in validators if not v.get("available")]
    check("every catalog validator is installed", not unavailable, ", ".join(unavailable))

    ids = {v["id"] for v in validators}
    check(
        "the real validators are present",
        {"ban_list", "detect_pii", "toxic_language"} <= ids,
        f"missing: {sorted({'ban_list', 'detect_pii', 'toxic_language'} - ids)}",
    )

    with_params = [v for v in validators if v.get("params")]
    check("validators expose parameters", len(with_params) >= 8, f"{len(with_params)} with params")

    tox = next((v for v in validators if v["id"] == "toxic_language"), {})
    check(
        "the LLM judge exposes a threshold",
        any(p["name"] == "threshold" for p in tox.get("params", [])),
    )

    # ── The retrieval API forwards the catalog ───────────────────────
    status, guards = api.request("GET", f"{api.retrieval}/guardrails/guards")
    check("GET /guardrails/guards proxies the catalog", status == 200 and isinstance(guards, list),
          f"HTTP {status}")

    status, on_fail = api.request("GET", f"{api.retrieval}/guardrails/on-fail-options")
    check("GET /guardrails/on-fail-options works", status == 200 and isinstance(on_fail, list),
          f"HTTP {status}")

    config_id = None
    run_id = None
    try:
        # ── Create a config with per-validator parameters ────────────
        status, config = api.request(
            "POST",
            f"{api.retrieval}/guardrails/configs",
            {
                "name": CONFIG_NAME,
                "description": f"e2e {RUN_TAG}",
                "guards": ["ban_list", "detect_pii", "toxic_language"],
                "mode": "both",
                "settings": {
                    "ban_list": {"banned_words": BANNED_WORDS, "max_l_dist": 0, "on_fail": "noop"},
                    "detect_pii": {"pii_entities": PII_ENTITIES, "on_fail": "noop"},
                    "toxic_language": {"threshold": 0.5, "on_fail": "noop"},
                },
            },
        )
        check("config create accepts per-validator settings", status == 201, f"HTTP {status}")
        if status != 201:
            return 1
        config_id = config["id"]
        check(
            "settings come back keyed by validator",
            set(config["settings"]) == {"ban_list", "detect_pii", "toxic_language"},
            str(list(config["settings"])),
        )
        check(
            "the numeric parameter survives the round trip",
            config["settings"]["ban_list"].get("max_l_dist") == 0,
            str(config["settings"]["ban_list"]),
        )
        check(
            "on_fail is stored with the parameters",
            config["settings"]["ban_list"].get("on_fail") == "noop",
        )

        # A bad parameter must be rejected at save time, not at chat time.
        status, detail = api.request(
            "POST",
            f"{api.retrieval}/guardrails/configs",
            {
                "name": f"E2E Bad {RUN_TAG}",
                "guards": ["ban_list"],
                "mode": "both",
                "settings": {"ban_list": {"banned_words": [], "on_fail": "noop"}},
            },
        )
        check("an empty required parameter is rejected", status == 422, f"HTTP {status}")

        # ── Seed and run the bundled golden dataset ──────────────────
        status, seeded = api.request(
            "POST", f"{api.retrieval}/guardrails-evaluate/datasets/seed", {"replace": True}
        )
        check("the bundled golden dataset seeds", status == 200, f"HTTP {status} {seeded}")
        if status != 200:
            return 1
        check("the dataset has 12 rows", seeded.get("item_count") == 12, str(seeded))

        dataset_id = seeded["dataset_id"]

        status, started = api.request(
            "POST",
            f"{api.retrieval}/guardrails-evaluate/runs",
            {"dataset_id": dataset_id, "guardrails_config_id": config_id},
        )
        check("the evaluation run starts", status == 200, f"HTTP {status}")
        if status != 200:
            return 1
        run_id = started["run_id"]
        check("the run reports a status", bool(started.get("status")), str(started))

        status, run = api.request("GET", f"{api.retrieval}/guardrails-evaluate/runs/{run_id}")
        check("the run is readable", status == 200, f"HTTP {status}")

        metrics = (run.get("aggregate_metrics") or {}) if isinstance(run, dict) else {}
        check("the run completed", run.get("status") == "completed", str(run.get("status")))
        check(
            "no row failed to run",
            metrics.get("items_failed") == 0,
            str(metrics.get("items_failed")),
        )
        check(
            "every row was evaluated",
            metrics.get("items_evaluated") == 12,
            str(metrics.get("items_evaluated")),
        )
        # This is the headline result: the shipped config must score perfectly on the
        # shipped dataset. A miss here means a guard regressed.
        check(
            "the config scores 1.0 on the golden dataset",
            metrics.get("accuracy") == 1.0,
            f"accuracy={metrics.get('accuracy')} fn={metrics.get('false_negatives')} "
            f"fp={metrics.get('false_positives')}",
        )
        check(
            "there are no false negatives",
            metrics.get("false_negatives") == 0,
            str(metrics.get("false_negatives")),
        )
        check(
            "there are no false positives",
            metrics.get("false_positives") == 0,
            str(metrics.get("false_positives")),
        )
        check(
            "the blocking guard matches the label on every blocked row",
            metrics.get("guard_match_rate") == 1.0,
            str(metrics.get("guard_match_rate")),
        )
        check(
            "all four scores are reported",
            all(key in metrics for key in ("accuracy", "precision", "recall", "f1")),
            str(sorted(metrics)),
        )

        status, items = api.request(
            "GET", f"{api.retrieval}/guardrails-evaluate/runs/{run_id}/items"
        )
        rows = items.get("items", []) if isinstance(items, dict) else []
        check("every row is returned", len(rows) == 12, str(len(rows)))

        # The bundled dataset carries one PII row with a spaced card number. The old
        # regex stub missed it, so assert specifically that it blocks.
        card_rows = [r for r in rows if "4111 1111 1111 1111" in r.get("text", "")]
        check(
            "the spaced card number is caught",
            bool(card_rows) and card_rows[0]["actual_blocked"] is True,
            str(card_rows[0] if card_rows else "row not found"),
        )

        # The old toxic stub always passed. Assert the two toxic rows block.
        toxic_rows = [r for r in rows if r.get("category") == "toxic"]
        check(
            "both toxic rows block",
            len(toxic_rows) == 2 and all(r["actual_blocked"] for r in toxic_rows),
            str([(r["actual_blocked"], r.get("actual_guard")) for r in toxic_rows]),
        )

        # ── The chat path records a trace with the richer results ────
        status, chat = api.request(
            "POST",
            f"{api.retrieval}/chat",
            {"query": "please use the codename here", "guardrails_config_id": config_id},
        )
        check("chat accepts a guardrails config", status == 200, f"HTTP {status}")
        check(
            "chat blocks the banned word",
            isinstance(chat, dict) and "blocked" in str(chat.get("answer", "")).lower(),
            str(chat.get("answer"))[:120] if isinstance(chat, dict) else str(chat),
        )

        status, traces = api.request("GET", f"{api.retrieval}/guardrails/traces?limit=5")
        check("traces are readable", status == 200, f"HTTP {status}")
        recent = traces.get("items", []) if isinstance(traces, dict) else []
        matching = [t for t in recent if t.get("config_id") == config_id]
        check("the blocked turn was traced", bool(matching), f"{len(matching)} matching traces")
        if matching:
            results = matching[0].get("guard_results") or {}
            check(
                "the trace carries a per-validator result",
                "ban_list" in results and "validation_passed" in results["ban_list"],
                str(sorted(results)),
            )

    finally:
        if run_id:
            pass  # runs cascade with their dataset
        if config_id:
            api.request("DELETE", f"{api.retrieval}/guardrails/configs/{config_id}")

    print(f"\n{len(TRACE) - len(FAILURES)}/{len(TRACE)} checks passed")
    if FAILURES:
        print("failed: " + ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
