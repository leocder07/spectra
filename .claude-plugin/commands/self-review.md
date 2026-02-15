---
description: Run Spectra on the current repository and review the findings
---

# Spectra Self-Review

Run Spectra's analysis on the current working directory and review the findings.

## Steps

1. Check if a recent Spectra report already exists for this repo:
   ```bash
   ls -la spectra-report.html examples/*self*.html examples/*spectra*.html 2>/dev/null
   ```

2. If no recent report exists (or user wants a fresh scan), run the analysis:
   ```bash
   cd /Users/leocder/Documents/spectra && .venv/bin/spectra analyze . --output spectra-self-review.html
   ```

3. Read the generated HTML report file.

4. Extract and present:
   - Overall grade and score
   - Per-dimension breakdown with scores and grades
   - Total number of findings by severity (critical, high, medium, low, info)

5. Identify the **top 3 highest-impact fixes**:
   - Prioritize critical and high severity findings
   - For each fix, explain:
     - What the issue is
     - Which file(s) are affected
     - Why it matters
     - A concrete fix recommendation

6. Present a summary:

   ```
   SPECTRA SELF-REVIEW
   ═══════════════════════════════════════════
   Overall: C- (70/100)

   Top 3 Fixes:
   1. [Critical] Security — hardcoded API key pattern in tests/conftest.py
      → Move to environment variable, add .env.example
   2. [High] Quality — cyclomatic complexity > 15 in orchestrate_agents.py
      → Extract helper functions for error handling paths
   3. [High] Documentation — no docstrings on public Protocol methods
      → Add docstrings to interfaces.py Protocol classes
   ```

7. Offer to:
   - Fix any of the top 3 issues right now
   - Compare with a previous self-review (via /spectra:compare)
   - Show all findings for a specific dimension
