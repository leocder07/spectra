"""Infrastructure layer — adapters, decorators, and agents."""

from spectra.infrastructure.anthropic_adapter import AnthropicAdapter
from spectra.infrastructure.git_adapter import GitAdapter, GitError
from spectra.infrastructure.logging_decorator import LoggingDecorator
from spectra.infrastructure.main import ReportError, cli
from spectra.infrastructure.report_adapter import ReportAdapter
from spectra.infrastructure.retry_decorator import RetryDecorator, SpectraRetryError
from spectra.infrastructure.tiktoken_adapter import TiktokenAdapter

__all__ = [
    # LLM adapter
    "AnthropicAdapter",
    # decorator chain
    "LoggingDecorator",
    "RetryDecorator",
    # infrastructure adapters
    "GitAdapter",
    "ReportAdapter",
    "TiktokenAdapter",
    # errors
    "GitError",
    "ReportError",
    "SpectraRetryError",
    # entry point
    "cli",
]
