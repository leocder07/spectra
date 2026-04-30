# Contributing to Spectra

Thanks for your interest in contributing to Spectra.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/leocder07/spectra.git
cd spectra

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Verify installation
spectra --version
pytest tests/ -v
```

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key (required for `spectra analyze`) |

## Running Tests

```bash
# Full test suite
pytest tests/ -v

# Unit tests only (fast, no I/O)
pytest tests/entities/ -v

# Integration tests
pytest tests/integration/ -v

# With coverage
pytest tests/ --cov=spectra --cov-report=html
open htmlcov/index.html
```

## Linting and Type Checking

```bash
# Lint
ruff check src/ tests/

# Auto-format
ruff format src/ tests/

# Type check
mypy src/
```

## Regenerating the Lock File

`requirements.lock` is the hash-pinned snapshot of the full transitive
dependency tree (runtime + dev). Always regenerate it with `uv` and the
`--generate-hashes` flag so each pin carries a SHA-256 (supply-chain
integrity — `pip install --require-hashes` will refuse to install a
wheel whose hash does not match).

```bash
uv pip compile pyproject.toml --extra dev --generate-hashes -o requirements.lock
```

When you bump a dependency in `pyproject.toml`, regenerate the lock in
the same commit and verify it still carries hashes:

```bash
grep -c "sha256:" requirements.lock   # expect: in the thousands, never zero
```

## Architecture Overview

Spectra follows **Clean Architecture** with 4 strict layers:

```
Layer 1: entities/        -> Imports NOTHING from spectra
Layer 2: use_cases/       -> Imports ONLY from entities/
Layer 3: adapters/        -> Imports from entities/ + use_cases/
Layer 4: infrastructure/  -> Imports from all inner layers
```

**The Dependency Rule:** Source code dependencies ONLY point inward. A layer may never import from a layer outside (further from center) than itself. Violations are rejected in code review.

### Pipeline Stages

```
INGEST -> PREFLIGHT (1.5) -> PLAN -> ANALYZE -> MERGE -> CRITIQUE -> REPORT
```

1. **INGEST** — Clone repo (HTTPS) or validate local path (`GitPort.prepare_workspace`)
2. **PREFLIGHT (Stage 1.5)** — `WorkspaceFilterPort` honors `.gitignore` + `.spectraignore`; `SecretScannerPort` aborts on secret detection (SPEC-011, `--allow-secrets` to override)
3. **PLAN** — MetaPrompter (Opus 4.7, effort=medium) builds focus-area plan from file tree only (≤5K tokens, never source code)
4. **ANALYZE** — 6 specialists run in parallel via `asyncio.gather` (all Opus 4.7, effort=xhigh). Per-`focus_area` cache splits each batch into cached + fresh
5. **MERGE** — Deduplicate findings (cached UNION fresh), validate file paths, remove hallucinations
6. **CRITIQUE** — CritiqueAgent (Opus 4.7, adaptive thinking + 80K task_budget) validates all findings + adversarial input check
7. **REPORT** — Render HTML/JSON/SARIF via Jinja2; emit Ed25519-signed receipt; honor `--classification confidential|public` (v0.6.0)

### Key Patterns

- **Dependency Injection** — The composition root (`infrastructure/main.py`) wires all dependencies
- **Decorator Chain** — `LoggingDecorator -> RetryDecorator -> AnthropicAdapter` wraps every LLM call
- **Template Method** — `BaseAgent` defines the agent lifecycle; subclasses override specific steps
- **Protocol Interfaces** — Ports in `use_cases/interfaces.py` define boundaries between layers
- **Frozen Models** — All Pydantic models use `frozen=True` for immutability

## Code Style Guidelines

### General Rules

- Functions: max 20 lines, max 3 parameters, cyclomatic complexity max 10
- No `Any` type. No `# type: ignore`
- No `print()` in `src/` — use `ProgressObserver` port
- Every entity model: `frozen=True`
- `Literal` types for enums (not `enum.Enum`)
- Export everything from `__init__.py` with `__all__`

### Architecture Layer Rules with Examples

The dependency rule is enforced by code review. Here are examples of valid and invalid imports:

