"""Token counting adapter — implements TokenPort using tiktoken."""

from __future__ import annotations

import tiktoken


class TiktokenAdapter:
    """Token counter implementing the TokenPort protocol.

    Caches token counts by text hash to avoid redundant encoding
    when the same content is counted multiple times (e.g. file tree
    sent to all 6 specialist agents).
    """

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        self._encoder = tiktoken.get_encoding(encoding_name)
        self._cache: dict[int, int] = {}

    def count(self, text: str) -> int:
        key = hash(text)
        if key not in self._cache:
            self._cache[key] = len(self._encoder.encode(text))
        return self._cache[key]

    def fits_budget(self, text: str, budget: int) -> bool:
        return self.count(text) <= budget

    def clear_cache(self) -> None:
        """Clear the token count cache."""
        self._cache.clear()
