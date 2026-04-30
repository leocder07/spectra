"""Infrastructure layer — Layer 4 of Clean Architecture (outermost, imports from all layers).

This is the outermost layer of Spectra's Clean Architecture. It contains
concrete implementations of all port interfaces, the decorator chain, the
agent system, and the composition root that wires everything together.

Key modules:

- **main.py** — Composition root and DI wiring. Builds the decorator chain
  (``LoggingDecorator`` → ``RetryDecorator`` → ``AnthropicAdapter``), creates
  agents via the factory, and exposes the ``cli()`` entry point.
- **anthropic_adapter.py** — Implements ``LLMGateway`` using the Anthropic
  SDK with streaming and connection pooling (httpx, 10 keep-alive connections).
- **retry_decorator.py** — Exponential backoff (1s, 2s, 4s) with jitter for
  transient ``SpectraRetryError`` failures. Max 3 retries.
- **logging_decorator.py** — Records model, tokens, and duration per call.
  Redacts API keys (``sk-ant-*``) before logging.
- **git_adapter.py** — Implements ``GitPort`` with 8-layer security hardening:
  HTTPS-only, SSRF prevention, path traversal blocking, symlink rejection,
  shallow clone with hooks disabled, file/repo size limits, and read timeouts.
- **tiktoken_adapter.py** — Token counting via ``cl100k_base`` with hash-based
  caching for repeat queries.
- **report_adapter.py** — Jinja2 HTML report rendering with VC due diligence
  frameworks (OWASP, SOC 2, bus factor, investment readiness).
- **agents/** — Agent subsystem: ``BaseAgent`` (Template Method ABC),
  ``AgentFactory`` (creates all 8 agents), ``MetaPrompter`` (Opus 4.7,
  medium effort), ``SpecialistAgent`` (6 dimensions, Opus 4.7 + xhigh
  effort), ``CritiqueAgent`` (Opus 4.7 + adaptive thinking + task budget).

**Dependency rule**: This layer may import from all inner layers.
No inner layer imports from infrastructure.
"""

from spectra.infrastructure.anthropic_adapter import AnthropicAdapter
from spectra.infrastructure.anthropic_batch_adapter import AnthropicBatchAdapter
from spectra.infrastructure.git_adapter import GitAdapter, GitError
from spectra.infrastructure.logging_decorator import LoggingDecorator
from spectra.infrastructure.main import ReportError, cli
from spectra.infrastructure.report_adapter import ReportAdapter
from spectra.infrastructure.retry_decorator import RetryDecorator, SpectraRetryError
from spectra.infrastructure.tiktoken_adapter import TiktokenAdapter

__all__ = [
    # LLM adapters
    "AnthropicAdapter",
    "AnthropicBatchAdapter",
    # infrastructure adapters
    "GitAdapter",
    # errors
    "GitError",
    # decorator chain
    "LoggingDecorator",
    "ReportAdapter",
    "ReportError",
    "RetryDecorator",
    "SpectraRetryError",
    "TiktokenAdapter",
    # entry point
    "cli",
]