```python
# ✅ VALID: entities/ imports nothing from spectra
# src/spectra/entities/models.py
from pydantic import BaseModel  # Third-party OK
from spectra.entities.enums import Severity  # Same layer OK

# ✅ VALID: use_cases/ imports only from entities/
# src/spectra/use_cases/analyze_repository.py
from spectra.entities.models import Finding  # Inner layer OK

# ❌ INVALID: entities/ importing from use_cases/
# src/spectra/entities/models.py
from spectra.use_cases.interfaces import LLMGateway  # VIOLATION!

# ❌ INVALID: use_cases/ importing from infrastructure/
# src/spectra/use_cases/orchestrate_agents.py
from spectra.infrastructure.anthropic_adapter import AnthropicAdapter  # VIOLATION!
```

### Immutable Models

All domain models use `frozen=True`. When you need to modify a field, use `model_copy()`:

```python
# ✅ Correct: create a new instance
adjusted = finding.model_copy(
    update={"severity": "medium", "validated_by_critique": True}
)

# ❌ Wrong: direct mutation raises ValidationError
finding.severity = "medium"  # Raises error!
```

Use `tuple[T, ...]` instead of `list[T]` for collection fields to prevent mutation.

### Docstrings

- Google-style docstrings on all public functions and classes
- Module-level docstrings on every `.py` file
- Include `Args:`, `Returns:`, and `Raises:` sections where applicable

Example of a well-formatted docstring:

```python
def score_to_grade(score: float) -> Grade:
    """Map a numeric score (0-100) to a letter grade.

    Args:
        score: Numeric score between 0 and 100.

    Returns:
        Letter grade from ``A+`` (95-100) down to ``F`` (0-56).
    """
```

### Error Handling

All fallible operations use the `SpectraError` pattern with codes SPEC-001 through SPEC-014 (see CLAUDE.md for the full registry):

```python
from spectra.entities.errors import ERRORS, AgentError

# Raise a domain error with a registered code
raise AgentError(ERRORS["SPEC-006"])  # Agent timeout

# Error codes carry retry metadata
err = ERRORS["SPEC-003"]
if err.retryable:
    # RetryDecorator will back-off up to err.max_retries times
    pass
```

Agent outputs are validated with Pydantic models BEFORE merge. Every agent gets `asyncio.wait_for(timeout=120)`.

### Brand Voice (User-Facing Text)

- CLI messages: max 80 characters, no trailing period
- Progress: `▸ [Stage]: [Action]`
- Success: `✓ [Result]`
- Error: `✗ [What failed]: [Why]: [What to do]`
- **Forbidden words:** revolutionary, cutting-edge, game-changing, leverage, innovative, utilize, might be, could potentially, comprehensive solution, AI-powered

---

## Testing Guidelines

### Test Organization

Tests mirror the source structure:

```
tests/
├── conftest.py              # Shared fixtures
├── entities/                # Unit tests (no I/O, no mocks)
│   ├── test_enums.py
│   ├── test_errors.py
│   └── test_models.py
├── use_cases/               # Unit tests with protocol fakes
│   ├── test_analyze_repository.py
│   ├── test_orchestrate_agents.py
│   └── test_manage_token_budget.py
├── adapters/                # Tests with Rich Console fakes
│   ├── test_cli_controller.py
│   ├── test_progress_reporter.py
│   └── test_analysis_presenter.py
└── infrastructure/          # Integration tests
    ├── test_agents/
    ├── test_anthropic_adapter.py
    └── test_retry_decorator.py
```

### Writing Tests

