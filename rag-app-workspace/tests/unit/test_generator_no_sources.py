from unittest.mock import MagicMock, patch

from generation_core.generator import Generator
from generation_core.prompt_builder import NO_SOURCES_ANSWER


def test_generate_returns_no_sources_message_when_chunks_empty() -> None:
    settings = MagicMock()
    settings.litellm_base_url = "http://localhost:4000"
    settings.openai_api_key = "sk-test"
    settings.chat_model = "test-model"
    settings.vision_model = "vision-model"
    settings.chat_max_tokens = 256
    settings.chat_temperature = 0.2

    generator = Generator(settings)
    result = generator.generate("What is the refund policy?", [])

    assert result.answer == NO_SOURCES_ANSWER
    assert result.text_chunk_count == 0
    assert result.image_chunk_count == 0
