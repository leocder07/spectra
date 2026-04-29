"""Resolve per-agent model + effort configs from CLI overrides.

Pure use-case helper: takes a dict of CLI overrides and returns a fully
resolved ``dict[AgentRole, AgentRunConfig]``. Layer 2 — imports only
from ``entities/``.

Override precedence (lowest to highest):
    1. ``_DEFAULT_AGENT_CONFIGS`` (the today-hardcoded baseline)
    2. ``global_model`` / ``global_effort`` (specialists only)
    3. ``models[role]`` / ``efforts[role]`` (per-role override; wins)

The CLI controller is responsible for merging JSON ``--model-overrides``
flags into ``models``/``efforts`` BEFORE calling this function — JSON
already wins over per-flag at that seam.
"""

from __future__ import annotations

from spectra.entities.enums import AgentRole
from spectra.entities.models import _DEFAULT_AGENT_CONFIGS, AgentRunConfig

_SPECIALIST_ROLES: frozenset[AgentRole] = frozenset(
    {
        "architecture",
        "security",
        "quality",
        "documentation",
        "dependency",
        "performance",
    }
)

# Sonnet/Haiku top out at "high" — auto-downgrade when the user changed
# only the model but kept the default Opus-tier "xhigh" effort.
_OPUS_TIER_MODELS: frozenset[str] = frozenset({"claude-opus-4-7", "claude-opus-4-6"})
_OPUS_ONLY_EFFORTS: frozenset[str] = frozenset({"xhigh", "max"})
_NON_OPUS_FALLBACK_EFFORT = "high"


def resolve_agent_configs(
    overrides: dict[str, object],
) -> dict[AgentRole, AgentRunConfig]:
    """Merge defaults with CLI overrides into a fully resolved config map.

    Args:
        overrides: Dict with optional keys: ``global_model``, ``global_effort``,
            ``models`` (dict[role, model]), ``efforts`` (dict[role, effort]).

    Returns:
        Mapping of every ``AgentRole`` to its resolved ``AgentRunConfig``.

    Raises:
        ValueError: If any role key in ``models``/``efforts`` is unknown,
            or if a per-role config fails ``AgentRunConfig`` validation
            (e.g. ``max`` effort on a Haiku model).
    """
    per_model = _coerce_role_dict(overrides.get("models"))
    per_effort = _coerce_role_dict(overrides.get("efforts"))
    _reject_unknown_roles(per_model, per_effort)

    global_model = _coerce_optional_str(overrides.get("global_model"))
    global_effort = _coerce_optional_str(overrides.get("global_effort"))

    return {
        role: _resolve_one(role, per_model, per_effort, global_model, global_effort) for role in _DEFAULT_AGENT_CONFIGS
    }


def _resolve_one(
    role: AgentRole,
    per_model: dict[str, str],
    per_effort: dict[str, str],
    global_model: str | None,
    global_effort: str | None,
) -> AgentRunConfig:
    """Compose the final AgentRunConfig for a single role.

    Auto-downgrade rule: when the model changed but effort did not, and
    the inherited default effort is Opus-only, fall back to ``high``.
    Explicit user effort overrides are never silently rewritten — they
    fail fast via Pydantic validation instead.
    """
    default = _DEFAULT_AGENT_CONFIGS[role]
    model_override = per_model.get(role) or _global_for_role(role, global_model)
    effort_override = per_effort.get(role) or _global_for_role(role, global_effort)
    model = model_override or default.model
    effort = _coerce_effort(model, effort_override, default.effort, explicit=effort_override is not None)
    return AgentRunConfig(
        model=model,  # type: ignore[arg-type]  # validated by Pydantic
        effort=effort,  # type: ignore[arg-type]  # validated by Pydantic
        task_budget_tokens=default.task_budget_tokens,
    )


def _coerce_effort(
    model: str,
    effort_override: str | None,
    default_effort: str,
    *,
    explicit: bool,
) -> str:
    """Pick effort, downgrading inherited Opus-only defaults for non-Opus models."""
    if explicit and effort_override is not None:
        return effort_override
    if model in _OPUS_TIER_MODELS:
        return default_effort
    if default_effort in _OPUS_ONLY_EFFORTS:
        return _NON_OPUS_FALLBACK_EFFORT
    return default_effort


def _global_for_role(role: AgentRole, value: str | None) -> str | None:
    """Return the global override only when ``role`` is a specialist."""
    if value is None or role not in _SPECIALIST_ROLES:
        return None
    return value


def _reject_unknown_roles(*role_dicts: dict[str, str]) -> None:
    """Raise ValueError if any role key is not a known AgentRole."""
    valid = set(_DEFAULT_AGENT_CONFIGS)
    for d in role_dicts:
        unknown = set(d) - valid
        if unknown:
            msg = f"Unknown agent role(s) in override: {sorted(unknown)}"
            raise ValueError(msg)


def _coerce_role_dict(value: object) -> dict[str, str]:
    """Return a string-valued dict view of ``value`` (or empty)."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        msg = "Per-role overrides must be a dict[str, str]"
        raise ValueError(msg)
    return {str(k): str(v) for k, v in value.items()}


def _coerce_optional_str(value: object) -> str | None:
    """Return ``value`` as a non-empty string, else None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
