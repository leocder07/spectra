"""Six-scan validation: 3 with the old (40/60 LLM blend) formula vs
3 with the new (penalty-only) formula introduced in PR #60.

The old scans came from main when the LLM blend was still active.
The new scans came from main after PR #60 + R3 fixes merged.
Same code (within R3 fix delta), same model, same effort, all forced.
"""
import json
from collections import Counter
from pathlib import Path

REPORTS = Path("docs/launch/reports/v0.6.0")

old_paths = [
    REPORTS / "spectra-self-confidential.json",
    REPORTS / "spectra-self-after-fixes-confidential.json",
    REPORTS / "spectra-self-scan-3-confidential.json",
]
new_paths = [
    REPORTS / "spectra-self-scan-4-confidential.json",
    REPORTS / "spectra-self-scan-5-confidential.json",
    REPORTS / "spectra-self-scan-6-confidential.json",
]


def stats(path):
    with open(path) as f:
        d = json.load(f)
    sc = d["score_card"]
    sev = Counter(f["severity"] for f in d["findings"])
    return {
        "overall_score": sc["overall_score"],
        "overall_grade": sc["overall_grade"],
        "total_findings": len(d["findings"]),
        "critical": sev.get("critical", 0),
        "high": sev.get("high", 0),
        "medium": sev.get("medium", 0),
        "low": sev.get("low", 0),
        "info": sev.get("info", 0),
        "cost": d.get("total_cost_usd", 0),
        "duration": d.get("analysis_duration_seconds", 0),
        "dims": {dim["dimension"]: dim["score"] for dim in sc["dimensions"]},
    }


old = [stats(p) for p in old_paths]
new = [stats(p) for p in new_paths]


def col(s, n=14):
    return str(s).ljust(n)


print("=" * 76)
print(f"  OLD FORMULA (0.4·LLM + 0.6·penalty)        NEW FORMULA (penalty-only)")
print("=" * 76)
print(f'{"":12}{col("scan #1")}{col("scan #2")}{col("scan #3")}|{col("scan #4")}{col("scan #5")}{col("scan #6")}')
print("-" * 76)


def fmt_grade(r):
    return f'{r["overall_grade"]} ({r["overall_score"]:.0f})'


print(f'{"Overall":12}' + "".join(col(fmt_grade(r)) for r in old) + "|" + "".join(col(fmt_grade(r)) for r in new))
print(f'{"Findings":12}' + "".join(col(r["total_findings"]) for r in old) + "|" + "".join(col(r["total_findings"]) for r in new))
print(f'{"Critical":12}' + "".join(col(r["critical"]) for r in old) + "|" + "".join(col(r["critical"]) for r in new))
print(f'{"High":12}' + "".join(col(r["high"]) for r in old) + "|" + "".join(col(r["high"]) for r in new))
print(f'{"Cost":12}' + "".join(col(f'${r["cost"]:.2f}') for r in old) + "|" + "".join(col(f'${r["cost"]:.2f}') for r in new))


def stats_for(arr):
    scores = [r["overall_score"] for r in arr]
    return min(scores), max(scores), sum(scores) / len(scores), max(scores) - min(scores)


old_min, old_max, old_mean, old_spread = stats_for(old)
new_min, new_max, new_mean, new_spread = stats_for(new)

print()
print("=" * 76)
print(f"VARIANCE COMPARISON")
print("=" * 76)
print(f"{'':30}{'OLD':>14}{'NEW':>14}")
print("-" * 76)
print(f"{'Overall score range':30}{f'{old_min:.0f}–{old_max:.0f}':>14}{f'{new_min:.0f}–{new_max:.0f}':>14}")
print(f"{'Spread (max - min)':30}{f'{old_spread:.0f} pts':>14}{f'{new_spread:.0f} pts':>14}")
print(f"{'Mean':30}{f'{old_mean:.1f}':>14}{f'{new_mean:.1f}':>14}")
print()
print(f"  Spread reduction: {old_spread:.0f} pts → {new_spread:.0f} pts  ({(1 - new_spread/old_spread)*100:.0f}% reduction)")
print(f"  Mean shift:       +{new_mean - old_mean:.1f} pts")
print()
print("Per-dimension spread comparison (max - min across the 3 runs)")
print("-" * 76)
print(f"{'Dimension':18}{'OLD spread':>14}{'NEW spread':>14}{'Reduction':>20}")
for dim in ("architecture", "security", "quality", "documentation", "maintainability", "performance"):
    o_scores = [r["dims"][dim] for r in old]
    n_scores = [r["dims"][dim] for r in new]
    o_spread = max(o_scores) - min(o_scores)
    n_spread = max(n_scores) - min(n_scores)
    if o_spread > 0:
        red = f"{(1 - n_spread/o_spread)*100:+.0f}%"
    else:
        red = "n/a"
    print(f"{dim:18}{f'{o_spread:.0f} pts':>14}{f'{n_spread:.0f} pts':>14}{red:>20}")
