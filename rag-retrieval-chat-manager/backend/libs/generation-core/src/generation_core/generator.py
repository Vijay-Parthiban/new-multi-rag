from __future__ import annotations

import time
from collections.abc import Iterator

from openai import OpenAI
from rag_shared.chunk_utils import image_data_uri, split_chunks
from rag_shared.config import Settings
from rag_shared.types import RerankedChunk

from generation_core.prompt_builder import NO_SOURCES_ANSWER, build_fusion_prompt, build_rag_prompt
from generation_core.result import GenerationResult
from generation_core.vision_generator import VisionGenerator


class Generator:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = OpenAI(
            base_url=settings.litellm_base_url,
            api_key=settings.openai_api_key,
        )
        self._vision = VisionGenerator(
            base_url=settings.litellm_base_url,
            api_key=settings.openai_api_key,
            model=settings.vision_model,
        )

    def _generate_text(
        self,
        query: str,
        chunks: list[RerankedChunk],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        system_prompt: str | None = None,
    ) -> str:
        messages = build_rag_prompt(query, chunks, system_prompt=system_prompt)
        response = self._client.chat.completions.create(
            model=model or self._settings.chat_model,
            messages=messages,
            max_tokens=max_tokens or self._settings.chat_max_tokens,
            temperature=temperature if temperature is not None else self._settings.chat_temperature,
        )
        return response.choices[0].message.content or ""

    def _generate_vision(
        self,
        query: str,
        chunks: list[RerankedChunk],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        return self._vision.generate(
            query,
            chunks,
            model=model or self._settings.vision_model,
            max_tokens=max_tokens or self._settings.chat_max_tokens,
            temperature=temperature if temperature is not None else self._settings.chat_temperature,
        )

    def _fuse_answers(
        self,
        query: str,
        *,
        text_answer: str,
        vision_answer: str,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        messages = build_fusion_prompt(
            query,
            text_answer=text_answer,
            vision_answer=vision_answer,
        )
        response = self._client.chat.completions.create(
            model=model or self._settings.fusion_model,
            messages=messages,
            max_tokens=max_tokens or self._settings.chat_max_tokens,
            temperature=temperature if temperature is not None else self._settings.chat_temperature,
        )
        return response.choices[0].message.content or ""

    def generate_stream(
        self,
        query: str,
        chunks: list[RerankedChunk],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        system_prompt: str | None = None,
    ) -> Iterator[str]:
        """Yield the answer text in deltas.

        An image result cannot be streamed: it needs the vision pass and the
        fusion pass, and neither reports progress. When image chunks are
        present this falls back to one blocking call and yields the whole
        answer as a single delta, so the caller sees one token event.
        """
        text_chunks, image_chunks = split_chunks(chunks)

        if image_chunks:
            result = self.generate(
                query,
                chunks,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt,
            )
            if result.answer:
                yield result.answer
            return

        if not text_chunks:
            return

        messages = build_rag_prompt(query, text_chunks, system_prompt=system_prompt)
        stream = self._client.chat.completions.create(
            model=model or self._settings.chat_model,
            messages=messages,
            max_tokens=max_tokens or self._settings.chat_max_tokens,
            temperature=temperature if temperature is not None else self._settings.chat_temperature,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def generate(
        self,
        query: str,
        chunks: list[RerankedChunk],
        *,
        model: str | None = None,
        vision_model: str | None = None,
        fusion_model: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        system_prompt: str | None = None,
    ) -> GenerationResult:
        text_chunks, image_chunks = split_chunks(chunks)
        latency: dict[str, int] = {}

        text_answer: str | None = None
        vision_answer: str | None = None

        if text_chunks:
            t0 = time.perf_counter()
            text_answer = self._generate_text(
                query,
                text_chunks,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system_prompt=system_prompt,
            )
            latency["generate_text"] = int((time.perf_counter() - t0) * 1000)

        if image_chunks:
            t0 = time.perf_counter()
            vision_answer = self._generate_vision(
                query,
                image_chunks,
                model=vision_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            latency["generate_vision"] = int((time.perf_counter() - t0) * 1000)

        if text_answer and vision_answer:
            t0 = time.perf_counter()
            answer = self._fuse_answers(
                query,
                text_answer=text_answer,
                vision_answer=vision_answer,
                model=fusion_model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            latency["generate_fusion"] = int((time.perf_counter() - t0) * 1000)
        elif text_answer:
            answer = text_answer
        elif vision_answer:
            answer = vision_answer
        else:
            answer = NO_SOURCES_ANSWER

        latency["generate_total"] = sum(latency.values())

        return GenerationResult(
            answer=answer,
            text_answer=text_answer,
            vision_answer=vision_answer,
            text_chunk_count=len(text_chunks),
            image_chunk_count=len(image_chunks),
            latency_ms=latency,
        )
