"""Seed one assistant pipeline per evaluable RAG strategy over a Knowledge Product.

Run from rag-retrieval-chat-manager/backend against the live stack:

    uv run python scripts/seed_resume_strategy_pipelines.py --product Resume

This is a seed, not a probe: it deletes nothing and it is safe to re-run. A pipeline it
made before is updated rather than duplicated.

What it does:

  1. Finds the Knowledge Product (default: the first whose name contains "resume").
  2. Enables its Redis (cache_redisvl) destination when it has none, so a multi-turn
     evaluation run has the session memory it drives.
  3. Creates one assistant pipeline per evaluable strategy - vector, lexical, hybrid,
     self_rag, corrective - each with the chat model and embedding model the user already
     runs over that product.
  4. Prints the pipelines it made, and names the strategies the product cannot serve.

A strategy the product has no store for is reported and skipped, not failed: the lexical
strategy needs an OpenSearch destination and the hybrid strategy needs both stores.

The ingestion API must be on 8007 and the retrieval API on 8001. Ports and URLs come from
the retrieval ``Settings``, so the same env the API uses drives this.
"""

from __future__ import annotations

import argparse
import re

import httpx

from rag_shared.config import Settings

# The strategies offline evaluation can score. Image Vision RAG is absent: its answers come
# from page images, and retrieval-to-generation scoring reads text passages.
STRATEGIES = ("vector", "lexical", "hybrid", "self_rag", "corrective")

STRATEGY_LABELS = {
    "vector": "Vector search",
    "lexical": "Keyword search",
    "hybrid": "Hybrid",
    "self_rag": "Self-reflective",
    "corrective": "Corrective",
}

# One day, which is the catalogue default for the Redis destination.
REDIS_TTL_S = 86400

# Used only when no pipeline exists yet over the product.
FALLBACK_CHAT_MODEL = "Gpt-oss-120b"
FALLBACK_EMBEDDING_MODEL = "nvidia-embed-textonly"


