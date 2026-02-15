"""Token counting adapter — implements TokenPort using tiktoken.

Uses the ``cl100k_base`` encoding (Claude/GPT-4 family) by default
and caches token counts by text hash to avoid redundant encoding.
"""

from __future__ import annotations

import tiktoken


class TiktokenAdapter:
    """Token counter implementing the TokenPort protocol.

    Caches token counts by text hash to avoid redundant encoding
    when the same content is counted multiple times (e.g. the file
    tree sent to all 6 specialist agents).
    """

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        """Initialize the token counter.

        Args:
            encoding_name: tiktoken encoding name (default ``cl100k_base``).
        """
        self._encoder = tiktoken.get_encoding(encoding_name)
        self._cache: dict[int, int] = {}

    def count(self, text: str) -> int:
        """Return the token count for the given text.

        Results are cached by ``hash(text)`` for repeat queries.

        Args:
            text: Input text to tokenize.

        Returns:
            Number of tokens.
        """
        key = hash(text)
        if key not in self._cache:
            self._cache[key] = len(self._encoder.encode(text))
        return self._cache[key]

    def fits_budget(self, text: str, budget: int) -> bool:
        """Return True if the text fits within the token budget.

        Args:
            text: Input text to check.
            budget: Maximum allowed tokens.

        Returns:
            True if token count is within budget.
        """
        return self.count(text) <= budget

    def clear_cache(self) -> None:
        """Clear the token count cache."""
        self._cache.clear()
