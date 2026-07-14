'''vision client for image generation using groq-vision model'''

from __future__ import annotations

import base64
import logging
from typing import Any, Dict

from openai import OpenAI

logger = logging.getLogger(__name__)


class VisionClient:
    """Simple wrapper around OpenAI client for the groq-vision model.

    The client expects an image as raw bytes, encodes it as a data URI, and sends a
    chat completion request to the model. The response content is returned as a
    string.
    """

    def __init__(self, *, base_url: str, api_key: str, model: str = "groq-vision") -> None:
        # Litellm proxy or direct OpenAI endpoint
        self._client = OpenAI(base_url=base_url.rstrip("/"), api_key=api_key)
        self._model = model

    @staticmethod
    def _bytes_to_data_url(image_bytes: bytes) -> str:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def generate(self, image_bytes: bytes, *, user_prompt: str | None = None) -> str:
        """Generate a textual response for an image.

        Args:
            image_bytes: Raw PNG/JPEG bytes.
            user_prompt: Optional additional prompt to guide the model.

        Returns:
            The model's reply as a string.
        """
        data_url = self._bytes_to_data_url(image_bytes)
        messages: list[Dict[str, Any]] = [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": data_url}}]}
        ]
        if user_prompt:
            messages[0]["content"].insert(0, {"type": "text", "text": user_prompt})
        response = self._client.chat.completions.create(model=self._model, messages=messages)
        text = response.choices[0].message.content or ""
        logger.info("vision_response_created model=%s length=%d", self._model, len(text))
        return text
