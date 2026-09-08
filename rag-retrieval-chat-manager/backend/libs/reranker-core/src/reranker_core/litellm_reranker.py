from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI
from rag_shared.chunk_utils import image_data_uri, is_image_chunk, passage_text_for_chunk
from rag_shared.config import Settings
from rag_shared.types import RetrievedChunk, RerankedChunk

from reranker_core.noop import NoopReranker

logger = logging.getLogger(__name__)

DEFAULT_RERANKER_MODEL = "nvidia-rerank"


def is_vl_rerank_model(model_name: str) -> bool:
    lowered = model_name.lower()
    return (
        "nvidia-rerank" in lowered
        or "nemotron" in lowered
        or "rerank-vl" in lowered
    )


def supports_upstream_top_n(model_name: str) -> bool:
    """NVIDIA NIM rerank models score all documents and reject top_n/top_k upstream."""
    return not is_vl_rerank_model(model_name)


def build_rerank_request_body(
    *,
    model_name: str,
    query: str,
    documents: list[str | dict[str, str]],
    top_k: int,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model_name,
        "query": query,
        "documents": documents,
    }
    if supports_upstream_top_n(model_name):
        body["top_n"] = top_k
    return body


def build_rerank_documents(
    chunks: list[RetrievedChunk],
    *,
    vl: bool,
) -> list[str | dict[str, str]]:
    documents: list[str | dict[str, str]] = []
    for chunk in chunks:
        if is_image_chunk(chunk):
            caption = passage_text_for_chunk(chunk)
            if vl:
                passage: dict[str, str] = {"text": caption}
                data_uri = image_data_uri(chunk)
                if data_uri:
                    passage["image"] = data_uri
                documents.append(passage)
            else:
                documents.append(caption)
        elif vl:
            documents.append({"text": chunk.content})
        else:
            documents.append(chunk.content)
    return documents


class LiteLLMReranker:
    """Rerank via LiteLLM proxy POST /v1/rerank (model alias e.g. nvidia-rerank)."""

    def __init__(
        self,
        settings: Settings,
        model_name: str = DEFAULT_RERANKER_MODEL,
    ) -> None:
        self.model_name = model_name
        self._vl = is_vl_rerank_model(model_name)
        self._client = OpenAI(
            base_url=settings.litellm_base_url.rstrip("/"),
            api_key=settings.openai_api_key,
        )

    def rerank(
        self,
        query: str,
        chunks: list[RetrievedChunk],
        top_k: int,
    ) -> list[RerankedChunk]:
        if not chunks:
            return []

        documents = build_rerank_documents(chunks, vl=self._vl)

        response = self._client.post(
            path="/v1/rerank",
            body=build_rerank_request_body(
                model_name=self.model_name,
                query=query,
                documents=documents,
                top_k=top_k,
            ),
            cast_to=object,
        )

        scores = self._parse_scores(response, len(chunks))

        ranked = sorted(
            zip(chunks, scores, strict=True),
            key=lambda pair: pair[1],
            reverse=True,
        )[:top_k]

        logger.info(
            "rerank_completed model=%s vl=%s chunks=%d top_k=%d",
            self.model_name,
            self._vl,
            len(chunks),
            top_k,
        )
        return [
            RerankedChunk(
                **chunk.model_dump(),
                rerank_score=float(score),
            )
            for chunk, score in ranked
        ]

    @staticmethod
    def _parse_scores(response_body: Any, count: int) -> list[float]:
        """Extract per-document relevance scores from the LiteLLM rerank response."""
        if isinstance(response_body, dict):
            # NVIDIA: {"rankings": [{"index": 0, "logit": 0.9}, ...]}
            rankings = response_body.get("rankings")
            if isinstance(rankings, list) and rankings:
                scores = [0.0] * count
                for item in rankings:
                    if not isinstance(item, dict):
                        continue
                    index = item.get("index", item.get("corpus_id"))
                    score = item.get(
                        "logit",
                        item.get("relevance_score", item.get("score")),
                    )
                    if index is not None and score is not None:
                        idx = int(index)
                        if 0 <= idx < count:
                            scores[idx] = float(score)
                if any(s != 0.0 for s in scores):
                    return scores

            # Cohere-compatible: {"results": [{"index": 0, "relevance_score": 0.9}, ...]}
            results = response_body.get("results") or response_body.get("data")
            if isinstance(results, list) and results:
                scores = [0.0] * count
                for item in results:
                    if not isinstance(item, dict):
                        continue
                    index = item.get("index")
                    score = item.get("relevance_score", item.get("score"))
                    if index is not None and score is not None:
                        idx = int(index)
                        if 0 <= idx < count:
                            scores[idx] = float(score)
                if any(s != 0.0 for s in scores):
                    return scores

            if isinstance(response_body.get("scores"), list):
                raw = [float(s) for s in response_body["scores"]]
                if len(raw) == count:
                    return raw

        if isinstance(response_body, list):
            if response_body and isinstance(response_body[0], dict):
                scores = [0.0] * count
                for item in response_body:
                    if not isinstance(item, dict):
                        continue
                    index = item.get("index")
                    score = item.get(
                        "logit",
                        item.get("relevance_score", item.get("score")),
                    )
                    if index is not None and score is not None:
                        idx = int(index)
                        if 0 <= idx < count:
                            scores[idx] = float(score)
                if any(s != 0.0 for s in scores):
                    return scores
            return [float(s) for s in response_body]

        raise ValueError(f"Unexpected rerank response shape: {response_body!r}")


def build_reranker(settings: Settings, *, enabled: bool, model: str | None = None):
    """Return LiteLLM reranker or noop pass-through when disabled."""
    if not enabled:
        return NoopReranker()

    return LiteLLMReranker(settings, model_name=model or settings.reranker_model)
