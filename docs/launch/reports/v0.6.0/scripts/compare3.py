import json
from collections import Counter

scans = [
    ('Scan #1 (v0.6.0 baseline)', 'docs/launch/reports/v0.6.0/spectra-self-confidential.json'),
    ('Scan #2 (after PR #54+#55+#56)', 'docs/launch/reports/v0.6.0/spectra-self-after-fixes-confidential.json'),
    ('Scan #3 (after PR #57+#58)', 'docs/launch/reports/v0.6.0/spectra-self-scan-3-confidential.json'),
]


def stats(path):
    with open(path) as f:
        d = json.load(f)
    sc = d['score_card']
    sev = Counter(f['severity'] for f in d['findings'])
    return {
        'overall': (sc['overall_grade'], sc['overall_score']),
        'total': len(d['findings']),
        'critical': sev.get('critical', 0),
        'high': sev.get('high', 0),
        'medium': sev.get('medium', 0),
        'low': sev.get('low', 0),
        'info': sev.get('info', 0),
        'cost': d.get('total_cost_usd', 0),
        'duration': d.get('analysis_duration_seconds', 0),
        'dims': {dim['dimension']: (dim['score'], dim['grade'], dim['findings_count']) for dim in sc['dimensions']},
    }


def col(s, n=22):
    return str(s).ljust(n)


rows = [stats(p) for _, p in scans]
labels = [name for name, _ in scans]

print(f'{"":18}{col(labels[0])}{col(labels[1])}{col(labels[2])}')
print('-' * 90)


def fmt_overall(r):
    g, s = r['overall']
    return f'{g} ({s:.0f})'


print(f'{"Overall":18}' + ''.join(col(fmt_overall(r)) for r in rows))
print(f'{"Total findings":18}' + ''.join(col(r['total']) for r in rows))
for sev in ('critical', 'high', 'medium', 'low', 'info'):
    print(f'{"  " + sev:18}' + ''.join(col(r[sev]) for r in rows))
print(f'{"Cost":18}' + ''.join(col(f'${r["cost"]:.2f}') for r in rows))
print(f'{"Duration":18}' + ''.join(col(f'{r["duration"]:.0f}s') for r in rows))
print()
print(f'{"Per-dimension":18}' + ''.join(col(labels[i]) for i in range(3)))
print('-' * 90)
for d in ('architecture', 'security', 'quality', 'documentation', 'maintainability', 'performance'):
    line = f'{d:18}'
    for r in rows:
        s, g, f_ = r['dims'][d]
        line += col(f'{int(s)} {g} ({f_}f)')
    print(line)

# Score variance
overall_scores = [r['overall'][1] for r in rows]
print(f'\nOverall score range: {min(overall_scores):.0f} - {max(overall_scores):.0f}  (spread: {max(overall_scores)-min(overall_scores):.0f} points)')
print(f'Mean: {sum(overall_scores)/3:.1f}')
