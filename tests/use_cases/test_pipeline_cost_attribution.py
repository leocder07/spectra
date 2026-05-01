"""Cost-attribution span tests (#33, ADR-023 §4).

Verifies the contract a CFO query depends on: every cost-bearing span
carries (spectra.team, agent.role, cost.usd, tokens.total). The root
span aggregates the same set across the run so a single
``last_over_time(spectra_root_cost_usd[7d])`` query yields per-team,
per-repo Anthropic spend.
"""

from __future__ import annotations

import pytest

from spectra.entities.models import (
    AnalysisRequest,
    Codebase,
)
from spectra.infrastructure.observability import InMemoryTracerAdapter
from spectra.use_cases.analyze_repository import (
    PipelineContext,
    analyze_repository,
)


@pytest.fixture
def codebase() -> Codebase:
    return Codebase(
        repo_url="https://github.com/acme/api",
        repo_name="api",
        local_path="/workspace/api",
        file_tree=("src/main.py", "README.md"),
    )


@pytest.fixture
def request_obj() -> AnalysisRequest:
    return AnalysisRequest(repo_url="https://github.com/acme/api")


@pytest.fixture
def six_specialists(make_agent):  # type: ignore[no-untyped-def]
    return [
        make_agent("architecture"),
        make_agent("security"),
        make_agent("quality"),
        make_agent("documentation"),
        make_agent("dependency"),
        make_agent("performance"),
    ]


@pytest.fixture
def meta_prompter(make_agent):  # type: ignore[no-untyped-def]
    return make_agent("meta_prompter")


@pytest.fixture
def critique_agent(make_agent):  # type: ignore[no-untyped-def]
    return make_agent("critique")


def _spans_by_name(adapter: InMemoryTracerAdapter, name_prefix: str) -> list[object]:
    return [s for s in adapter.exporter.get_finished_spans() if s.name.startswith(name_prefix)]


def _attrs(span: object) -> dict[str, object]:
    return dict(span.attributes or {})  # type: ignore[attr-defined]


@pytest.mark.asyncio
class TestCostAttributionAttributes:
    async def test_every_agent_span_has_team_role_and_cost(
        self, request_obj, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=request_obj,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
            team="payments-platform",
        )
        await analyze_repository(ctx)
        agent_spans = _spans_by_name(tracer, "spectra.agent.")
        assert len(agent_spans) >= 6
        for span in agent_spans:
            attrs = _attrs(span)
            assert attrs["spectra.team"] == "payments-platform"
            assert "agent.role" in attrs
            assert "cost.usd" in attrs
            assert "tokens.total" in attrs

    async def test_default_team_is_default(
        self, request_obj, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=request_obj,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
        )
        await analyze_repository(ctx)
        agent = _spans_by_name(tracer, "spectra.agent.")[0]
        assert _attrs(agent)["spectra.team"] == "default"

    async def test_root_span_aggregates_total_cost(
        self, request_obj, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=request_obj,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
            team="ml-platform",
        )
        await analyze_repository(ctx)
        root = _spans_by_name(tracer, "spectra.analyze_repository")[0]
        attrs = _attrs(root)
        assert attrs["spectra.team"] == "ml-platform"
        assert "cost.usd" in attrs
        assert "spectra.tokens" in attrs
        assert "spectra.findings" in attrs
        assert "spectra.score" in attrs
        # Cost should be non-negative (mock agents report tokens_used=500 each).
        assert float(attrs["cost.usd"]) >= 0.0  # type: ignore[arg-type]

    async def test_stage_spans_carry_team_tag(
        self, request_obj, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=request_obj,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
            team="data-eng",
        )
        await analyze_repository(ctx)
        for stage in ("plan", "analyze", "critique"):
            spans = _spans_by_name(tracer, f"spectra.stage.{stage}")
            assert spans, f"missing stage span: {stage}"
            assert _attrs(spans[0])["spectra.team"] == "data-eng"

    async def test_per_agent_outcome_attribute_distinguishes_success_from_failure(
        self, request_obj, codebase, meta_prompter, six_specialists, critique_agent, make_agent
    ) -> None:
        # Replace one specialist with a failing agent.
        six_specialists[1] = make_agent("security", error=RuntimeError("agent down"))
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=request_obj,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
        )
        await analyze_repository(ctx)
        sec = _spans_by_name(tracer, "spectra.agent.security")[0]
        attrs = _attrs(sec)
        assert attrs["agent.outcome"] == "failure"
        # A successful agent stamps "success".
        arch = _spans_by_name(tracer, "spectra.agent.architecture")[0]
        assert _attrs(arch)["agent.outcome"] == "success"
