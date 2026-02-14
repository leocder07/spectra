---
description: Run Spectra analysis on a repository — 8 AI agents analyze code across 6 dimensions
---

# Spectra Analyze

Run the full Spectra analysis pipeline on the repository at "$ARGUMENTS".

## Steps

1. Run the analysis using the Bash tool:
   ```
   cd /Users/leocder/Documents/spectra && .venv/bin/spectra analyze $ARGUMENTS
   ```

2. If the command succeeds, read the generated HTML report file and summarize:
   - Overall grade and score
   - Top 3-5 critical or high-severity findings
   - Dimension breakdown (Architecture, Security, Quality, Documentation, Maintainability, Performance)

3. If the command fails, explain the error using Spectra error codes:
   - SPEC-001: Git clone failed — check the repository URL
   - SPEC-002: API unreachable — check ANTHROPIC_API_KEY
   - SPEC-003: Rate limited — wait and retry
   - SPEC-004: Token budget exceeded — try a smaller repo or --quick
   - SPEC-006: Agent timeout — try --quick flag

4. After analysis, offer to:
   - Open the HTML report in browser
   - Explain specific findings in detail
   - Suggest fixes for critical issues
