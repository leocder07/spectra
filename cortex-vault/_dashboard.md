# Cortex Dashboard

> Entry point for Spectra project knowledge graph.

## Quick Links

- [[projects/spectra/_index|Spectra Project]]
- [[projects/lumen/_index|LUMEN Project]]

## Active Sessions

```dataview
TABLE status, task FROM "memories/sessions"
WHERE status = "active"
SORT created DESC
```

## Recent Decisions

```dataview
TABLE status, impact FROM "decisions"
SORT file.cday DESC
LIMIT 10
```

## Open Tasks

```dataview
TABLE status, priority FROM "agents/tasks"
WHERE status != "done"
SORT priority ASC
```

## People

- [[agents/profiles/vivek|Vivek]] — CTO / Team Lead

## Tags Index

#project/spectra #project/lumen
#type/session #type/decision #type/learning #type/task #type/pattern
#status/active #status/done #status/blocked
#domain/backend #domain/frontend #domain/infra #domain/agents #domain/cli
#priority/p0 #priority/p1 #priority/p2
