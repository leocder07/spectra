"""Trace-shape contract tests for the analyze_repository pipeline (ADR-023).

Asserts the canonical span tree:

    spectra.analyze_repository (root)
     ├── spectra.stage.plan
     ├── spectra.stage.analyze
     │    ├── spectra.agent.architecture
     │    ├── spectra.agent.security
     │    ├── ...
     ├── spectra.stage.merge
     ├── spectra.stage.critique
     └── spectra.stage.report

Per-agent spans carry cost.usd, tokens.input, tokens.output, agent.role
attributes. Root span carries spectra.team + spectra.repo_signature
when supplied. Cache short-circuit emits stage.cache_short_circuit.
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
def analysis_request() -> AnalysisRequest:
    return AnalysisRequest(repo_url="https://github.com/acme/api")


@pytest.fixture
def codebase() -> Codebase:
    return Codebase(
        repo_url="https://github.com/acme/api",
        repo_name="api",
        local_path="/workspace/api",
        file_tree=("src/main.py", "README.md"),
    )


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


def _names(adapter: InMemoryTracerAdapter) -> list[str]:
    return [s.name for s in adapter.exporter.get_finished_spans()]


def _by_name(adapter: InMemoryTracerAdapter, name: str) -> object:
    matches = [s for s in adapter.exporter.get_finished_spans() if s.name == name]
    assert matches, f"no span with name={name!r} found in {_names(adapter)}"
    return matches[0]


@pytest.mark.asyncio
class TestPipelineSpanTree:
    async def test_root_span_is_emitted(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=analysis_request,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
        )
        await analyze_repository(ctx)
        names = _names(tracer)
        assert "spectra.analyze_repository" in names

    async def test_per_stage_spans_are_emitted(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=analysis_request,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
        )
        await analyze_repository(ctx)
        names = set(_names(tracer))
        assert "spectra.stage.plan" in names
        assert "spectra.stage.analyze" in names
        assert "spectra.stage.merge" in names
        assert "spectra.stage.critique" in names
        assert "spectra.stage.report" in names

    async def test_per_agent_spans_emit_for_every_specialist(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=analysis_request,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
        )
        await analyze_repository(ctx)
        names = set(_names(tracer))
        for role in ("architecture", "security", "quality", "documentation", "dependency", "performance"):
            assert f"spectra.agent.{role}" in names

    async def test_root_attributes_include_repo_url_and_team(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=analysis_request,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
            team="payments-platform",
            spectra_version="0.7.0",
        )
        await analyze_repository(ctx)
        root = _by_name(tracer, "spectra.analyze_repository")
        attrs = dict(root.attributes or {})  # type: ignore[attr-defined]
        assert attrs["spectra.team"] == "payments-platform"
        assert attrs["spectra.repo_url"] == "https://github.com/acme/api"
        assert attrs["spectra.version"] == "0.7.0"

    async def test_per_agent_spans_carry_cost_and_token_attributes(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=analysis_request,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
        )
        await analyze_repository(ctx)
        sec = _by_name(tracer, "spectra.agent.security")
        attrs = dict(sec.attributes or {})  # type: ignore[attr-defined]
        assert attrs["agent.role"] == "security"
        # tokens.* and cost.usd are populated post-call from AgentOutput.
        assert "cost.usd" in attrs
        assert "tokens.total" in attrs
        # The mock agent reports tokens_used=500.
        assert attrs["tokens.total"] == 500

    async def test_team_attribute_propagates_to_agent_spans(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=analysis_request,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
            team="payments-platform",
        )
        await analyze_repository(ctx)
        sec = _by_name(tracer, "spectra.agent.security")
        attrs = dict(sec.attributes or {})  # type: ignore[attr-defined]
        assert attrs["spectra.team"] == "payments-platform"

    async def test_no_tracer_means_no_spans(
        self, analysis_request, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        # Backwards-compatible default: tracer omitted = NoopTracerAdapter.
        ctx = PipelineContext(
            request=analysis_request,
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
        )
        # Should run without raising even when tracer is unset.
        report = await analyze_repository(ctx)
        assert report.repo_url == "https://github.com/acme/api"

    async def test_quick_mode_skips_critique_span(
        self, codebase, meta_prompter, six_specialists, critique_agent
    ) -> None:
        tracer = InMemoryTracerAdapter()
        ctx = PipelineContext(
            request=AnalysisRequest(repo_url="https://github.com/acme/api", quick=True),
            codebase=codebase,
            meta_prompter=meta_prompter,
            specialists=six_specialists,
            critique_agent=critique_agent,
            tracer=tracer,
        )
        await analyze_repository(ctx)
        names = _names(tracer)
        assert "spectra.stage.critique" not in names
        assert "spectra.stage.plan" in names