def product_slug(name: str) -> str:
    """The same derivation the ingestion service uses to name a product's stores."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:32].strip("_") or "product"


class Api:
    """Fails loudly instead of returning a mock, so a down service is visible."""

    def __init__(self, settings: Settings) -> None:
        self.ingestion = settings.ingestion_service_url.rstrip("/")
        self.retrieval = f"http://localhost:{settings.api_port}"
        self.headers = {"X-API-Key": settings.api_key} if settings.api_key else {}
        self.client = httpx.Client(timeout=120.0, headers=self.headers)

    def request(self, method: str, url: str, body: dict | None = None) -> tuple[int, object]:
        response = self.client.request(method, url, json=body)
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        return response.status_code, payload

    def ingestion_call(self, method: str, path: str, body: dict | None = None):
        return self.request(method, f"{self.ingestion}{path}", body)

    def retrieval_call(self, method: str, path: str, body: dict | None = None):
        return self.request(method, f"{self.retrieval}{path}", body)


def pick_product(api: Api, wanted: str | None) -> dict:
    status, products = api.ingestion_call("GET", "/api/knowledge-products")
    if status != 200 or not isinstance(products, list):
        raise SystemExit(f"Cannot list Knowledge Products: HTTP {status} {products}")
    if not products:
        raise SystemExit("No Knowledge Product exists. Create one in the Ingestion Manager.")

    names = ", ".join(product["name"] for product in products)
    if wanted:
        for product in products:
            if product["name"].lower() == wanted.lower() or str(product["id"]) == wanted:
                return product
        raise SystemExit(f"No Knowledge Product matches '{wanted}'. Found: {names}")

    for product in products:
        if "resume" in product["name"].lower():
            return product
    raise SystemExit(f"No Knowledge Product name contains 'resume'. Found: {names}")


def ensure_redis(api: Api, product: dict) -> str:
    """Make sure the product remembers sessions. Returns the Redis key prefix.

    The update replaces the product's whole destination list - a type missing from the
    payload is deleted - so every existing destination travels back with the new one.
    """
    destinations = product.get("destinations") or []
    for dest in destinations:
        if dest.get("destination_type") == "cache_redisvl" and dest.get("enabled"):
            prefix = str((dest.get("config") or {}).get("index_prefix") or "")
            print(f"Redis already enabled on '{product['name']}' prefix={prefix}")
            return prefix

    payload = [
        {
            "destination_type": dest["destination_type"],
            "enabled": bool(dest.get("enabled")),
            "config": dest.get("config") or {},
        }
        for dest in destinations
    ]
    payload.append(
        {
            "destination_type": "cache_redisvl",
            "enabled": True,
            "config": {"ttl_seconds": REDIS_TTL_S},
        }
    )

    status, updated = api.ingestion_call(
        "PATCH", f"/api/knowledge-products/{product['id']}", {"destinations": payload}
    )
    if status != 200:
        raise SystemExit(f"Cannot enable Redis on '{product['name']}': HTTP {status} {updated}")

    prefix = next(
        (
            str((d.get("config") or {}).get("index_prefix") or "")
            for d in updated.get("destinations") or []
            if d.get("destination_type") == "cache_redisvl"
        ),
        "",
    )
    print(f"Enabled Redis on '{product['name']}' prefix={prefix}")
    return prefix


def models_in_use(pipelines: list[dict], product: dict) -> tuple[str, str]:
    """The chat and embedding models of a pipeline already over this product."""
    for pipeline in pipelines:
        if str(pipeline.get("knowledge_product_id")) != str(product["id"]):
            continue
        if pipeline.get("chat_model"):
            return pipeline["chat_model"], pipeline.get("embedding_model") or ""
    return (
        FALLBACK_CHAT_MODEL,
        product.get("text_embedding_model") or FALLBACK_EMBEDDING_MODEL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed one assistant pipeline per evaluable RAG strategy."
    )
    parser.add_argument(
        "--product",
        default=None,
        help=(
            "Knowledge Product name or id. Default: the first product whose name contains "
            "'resume'."
        ),
    )
    args = parser.parse_args()

    api = Api(Settings())
    product = pick_product(api, args.product)
    print(f"Product: {product['name']} ({product['id']})")

    ensure_redis(api, product)

    status, pipelines = api.ingestion_call("GET", "/api/pipelines")
    pipelines = pipelines if status == 200 and isinstance(pipelines, list) else []
    chat_model, embedding_model = models_in_use(pipelines, product)
    print(f"Models: chat={chat_model} embedding={embedding_model}")

    by_slug = {p.get("slug"): p for p in pipelines if p.get("slug")}
    by_name = {p.get("name"): p for p in pipelines if p.get("name")}

    made: list[dict] = []
    skipped: list[tuple[str, str]] = []

    for strategy in STRATEGIES:
        name = f"{product['name']} \u00b7 {STRATEGY_LABELS[strategy]}"
        slug = f"{product_slug(product['name'])}-{strategy}"
        fields = {
            "name": name,
            "description": (
                f"Offline evaluation pipeline for the '{strategy}' strategy over "
                f"'{product['name']}'."
            ),
            "slug": slug,
            "knowledge_product_id": product["id"],
            "rag_strategy": strategy,
            "chat_model": chat_model,
            "embedding_model": embedding_model,
        }

        existing = by_slug.get(slug) or by_name.get(name)
        if existing:
            status, payload = api.ingestion_call(
                "PATCH", f"/api/pipelines/{existing['id']}", fields
            )
            action = "updated"
        else:
            status, payload = api.ingestion_call("POST", "/api/pipelines", fields)
            action = "created"

        if status not in (200, 201):
            reason = payload.get("detail") if isinstance(payload, dict) else payload
            print(f"SKIP {strategy}: {reason}")
            skipped.append((strategy, str(reason)))
            continue

        made.append(
            {
                "strategy": strategy,
                "action": action,
                "id": payload["id"],
                "slug": payload.get("slug"),
                "name": payload["name"],
            }
        )

    print(f"\n{len(made)} pipelines over '{product['name']}':")
    for row in made:
        print(
            f"  {row['strategy']:<11} {row['action']:<8} id={row['id']} "
            f"slug={row['slug']} name={row['name']}"
        )
    if skipped:
        print("\nNot created (the product has no store for these):")
        for strategy, reason in skipped:
            print(f"  {strategy}: {reason}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
