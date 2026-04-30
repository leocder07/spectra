---
name: Mermaid `.md` files are diagram source of truth
description: SVG files in docs/diagrams/ are downstream artifacts; never hand-edit them
type: feedback
---

In `docs/diagrams/`, the `.md` files containing ```mermaid fences are the source of truth. The `.svg` siblings are generated artifacts that go stale whenever the Mermaid source is updated.

**Why:** The user uses Mermaid because it's diff-friendly and review-friendly. Hand-editing SVGs is fragile and unreviewable. The user explicitly said "do not regenerate the SVG files yourself" — instead, leave a "SVGs are stale" note at the top of `docs/diagrams/README.md` so a separate pipeline can re-render them.

**How to apply:** When updating a diagram, edit only the Mermaid source. If the corresponding `.svg` exists, add (or refresh) a stale-SVG note in `docs/diagrams/README.md` listing which Mermaid files have been updated since the last SVG regeneration. Do NOT shell out to mermaid-cli or any other renderer.
