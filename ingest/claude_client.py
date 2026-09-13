"""Một client Anthropic dùng chung cho locate.py và extract.py."""
from __future__ import annotations

import anthropic

from common.config import ANTHROPIC_API_KEY

_client: anthropic.Anthropic | None = None


class NoApiKey(Exception):
    pass


def client() -> anthropic.Anthropic:
    global _client
    if not ANTHROPIC_API_KEY:
        raise NoApiKey("Chưa có ANTHROPIC_API_KEY trong .env — bước tìm trang và đọc ảnh cần khoá này")
    if _client is None:
        # Đọc ảnh 3–5 trang có thể mất vài phút; max_retries 2 cho 429/5xx.
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=600, max_retries=2)
    return _client