For **entities/** (Layer 1), write pure unit tests with no mocks:

```python
def test_finding_deduplication():
    """Two findings at the same location + dimension are equal."""
    f1 = Finding(id="a", dimension="security", ...)
    f2 = Finding(id="b", dimension="security", ...)  # same location
    assert f1 == f2
    assert len({f1, f2}) == 1  # hashable dedup
```

For **use_cases/** (Layer 2), create protocol fakes:

```python
class FakeGateway:
    """Test double satisfying LLMGateway protocol."""
    async def analyze(self, system_prompt, user_prompt, model, max_tokens) -> str:
        return '{"findings": []}'

    async def analyze_with_thinking(self, system_prompt, user_prompt, model, max_tokens) -> str:
        return '{"findings": []}'
```

For **async code**, use `pytest-asyncio`:

```python
import pytest

@pytest.mark.asyncio
async def test_run_specialists_timeout():
    """Agents that exceed timeout produce exceptions."""
    results = await run_specialists(agents, prompts, timeout_seconds=0.001)
    assert isinstance(results[0], Exception)
```

### Coverage Requirements

- Target: 90%+ overall coverage
- All new code must include tests
- Run coverage report: `pytest tests/ --cov=spectra --cov-report=html`

---

## Pull Request Process

1. **Branch** — Create a feature branch from `main`
2. **Implement** — Follow the architecture rules and code style
3. **Test** — All tests must pass (`pytest tests/ -v`)
4. **Lint** — No ruff or mypy errors (`ruff check src/ tests/ && mypy src/`)
5. **Document** — Add docstrings to new public APIs
6. **PR** — Open a PR with a clear description of changes
7. **Review** — Address review feedback

### PR Checklist

- [ ] Tests pass (`pytest tests/ -v`)
- [ ] No lint errors (`ruff check src/ tests/`)
- [ ] Type check passes (`mypy src/`)
- [ ] Docstrings added for new public APIs
- [ ] Module-level docstrings on every new `.py` file
- [ ] Architecture layer rules respected (no outward imports)
- [ ] All Pydantic models use `frozen=True`
- [ ] No `Any` types or `# type: ignore`
- [ ] No `print()` in `src/` — use `ProgressObserver`
- [ ] No forbidden brand words in user-facing text
- [ ] Coverage does not decrease

---

## File Ownership

| Area | Files | Key Patterns |
|------|-------|--------------|
| Domain Model | `src/spectra/entities/*` | Frozen Pydantic models, Literal enums, error taxonomy |
| Use Cases | `src/spectra/use_cases/*` | Protocol interfaces, pipeline orchestration, token budgets |
| CLI & Presentation | `src/spectra/adapters/*`, `templates/*` | Typer CLI, Rich terminal, brand constants |
| Infrastructure | `src/spectra/infrastructure/*` | Anthropic API, GitPython, Jinja2, decorator chain, agents |
| Tests | `tests/*` | pytest, pytest-asyncio, protocol fakes |

---

## Architecture Decision Records

Design decisions are documented in `docs/architecture/adr/` (10 records as of v0.6.0); strategy ADRs 011-020 live in `docs/strategy/`. Highlights:

| ADR | Decision | Status |
|-----|----------|--------|
| [ADR-001](docs/architecture/adr/ADR-001-clean-architecture.md) | Clean Architecture with 4 layers | Accepted |
| [ADR-002](docs/architecture/adr/ADR-002-parallel-agent-pipeline.md) | 8-agent parallel analysis pipeline | Accepted |
| [ADR-003](docs/architecture/adr/ADR-003-extended-thinking-critique-only.md) | Extended thinking for CritiqueAgent only | Superseded by ADR-008 |
| [ADR-004](docs/architecture/adr/ADR-004-frozen-pydantic-models.md) | Pydantic frozen models for domain entities | Accepted |
| [ADR-005](docs/architecture/adr/ADR-005-opus-4-7-migration.md) | Migrate all 8 agents to Opus 4.7 | Accepted |
| [ADR-006](docs/architecture/adr/ADR-006-cache-port-incremental-analysis.md) | CachePort + 4-phase incremental analysis | Accepted |
| [ADR-008](docs/architecture/adr/ADR-008-adaptive-thinking-supersedes-extended.md) | Adaptive thinking supersedes extended thinking | Accepted |
| [ADR-009](docs/architecture/adr/ADR-009-batch-granularity-per-focus-area.md) | Phase 3 per-`focus_area` batch caching | Accepted |
| ADR-011 — ADR-020 (strategy) | Q1 + Q2 capabilities (prompt-injection, cache HMAC, audit log, encrypted cache, signed receipts, policy + waivers, dual-mode classification) | Shipped in v0.5.0 / v0.6.0 |

When making architectural decisions, add a new ADR following the same format: Status, Date, Context, Decision, Consequences (Positive/Negative/Mitigation).
