"""Tests for JSON output format in the composition root."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Import enums first so Pydantic can resolve forward refs in models.
from spectra.entities.disclaimer import DISCLAIMER_TEXT, DISCLAIMER_URL
from spectra.entities.enums import (  # noqa: F401
    AgentRole,
    Dimension,
    Grade,
    Severity,
)
from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    score_to_grade,
)
from spectra.infrastructure.main import build_json_payload

# Resolve deferred Pydantic annotations (TYPE_CHECKING guard in models.py).
Finding.model_rebuild()
DimensionScore.model_rebuild()
ScoreCard.model_rebuild()
AnalysisReport.model_rebuild()

_ALL_AGENTS = (
    "architecture",
    "security",
    "quality",
    "documentation",
    "dependency",
    "performance",
)


def _dim(
    name: str,
    score: float = 85.0,
    count: int = 0,
    weight: float = 0.10,
) -> DimensionScore:
    return DimensionScore(
        dimension=name,
        score=score,
        grade=score_to_grade(score),
        findings_count=count,
        weight=weight,
    )


def _minimal_report() -> AnalysisReport:
    """Create a minimal AnalysisReport for JSON output tests."""
    finding = Finding(
        id="TEST-001",
        dimension="security",
        severity="high",
        title="Test finding",
        description="Test description",
        location=FileLocation(
            file_path="src/main.py",
            line_start=10,
        ),
        recommendation="Fix this",
        agent_role="security",
        confidence=0.9,
    )
    dimensions = (
        _dim("architecture", 85.0, 0, 0.25),
        _dim("security", 80.0, 1, 0.25),
        _dim("quality", 85.0, 0, 0.20),
        _dim("documentation", 85.0, 0, 0.10),
        _dim("maintainability", 85.0, 0, 0.10),
        _dim("performance", 85.0, 0, 0.10),
    )
    overall = sum(d.score * d.weight for d in dimensions)
    score_card = ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=dimensions,
        total_findings=1,
    )
    return AnalysisReport(
        repo_url="https://github.com/test/repo",
        repo_name="repo",
        score_card=score_card,
        findings=(finding,),
        analysis_duration_seconds=5.0,
        total_tokens_used=1000,
        total_cost_usd=0.01,
        agents_used=_ALL_AGENTS,
        is_degraded=False,
        degraded_dimensions=(),
    )


class TestJsonOutput:
    """Verify JSON output produces valid JSON with all fields."""

    def test_model_dump_json_is_valid_json(self):
        report = _minimal_report()
        data = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
        )
        parsed = json.loads(data)
        assert isinstance(parsed, dict)

    def test_json_contains_all_report_fields(self):
        report = _minimal_report()
        parsed = report.model_dump(mode="json")

        expected_keys = {
            "repo_url",
            "repo_name",
            "score_card",
            "findings",
            "analysis_duration_seconds",
            "total_tokens_used",
            "total_cost_usd",
            "agents_used",
            "is_degraded",
            "degraded_dimensions",
            "cross_cutting_insights",
        }
        assert expected_keys.issubset(parsed.keys())

    def test_json_output_is_not_html(self):
        report = _minimal_report()
        data = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
        )
        assert "<html" not in data
        assert "<!DOCTYPE" not in data

    def test_json_written_to_file(self):
        report = _minimal_report()
        data = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
        )

        with tempfile.NamedTemporaryFile(
            suffix=".json",
            delete=False,
        ) as f:
            path = f.name

        Path(path).write_text(data, encoding="utf-8")
        content = Path(path).read_text(encoding="utf-8")
        parsed = json.loads(content)

        assert parsed["repo_name"] == "repo"
        assert parsed["repo_url"] == "https://github.com/test/repo"
        assert parsed["total_tokens_used"] == 1000
        assert parsed["is_degraded"] is False
        assert len(parsed["findings"]) == 1
        assert parsed["findings"][0]["severity"] == "high"

        Path(path).unlink()

    def test_json_scorecard_structure(self):
        report = _minimal_report()
        parsed = report.model_dump(mode="json")
        sc = parsed["score_card"]

        assert "overall_score" in sc
        assert "overall_grade" in sc
        assert "dimensions" in sc
        assert len(sc["dimensions"]) == 6
        for dim in sc["dimensions"]:
            assert "dimension" in dim
            assert "score" in dim
            assert "grade" in dim
            assert "weight" in dim


class TestJsonDisclaimer:
    """JSON output carries the indicative-analysis disclaimer at the top level.

    SAST consumers and machine pipelines read the disclaimer programmatically;
    it is a data field, not a UI element, and cannot be dismissed.
    """

    def test_payload_has_top_level_disclaimer(self):
        payload = build_json_payload(_minimal_report())
        assert "disclaimer" in payload

    def test_disclaimer_has_text_and_url(self):
        payload = build_json_payload(_minimal_report())
        assert payload["disclaimer"]["text"] == DISCLAIMER_TEXT
        assert payload["disclaimer"]["url"] == DISCLAIMER_URL

    def test_disclaimer_text_at_least_50_chars(self):
        payload = build_json_payload(_minimal_report())
        assert len(payload["disclaimer"]["text"]) >= 50

    def test_disclaimer_does_not_clobber_report_fields(self):
        payload = build_json_payload(_minimal_report())
        # Report fields must still be present alongside the disclaimer.
        assert payload["repo_name"] == "repo"
        assert payload["score_card"]["overall_grade"]
        assert isinstance(payload["findings"], list)

    def test_json_serializes_round_trip(self):
        payload = build_json_payload(_minimal_report())
        roundtrip = json.loads(json.dumps(payload))
        assert roundtrip["disclaimer"]["text"] == DISCLAIMER_TEXT


class TestJsonValidationStatus:
    """Q2 #20: JSON top-level ``validation_status`` is always present.

    SAST consumers and machine pipelines must be able to read the trust
    stamp programmatically — it is a data field, identical in shape across
    HTML, JSON, and SARIF.
    """

    def test_validated_default_is_present(self):
        payload = build_json_payload(_minimal_report())
        assert payload["validation_status"] == "validated"

    def test_quick_mode_propagates(self):
        report = _minimal_report().model_copy(update={"validation_status": "non-validated:quick-mode"})
        payload = build_json_payload(report)
        assert payload["validation_status"] == "non-validated:quick-mode"

    def test_critique_skipped_propagates(self):
        report = _minimal_report().model_copy(update={"validation_status": "non-validated:critique-skipped"})
        payload = build_json_payload(report)
        assert payload["validation_status"] == "non-validated:critique-skipped"

    def test_validation_status_at_top_level_not_nested(self):
        # Top-level so SAST consumers don't have to walk into score_card.
        payload = build_json_payload(_minimal_report())
        assert "validation_status" in payload
        assert "validation_status" not in payload.get("score_card", {})


class TestValidationStatusFormatConsistency:
    """Q2 #20: HTML, JSON, SARIF all surface the SAME validation_status string.

    A run cannot disagree with itself across formats — that would let an
    attacker downgrade trust in one consumer while showing "validated" to
    another. Same source of truth (``AnalysisReport.validation_status``),
    same string everywhere.
    """

    @pytest.fixture
    def quick_report(self):
        return _minimal_report().model_copy(update={"validation_status": "non-validated:quick-mode"})

    def test_json_and_sarif_agree_on_quick_mode(self, quick_report):
        from spectra.infrastructure.main import _build_sarif

        json_payload = build_json_payload(quick_report)
        sarif = _build_sarif(quick_report)
        assert (
            json_payload["validation_status"]
            == sarif["runs"][0]["properties"]["validation_status"]
            == "non-validated:quick-mode"
        )

    def test_json_and_sarif_agree_on_validated(self):
        from spectra.infrastructure.main import _build_sarif

        report = _minimal_report()
        json_payload = build_json_payload(report)
        sarif = _build_sarif(report)
        assert json_payload["validation_status"] == sarif["runs"][0]["properties"]["validation_status"] == "validated"


# ── Capability #56 — JSON classification parity ──────────────


def _classified(classification: str) -> AnalysisReport:
    """Return _minimal_report with a chosen classification."""
    return _minimal_report().model_copy(update={"classification": classification})


def _sensitive_finding() -> Finding:
    """Sensitive finding fixture for redaction grep tests."""
    return Finding(
        id="SEC-001",
        dimension="security",
        severity="critical",
        title="AWS access key AKIAIOSFODNN7EXAMPLE in source",
        description="-----BEGIN RSA PRIVATE KEY----- block in src/secrets.py",
        location=FileLocation(file_path="src/secrets.py", line_start=12),
        recommendation="Rotate keys and remove file from git history.",
        agent_role="security",
        confidence=0.99,
        estimated_hours=3.0,
        code_snippet="AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
    )


def _sensitive_report(classification: str) -> AnalysisReport:
    """A report with one sensitive finding, classified."""
    return _minimal_report().model_copy(
        update={
            "classification": classification,
            "findings": (_sensitive_finding(),),
        }
    )


class TestJsonClassificationConfidential:
    """Confidential JSON preserves the full report (no redaction)."""

    def test_classification_field_present(self):
        payload = build_json_payload(_classified("confidential"))
        assert payload["classification"] == "confidential"

    def test_findings_preserved_in_full(self):
        payload = build_json_payload(_sensitive_report("confidential"))
        assert len(payload["findings"]) == 1
        f = payload["findings"][0]
        assert "AKIAIOSFODNN7EXAMPLE" in f["title"]
        assert "BEGIN RSA PRIVATE KEY" in f["description"]
        assert f["location"]["file_path"] == "src/secrets.py"
        assert "AKIAIOSFODNN7EXAMPLE" in f["code_snippet"]

    def test_disclaimer_still_attached(self):
        payload = build_json_payload(_classified("confidential"))
        assert payload["disclaimer"]["text"] == DISCLAIMER_TEXT
        assert payload["disclaimer"]["url"] == DISCLAIMER_URL


class TestJsonClassificationPublic:
    """Public JSON drops every individual finding and all PII-bearing fields."""

    def test_classification_field_present(self):
        payload = build_json_payload(_classified("public"))
        assert payload["classification"] == "public"

    def test_findings_array_is_empty(self):
        payload = build_json_payload(_sensitive_report("public"))
        assert payload["findings"] == []

    def test_findings_count_preserved_at_top_level(self):
        # The numeric findings count survives even though individual
        # findings are dropped — capability #56 §4 keep-list.
        payload = build_json_payload(_sensitive_report("public"))
        assert payload["score_card"]["total_findings"] == 1
        # Per-dimension findings_count survives too.
        for dim in payload["score_card"]["dimensions"]:
            assert "findings_count" in dim

    def test_cross_cutting_insights_dropped(self):
        report = _classified("public").model_copy(
            update={"cross_cutting_insights": ("internal: re-architect auth flow",)}
        )
        payload = build_json_payload(report)
        assert payload.get("cross_cutting_insights") in (None, [])

    def test_no_sensitive_substrings_anywhere(self):
        # Grep test — render JSON to bytes and confirm none of the
        # planted markers leaked through.
        forbidden = ("AKIAIOSFODNN7EXAMPLE", "BEGIN RSA", "PRIVATE KEY", "src/secrets.py")
        payload = build_json_payload(_sensitive_report("public"))
        blob = json.dumps(payload)
        leaks = [s for s in forbidden if s in blob]
        assert not leaks, f"Public JSON leaked: {leaks}"

    def test_disclaimer_still_attached_in_public(self):
        # PR #38 disclaimer rides along regardless of classification.
        payload = build_json_payload(_classified("public"))
        assert payload["disclaimer"]["text"] == DISCLAIMER_TEXT

    def test_score_card_preserved(self):
        # Overall + per-dimension scores survive in public JSON.
        payload = build_json_payload(_classified("public"))
        sc = payload["score_card"]
        assert sc["overall_grade"]
        assert sc["overall_score"]
        assert len(sc["dimensions"]) == 6

    def test_repo_name_and_scan_metadata_preserved(self):
        # Capability #56 §4 keep-list: repo name, scan timestamp, version.
        payload = build_json_payload(_classified("public"))
        assert payload["repo_name"] == "repo"
        assert payload["repo_url"]  # URL is metadata, kept
        assert payload["analysis_duration_seconds"] == 5.0
