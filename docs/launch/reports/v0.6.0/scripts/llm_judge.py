"""LLM-as-judge: cluster findings across 3 self-scans semantically.

We have 133 findings spread across 3 scans of identical code. Zero
exact-title overlap. Hypothesis: many findings are the same underlying
issue with different phrasings.

This script asks Claude to cluster the findings, then we count how many
DISTINCT issues exist vs how many phrasings the LLM emitted.
"""
import json
import os
from collections import defaultdict
from anthropic import Anthropic

scans = [
    ('docs/launch/reports/v0.6.0/spectra-self-confidential.json', '#1'),
    ('docs/launch/reports/v0.6.0/spectra-self-after-fixes-confidential.json', '#2'),
    ('docs/launch/reports/v0.6.0/spectra-self-scan-3-confidential.json', '#3'),
]

# Collect all findings with scan tag
all_findings = []
for path, tag in scans:
    with open(path) as f:
        d = json.load(f)
    for f_obj in d['findings']:
        loc = f_obj.get('location', {})
        all_findings.append({
            'scan': tag,
            'dim': f_obj['dimension'],
            'sev': f_obj['severity'],
            'title': f_obj['title'],
            'desc': f_obj.get('description', '')[:200],
            'file': loc.get('file_path', '?'),
            'line': loc.get('line_start', 0),
        })

print(f'Total findings across 3 scans: {len(all_findings)}')

# Group by dimension first (judge dimension by dimension to keep prompts focused)
by_dim = defaultdict(list)
for f in all_findings:
    by_dim[f['dim']].append(f)

# For each dimension, ask Claude to cluster
client = Anthropic()
clusters_per_dim = {}

for dim in sorted(by_dim.keys()):
    fs = by_dim[dim]
    if len(fs) <= 1:
        clusters_per_dim[dim] = [[i] for i in range(len(fs))]
        continue

    # Build numbered list for Claude
    numbered = '\n'.join(
        f"[{i}] (scan {f['scan']}, {f['sev']}, {f['file']}:{f['line']}): {f['title']}\n     {f['desc'][:120]}"
        for i, f in enumerate(fs)
    )

    prompt = f"""You are deduplicating code-quality findings from 3 separate scans of the same codebase. Same code, different LLM passes — many findings describe the same underlying issue with different wording.

Below are {len(fs)} findings in the {dim} dimension. Group them into clusters where each cluster contains findings about the SAME underlying issue (regardless of how it's phrased or which file:line is named).

A cluster of size 1 means a unique issue. A cluster of size 3 means the same issue was independently discovered in all 3 scans (high-confidence real signal).

Findings:
{numbered}

Output ONLY a JSON object of this shape — no prose, no markdown fence:
{{"clusters": [[0, 4, 7], [1], [2, 8], ...]}}

Each inner list contains the indices of findings in one cluster."""

    print(f'\nClustering {dim} ({len(fs)} findings)...', flush=True)
    resp = client.messages.create(
        model='claude-opus-4-7',
        max_tokens=2000,
        messages=[{'role': 'user', 'content': prompt}],
    )
    text = resp.content[0].text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    try:
        result = json.loads(text)
        clusters_per_dim[dim] = result['clusters']
    except (json.JSONDecodeError, KeyError) as e:
        print(f'  ERROR parsing response: {e}\n  Got: {text[:200]}')
        clusters_per_dim[dim] = [[i] for i in range(len(fs))]

# Analyze clusters
print('\n\n=== CLUSTER ANALYSIS ===\n')
total_real = 0
total_stochastic = 0
total_findings = 0
detail_lines = []

for dim, clusters in sorted(clusters_per_dim.items()):
    fs = by_dim[dim]
    n = len(fs)
    sizes = [len(c) for c in clusters]
    in_3_runs = sum(1 for c in clusters if len(c) >= 3)
    in_2_runs = sum(1 for c in clusters if len(c) == 2)
    one_shot = sum(1 for c in clusters if len(c) == 1)
    distinct = len(clusters)

    print(f'{dim:18}  {n:3} findings → {distinct:3} distinct issues  '
          f'(stable: {in_3_runs}, partial: {in_2_runs}, one-shot: {one_shot})')

    total_real += in_3_runs + in_2_runs
    total_stochastic += one_shot
    total_findings += n

    # Detail: list the stable + partial clusters
    for c in clusters:
        if len(c) >= 2:
            scans_present = sorted({fs[i]['scan'] for i in c})
            ttl = fs[c[0]]['title'][:80]
            detail_lines.append(f"  [{dim:13} | scans {','.join(scans_present)} | size {len(c)}] {ttl}")

print(f'\n--- Totals ---')
print(f'Total findings:      {total_findings}')
print(f'Distinct issues:     {sum(len(cs) for cs in clusters_per_dim.values())}')
print(f'  appearing in 2-3 scans (real): {total_real}')
print(f'  appearing in 1 scan (stochastic): {total_stochastic}')
print(f'  → de-dup ratio: {total_findings / (total_real + total_stochastic):.2f}x')

print(f'\n--- "Real" issues (in 2 or 3 scans) ---')
for line in detail_lines:
    print(line)
