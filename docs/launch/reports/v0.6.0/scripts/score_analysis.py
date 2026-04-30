"""Reverse-engineer the per-dimension scores from the finding penalty formula.

Formula (from src/spectra/use_cases/analyze_repository.py):
    raw_penalty = sum(PENALTY[sev] * confidence for each finding)
    capped_penalty = min(raw_penalty, 55)
    penalty_score = max(0, 100 - capped_penalty)

When LLM emits a dimension_score (the per-agent holistic), the final
dimension score = 0.4 * llm_score + 0.6 * penalty_score.

PENALTY = {critical: 15, high: 8, medium: 3, low: 1, info: 0}
"""
import json
from collections import Counter, defaultdict

PENALTY = {'critical': 15.0, 'high': 8.0, 'medium': 3.0, 'low': 1.0, 'info': 0.0}
MAX_PENALTY = 55.0

scans = [
    ('#1 baseline', 'docs/launch/reports/v0.6.0/spectra-self-confidential.json'),
    ('#2 (PRs 54+55+56)', 'docs/launch/reports/v0.6.0/spectra-self-after-fixes-confidential.json'),
    ('#3 (PRs 57+58)', 'docs/launch/reports/v0.6.0/spectra-self-scan-3-confidential.json'),
]


def by_dim(findings):
    g = defaultdict(list)
    for f in findings:
        g[f['dimension']].append(f)
    return g


def penalty(findings):
    raw = sum(PENALTY[f['severity']] * f.get('confidence', 1.0) for f in findings)
    return min(raw, MAX_PENALTY)


print(f'\n{"":18}{"sc1":>14}{"sc2":>14}{"sc3":>14}')
print('-' * 60)
data = []
for label, path in scans:
    with open(path) as f:
        d = json.load(f)
    g = by_dim(d['findings'])
    sc = d['score_card']
    rec = {'label': label, 'g': g, 'reported': {dim['dimension']: dim['score'] for dim in sc['dimensions']}}
    data.append(rec)

for dim in ('architecture', 'security', 'quality', 'documentation', 'maintainability', 'performance'):
    line = f'{dim:18}'
    for d in data:
        f_list = d['g'][dim]
        p = penalty(f_list)
        psc = max(0, 100 - p)
        rep = d['reported'].get(dim, 0)
        sev = Counter(f['severity'] for f in f_list)
        # Format: "penalty_score | reported   (mix)"
        mix = ''.join(f'{sev[s]}{s[0]}' for s in ('critical', 'high', 'medium', 'low') if s in sev)
        cell = f'{psc:.0f}|{rep:.0f} ({mix})'
        line += f'{cell:>14}'
    print(line)

print('\n=== Decomposition: penalty score vs reported (LLM blend) ===')
print('Format: "penalty_only | reported (severity mix)"')
print('"penalty_only" = pure formula. "reported" = 40% LLM holistic + 60% penalty.')
print('Gap between penalty_only and reported = LLM influence.')

print('\n=== Severity mix per scan ===')
for d in data:
    counts = Counter(f['severity'] for f_list in d['g'].values() for f in f_list)
    print(f"  {d['label']:25}", dict(counts))

# Find findings that appear across multiple scans (stable signal)
print('\n=== Cross-scan finding overlap ===')
all_titles = []
for d in data:
    titles = {f['title'] for f_list in d['g'].values() for f in f_list}
    all_titles.append(titles)

shared_3 = all_titles[0] & all_titles[1] & all_titles[2]
shared_2 = (all_titles[0] & all_titles[1]) | (all_titles[1] & all_titles[2]) | (all_titles[0] & all_titles[2])
unique_1 = all_titles[0] - all_titles[1] - all_titles[2]
unique_2 = all_titles[1] - all_titles[0] - all_titles[2]
unique_3 = all_titles[2] - all_titles[0] - all_titles[1]

print(f'In all 3 scans:    {len(shared_3)} (stable signal)')
print(f'In 2 of 3 scans:   {len(shared_2 - shared_3)} (medium signal)')
print(f'Only in scan #1:   {len(unique_1)} (stochastic / one-shot)')
print(f'Only in scan #2:   {len(unique_2)} (stochastic / one-shot)')
print(f'Only in scan #3:   {len(unique_3)} (stochastic / one-shot)')

if shared_3:
    print('\n=== Findings in all 3 scans (these are the REAL issues) ===')
    for t in sorted(shared_3):
        print(f'  • {t[:80]}')
