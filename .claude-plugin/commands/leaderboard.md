---
description: Compare code health scores across multiple repositories
---

# Spectra Leaderboard

Compare code health scores across all analyzed repositories.

## Steps

1. Find all Spectra report files in the `examples/` directory:
   ```
   Look for *.html files that contain Spectra report data (grade-gauge, dim-score elements)
   ```

2. For each report file, extract:
   - Repository name (from the `<title>` tag: "Spectra Report — {name}")
   - Overall grade and score (from `.grade-gauge-letter` and `.grade-gauge-score`)
   - Per-dimension scores: Architecture, Security, Quality, Documentation, Maintainability, Performance
     (from `.dim-score` and `.dim-grade` elements paired with `.dim-label`)
   - Total finding count (sum the numbers in `<h2>Dimension (N)</h2>` headers)

3. Present a comparison table sorted by overall score (highest first):

   ```
   SPECTRA LEADERBOARD
   ═══════════════════════════════════════════════════════════════════════
   Repo           Overall  Arch  Sec   Qual  Docs  Maint  Perf  Findings
   ───────────────────────────────────────────────────────────────────────
   flask          A- (87)  91 A  83 B+ 90 A  86 B+ 87 A-  83 B  59
   express        B- (80)  89 A- 67 D+ 87 B+ 68 C- 92 A   76 C+ 46
   spectra        C- (70)  84 B+ 67 C- 62 D  65 D+ 68 C-  62 D  54
   ```

4. Highlight:
   - Best and worst scores per dimension
   - Common weak areas across repos
   - Which repos lead in each dimension

5. Offer to:
   - Show detailed findings for any specific repo
   - Open the leaderboard HTML page (`examples/leaderboard.html`) in a browser
   - Run a new analysis to add another repo to the comparison
