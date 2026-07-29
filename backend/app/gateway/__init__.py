"""AI Gateway package — unified LLM exit for the platform."""
from __future__ import annotations

from .service import chat_completion, test_model_connection

__all__ = ["chat_completion", "test_model_connection"]
