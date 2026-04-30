"""v0.7.0 OSS leaderboard — 5 repos scanned with the new deterministic scoring."""
import json
from pathlib import Path
from collections import Counter

REPORTS = Path("docs/launch/reports")
ENTRIES = [
    ("Spectra (self)", REPORTS / "v0.6.0/spectra-self-scan-5-confidential.json", "github.com/leocder07/spectra"),
    ("FastAPI", REPORTS / "v0.7.0/fastapi-fastapi-confidential.json", "github.com/fastapi/fastapi"),
    ("HTTPX", REPORTS / "v0.7.0/encode-httpx-confidential.json", "github.com/encode/httpx"),
    ("Simon Willison's LLM", REPORTS / "v0.7.0/simonw-llm-confidential.json", "github.com/simonw/llm"),
    ("Aider", REPORTS / "v0.7.0/aider-confidential.json", "github.com/Aider-AI/aider"),
]


rows = []
for name, path, url in ENTRIES:
    with open(path) as f:
        d = json.load(f)
    sc = d["score_card"]
    sev = Counter(f["severity"] for f in d["findings"])
    rows.append({
        "name": name,
        "url": url,
        "score": sc["overall_score"],
        "grade": sc["overall_grade"],
        "total": len(d["findings"]),
        "critical": sev.get("critical", 0),
        "high": sev.get("high", 0),
        "medium": sev.get("medium", 0),
        "low": sev.get("low", 0),
        "info": sev.get("info", 0),
        "cost": d.get("total_cost_usd", 0),
        "duration": d.get("analysis_duration_seconds", 0),
        "dims": {dim["dimension"]: (dim["score"], dim["grade"]) for dim in sc["dimensions"]},
    })

rows.sort(key=lambda r: -r["score"])

print(f'{"Repo":24}{"Grade":>10}{"Findings":>10}{"Critical":>10}{"High":>6}{"Cost":>9}{"Duration":>10}')
print("-" * 80)
for r in rows:
    print(f'{r["name"]:24}{r["grade"] + " ("+str(int(r["score"]))+")":>10}{r["total"]:>10}{r["critical"]:>10}{r["high"]:>6}{"$"+f"{r["cost"]:.2f}":>9}{f"{r["duration"]:.0f}s":>10}')

print()
print("Per-dimension:")
print(f'{"Repo":24}{"Arch":>8}{"Sec":>8}{"Qual":>8}{"Doc":>8}{"Maint":>8}{"Perf":>8}')
print("-" * 80)
for r in rows:
    line = f'{r["name"]:24}'
    for d in ("architecture", "security", "quality", "documentation", "maintainability", "performance"):
        if d in r["dims"]:
            score, grade = r["dims"][d]
            line += f'{int(score)}{" "+grade:>4}'.rjust(8)
        else:
            line += f'{"—":>8}'
    print(line)
