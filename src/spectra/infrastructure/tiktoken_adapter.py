"""Token counting adapter — implements TokenPort using tiktoken.

Uses the ``cl100k_base`` encoding (Claude/GPT-4 family) by default
and caches token counts by text hash to avoid redundant encoding.

Performance:
    - Hash-based cache: Token counts are stored in a ``dict[int, int]``
      keyed by ``hash(text)``. Repeat lookups are O(1) dict access,
      skipping the expensive ``tiktoken.encode()`` call entirely.
    - The encoder itself is shared across every adapter instance via
      ``get_encoder`` (an ``lru_cache``-backed factory). Constructing
      ``TiktokenAdapter`` is therefore a hash-table lookup — no disk I/O
      after the first call per encoding name.
    - Cache hits are common: the file tree string is counted once but
      referenced by all 6 specialist agents, the MetaPrompter, and the
      budget checker — 8+ cache hits per analysis run.
"""

from __future__ import annotations

from functools import lru_cache

import tiktoken


@lru_cache(maxsize=8)
def get_encoder(encoding_name: str = "cl100k_base") -> tiktoken.Encoding:
    """Return a process-wide cached tiktoken encoder for ``encoding_name``.

    ``tiktoken.get_encoding`` performs disk I/O (and a network fetch on
    a cold cache) for every call, so re-instantiating ``TiktokenAdapter``
    per analysis was reloading the encoder unnecessarily. Caching here
    means the second and later calls are pure dict lookups.

    The cache is keyed by encoding name; ``maxsize=8`` is generous —
    Spectra only ever uses ``cl100k_base`` today, but leaving headroom
    avoids surprise evictions if a future agent opts into a different
    tokenizer.
    """
    return tiktoken.get_encoding(encoding_name)


class TiktokenAdapter:
    """Token counter implementing the TokenPort protocol.

    Caches token counts by text hash to avoid redundant encoding
    when the same content is counted multiple times (e.g. the file
    tree sent to all 6 specialist agents).

    The cache is a simple ``dict[int, int]`` (text hash → token count).
    This avoids the expensive ``tiktoken.encode()`` call on repeated
    inputs — cached lookups are O(1) dict access vs. O(n) encoding.
    """

    def __init__(self, encoding_name: str = "cl100k_base") -> None:
        """Initialize the token counter.

        Args:
            encoding_name: tiktoken encoding name (default ``cl100k_base``).
        """
        # Encoder reused across instances via the module-level lru_cache —
        # avoids reloading the tiktoken encoding on every adapter creation.
        self._encoder = get_encoder(encoding_name)
        # Hash-based cache: O(1) repeat lookups for identical text
        self._cache: dict[int, int] = {}

    def count(self, text: str) -> int:
        """Return the token count for the given text.

        Results are cached by ``hash(text)`` for repeat queries.

        Args:
            text: Input text to tokenize.

        Returns:
            Number of tokens.
        """
        # Cached by text hash — O(1) repeat lookups
        key = hash(text)
        if key not in self._cache:
            # Cache miss: encode once and store
            self._cache[key] = len(self._encoder.encode(text))
        # Cache hit path: direct dict lookup, skips encode()
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
