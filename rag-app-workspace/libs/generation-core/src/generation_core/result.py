from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GenerationResult:
    answer: str
    text_answer: str | None = None
    vision_answer: str | None = None
    text_chunk_count: int = 0
    image_chunk_count: int = 0
    latency_ms: dict[str, int] = field(default_factory=dict)
