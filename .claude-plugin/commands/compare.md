---
description: Compare two Spectra reports to show score changes over time
---

# Spectra Compare

Compare two Spectra report files to show score changes per dimension.

## Arguments

`$ARGUMENTS` should be two file paths separated by a space:
- First path: the "before" report (baseline)
- Second path: the "after" report (current)

If only one path is provided, look for the most recent other report in `examples/` as the baseline.

## Steps

1. Read both HTML report files.

2. Extract from each report:
   - Repository name (from `<title>`)
   - Overall grade and numeric score
   - Per-dimension scores: Architecture, Security, Quality, Documentation, Maintainability, Performance
   - Total finding count per dimension

3. Compute deltas for each dimension and overall:
   - Delta = after_score - before_score
   - Positive delta = improvement (show in green)
   - Negative delta = regression (show in red)
   - Zero delta = unchanged

4. Present the comparison:

   ```
   SPECTRA COMPARE
   ═══════════════════════════════════════════════════════
   Dimension        Before    After     Delta
   ───────────────────────────────────────────────────────
   Overall          B- (80)   A- (87)   +7  ▲ improved
   Architecture     89 A-     91 A      +2  ▲
   Security         67 D+     83 B+     +16 ▲▲ big jump
   Quality          87 B+     90 A      +3  ▲
   Documentation    68 C-     86 B+     +18 ▲▲ big jump
   Maintainability  92 A      87 A-     -5  ▼ regression
   Performance      76 C+     83 B      +7  ▲
   ───────────────────────────────────────────────────────
   Findings         46        59        +13
   ```

5. Summarize:
   - Number of dimensions that improved vs regressed
   - Biggest improvement and biggest regression
   - Whether the overall grade changed

6. Use color indicators:
   - Green (▲) for improvements
   - Red (▼) for regressions
   - Amber for small changes (±2 points)
