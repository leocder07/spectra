# Contributing to Spectra

Thanks for your interest in contributing to Spectra.

## Development Setup

```bash
# Clone the repository
git clone https://github.com/your-org/spectra.git
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
INGEST -> PLAN -> ANALYZE -> MERGE -> CRITIQUE -> REPORT
```

1. **INGEST** — Clone repo, extract file tree (GitPython)
2. **PLAN** — MetaPrompter (Sonnet 4.5) creates per-agent focus areas from file tree only
3. **ANALYZE** — 6 specialists run in parallel via `asyncio.gather` (all Opus 4.6)
4. **MERGE** — Deduplicate findings, validate file paths, remove hallucinations
5. **CRITIQUE** — CritiqueAgent (Opus 4.6, extended thinking) validates all findings
6. **REPORT** — Render HTML via Jinja2 with executive summary and VC due diligence

### Key Patterns

- **Dependency Injection** — The composition root (`infrastructure/main.py`) wires all dependencies
- **Decorator Chain** — `LoggingDecorator -> RetryDecorator -> AnthropicAdapter` wraps every LLM call
- **Template Method** — `BaseAgent` defines the agent lifecycle; subclasses override specific steps
- **Protocol Interfaces** — Ports in `use_cases/interfaces.py` define boundaries between layers
- **Frozen Models** — All Pydantic models use `frozen=True` for immutability

## Code Style Guidelines

### General

- Functions: max 20 lines, max 3 parameters, cyclomatic complexity max 10
- No `Any` type. No `# type: ignore`
- No `print()` in `src/` — use `ProgressObserver` port
- Every entity model: `frozen=True`
- `Literal` types for enums (not `enum.Enum`)
- Export everything from `__init__.py` with `__all__`

### Docstrings

- Google-style docstrings on all public functions and classes
- Module-level docstrings on every `.py` file
- Include `Args:`, `Returns:`, and `Raises:` sections where applicable

### Error Handling

- Fallible operations use the `SpectraError` pattern with error codes (SPEC-001 to SPEC-009)
- Agent outputs validated with Pydantic models BEFORE merge
- `asyncio.wait_for(timeout=120)` per agent

### Brand Voice (User-Facing Text)

- CLI messages: max 80 characters, no trailing period
- Progress: `> [Stage]: [Action]`
- Success: `✓ [Result]`
- Error: `✗ [What failed]: [Why]: [What to do]`
- Forbidden words: revolutionary, cutting-edge, game-changing, leverage, innovative, utilize

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
- [ ] Architecture layer rules respected
- [ ] No forbidden brand words in user-facing text

## File Ownership

| Area | Files |
|------|-------|
| Domain Model | `src/spectra/entities/*` |
| Use Cases | `src/spectra/use_cases/*` |
| CLI & Presentation | `src/spectra/adapters/*`, `templates/*` |
| Infrastructure | `src/spectra/infrastructure/*` |
| Tests | `tests/*` |
