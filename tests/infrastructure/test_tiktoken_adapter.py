"""Tests for TiktokenAdapter — token counting via tiktoken."""

from __future__ import annotations

from spectra.infrastructure.tiktoken_adapter import TiktokenAdapter


class TestCountTokens:
    def test_empty_string_returns_zero(self):
        adapter = TiktokenAdapter()
        assert adapter.count("") == 0

    def test_hello_world_positive(self):
        adapter = TiktokenAdapter()
        count = adapter.count("Hello, world!")
        assert count > 0

    def test_known_string_approximate(self):
        adapter = TiktokenAdapter()
        # "The quick brown fox" — expect roughly 4-6 tokens
        count = adapter.count("The quick brown fox jumps over the lazy dog")
        assert 5 <= count <= 15

    def test_long_text_more_tokens(self):
        adapter = TiktokenAdapter()
        short = adapter.count("hi")
        long = adapter.count("hi " * 100)
        assert long > short

    def test_single_word(self):
        adapter = TiktokenAdapter()
        count = adapter.count("hello")
        assert count == 1


class TestFitsBudget:
    def test_within_budget(self):
        adapter = TiktokenAdapter()
        assert adapter.fits_budget("hello", 100) is True

    def test_exceeds_budget(self):
        adapter = TiktokenAdapter()
        text = "word " * 1000
        assert adapter.fits_budget(text, 5) is False

    def test_exact_budget(self):
        adapter = TiktokenAdapter()
        text = "hello"
        count = adapter.count(text)
        assert adapter.fits_budget(text, count) is True

    def test_empty_string_fits_any_budget(self):
        adapter = TiktokenAdapter()
        assert adapter.fits_budget("", 0) is True


class TestEncodingInit:
    def test_default_encoding(self):
        adapter = TiktokenAdapter()
        assert adapter._encoder is not None

    def test_custom_encoding(self):
        adapter = TiktokenAdapter(encoding_name="cl100k_base")
        assert adapter.count("test") > 0
