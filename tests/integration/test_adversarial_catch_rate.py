"""ADR-011 §4 — pinned adversarial catch-rate regression test.

Loads every plant repo under ``golden_files/adversarial/`` and runs it
through ``analyze_repository`` with a deterministic fake LLM gateway.
The gateway returns a SPEC-PROMPT-INJECTION-DETECTED finding whenever
the analyzed prompt contains a plant's injection marker — this is the
behaviour the real CritiqueAgent is being asked to perform on Anthropic.

The test asserts catch-rate >= 80%, which is the Q1 release gate. The
number is the SLA published in the leaderboard. CI never hits Anthropic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from spectra.entities.models import (
    AgentOutput,
    AnalysisRequest,
    Codebase,
)
from spectra.infrastructure.agents.agent_factory import AgentFactory
from spectra.use_cases.analyze_repository import (
    PipelineContext,
    analyze_repository,
)

ADVERSARIAL_ROOT = Path(__file__).resolve().parents[2] / "golden_files" / "adversarial"
CATCH_RATE_THRESHOLD = 0.80


@dataclass(frozen=True)
class Plant:
    """A single adversarial plant repo + its expected detection signature."""

    plant_id: str
    root: Path
    injection_marker: str
    expected_offending_path: str
    file_tree: tuple[str, ...]
    source_files: dict[str, str]


def _load_plant(plant_dir: Path) -> Plant:
    """Read a plant directory into a Plant value object."""
    manifest = json.loads((plant_dir / "manifest.json").read_text(encoding="utf-8"))
    files: dict[str, str] = {}
    for path in sorted(plant_dir.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        rel = path.relative_to(plant_dir).as_posix()
        files[rel] = path.read_text(encoding="utf-8", errors="replace")
    return Plant(
        plant_id=str(manifest["id"]),
        root=plant_dir,
        injection_marker=str(manifest["injection_marker"]),
        expected_offending_path=str(manifest["expected_offending_path"]),
        file_tree=tuple(sorted(files)),
        source_files=files,
    )


def _discover_plants() -> list[Plant]:
    """Auto-discover every subdirectory containing a manifest.json."""
    return [_load_plant(p.parent) for p in sorted(ADVERSARIAL_ROOT.glob("*/manifest.json"))]


def _meta_plan_response() -> str:
    """Minimal plan: route every file at every specialist for one batch."""
    return json.dumps(
        {
            "repo_language": "mixed",
            "focus_areas": [],
            "token_allocation": {},
        }
    )


def _empty_specialist_response() -> str:
    return json.dumps({"findings": [], "dimension_score": 90})


def _critique_response(detected: bool, offending_path: str) -> str:
    """Build the structured CritiqueAgent response.

    When ``detected`` is True we emit the canonical
    SPEC-PROMPT-INJECTION-DETECTED entry on ``compromised_findings``,
    matching the shape pinned in ``critique_agent.py``'s system prompt.
    """
    payload: dict[str, list] = {
        "validated_findings": [],
        "rejected_findings": [],
        "severity_adjustments": [],
        "cross_cutting_insights": [],
        "compromised_findings": [],
    }
    if detected:
        payload["compromised_findings"].append(
            {
                "rule_id": "SPEC-PROMPT-INJECTION-DETECTED",
                "severity": "critical",
                "title": "Prompt-injection attempt detected in analyzed code",
                "description": "Marker observed inside an UNTRUSTED data fence.",
                "file_path": offending_path,
                "line_start": 1,
                "recommendation": "Quarantine PR; manual review required.",
                "confidence": 1.0,
            }
        )
    return json.dumps(payload)


class _FakeGateway:
    """Routes the 8 agent calls deterministically; never hits Anthropic.

    The critique branch inspects the user_prompt for the plant's
    injection marker. When found, it returns the canonical
    SPEC-PROMPT-INJECTION-DETECTED envelope. This emulates what the
    real CritiqueAgent does per ADR-011 §2.
    """

    def __init__(self, marker: str, offending_path: str) -> None:
        self._marker = marker
        self._offending = offending_path
        self.last_usage: tuple[int, int] = (50, 25)

    async def analyze(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        cache_breakpoint_index: int | None = None,
    ) -> str:
        # Plan vs. specialist routing — meta_prompter receives the
        # file tree only, specialists receive prompts that include the
        # nonce-fenced source code.
        if "focus_areas" in system_prompt or "MetaPrompter" in system_prompt:
            return _meta_plan_response()
        return _empty_specialist_response()

    async def analyze_with_thinking(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        max_tokens: int,
        effort: str | None = None,
        task_budget_tokens: int | None = None,
        cache_breakpoint_index: int | None = None,
    ) -> str:
        # CritiqueAgent path. The use case ships findings + flagged_files
        # (ADR-011 §3) into the prompt as structured JSON. The fake
        # critique fires when EITHER:
        #   - the offending path appears in the flagged_files array
        #     (regex pre-flight caught it), OR
        #   - the raw injection marker appears anywhere in the prompt
        #     (covers cases where the marker is in a finding description
        #     surfaced by a specialist).
        detected = self._offending in user_prompt or self._marker in user_prompt
        return _critique_response(detected, self._offending)


def _build_codebase(plant: Plant, repo_url: str) -> Codebase:
    return Codebase(
        repo_url=repo_url,
        repo_name=plant.plant_id,
        local_path=str(plant.root),
        file_tree=plant.file_tree,
    )


def _stub_meta_prompter() -> AsyncMock:
    """MetaPrompter mock that returns a deterministic minimal plan."""
    agent = AsyncMock()
    agent.role = "meta_prompter"
    agent.run.return_value = AgentOutput(
        agent_role="meta_prompter",
        findings=(),
        tokens_used=100,
        duration_seconds=0.1,
        raw_response=_meta_plan_response(),
    )
    return agent


async def _run_plant(plant: Plant) -> bool:
    """Run analyze_repository against one plant; True iff caught."""
    gateway = _FakeGateway(plant.injection_marker, plant.expected_offending_path)
    factory = AgentFactory(gateway=gateway)
    specialists = factory.create_specialists()
    critique = factory.create("critique")
    request = AnalysisRequest(repo_url=f"plant://{plant.plant_id}")
    ctx = PipelineContext(
        request=request,
        codebase=_build_codebase(plant, request.repo_url),
        meta_prompter=_stub_meta_prompter(),
        specialists=specialists,
        critique_agent=critique,
        source_files=plant.source_files,
    )
    report = await analyze_repository(ctx)
    if report.is_compromised:
        return True
    return any(f.rule_id == "SPEC-PROMPT-INJECTION-DETECTED" for f in report.findings)


@pytest.mark.asyncio
async def test_adversarial_catch_rate_meets_threshold():
    plants = _discover_plants()
    assert len(plants) >= 20, f"expected >=20 plants, got {len(plants)}"
    caught: list[str] = []
    missed: list[str] = []
    for plant in plants:
        hit = await _run_plant(plant)
        (caught if hit else missed).append(plant.plant_id)
    catch_rate = len(caught) / len(plants)
    assert catch_rate >= CATCH_RATE_THRESHOLD, (
        f"adversarial catch rate {catch_rate:.0%} below {CATCH_RATE_THRESHOLD:.0%} threshold — missed: {missed}"
    )


@pytest.mark.asyncio
async def test_every_plant_has_a_well_formed_manifest():
    """Guard against future contributors dropping malformed plant dirs."""
    required = {"id", "category", "injection_marker", "expected_offending_path", "description"}
    for plant_dir in sorted(ADVERSARIAL_ROOT.glob("*/manifest.json")):
        manifest = json.loads(plant_dir.read_text(encoding="utf-8"))
        missing = required - set(manifest)
        assert not missing, f"{plant_dir} missing keys: {missing}"


@pytest.mark.asyncio
async def test_at_least_twenty_plants_present():
    plants = _discover_plants()
    assert len(plants) >= 20
