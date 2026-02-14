"""Token counting adapter — implements TokenPort using tiktoken."""

from __future__ import annotations

import tiktoken


class TiktokenAdapter:
    """Token counter implementing the TokenPort protocol."""

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoder = tiktoken.get_encoding(encoding_name)

    def count(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def fits_budget(self, text: str, budget: int) -> bool:
        return self.count(text) <= budget
