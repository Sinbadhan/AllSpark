# Architecture Decision Records

Records of architectural decisions whose rationale outlives any single
release. Each ADR is short, dated, and pinned to a status (Proposed,
Accepted, Deferred, Superseded).

| # | Title | Status |
|---|-------|--------|
| [001](./001-spark-network-encryption.md) | Spark-to-Spark Communication Encryption | Deferred to v2.0+ |
| [002](./002-tier3-knowledge-review.md)   | Tier 3 Knowledge Expert Review            | Deferred to v2.0+ |
| [003](./003-skf-package-signing.md)      | SKF Knowledge-Pack Signing                | Deferred to v2.0+ |

## Conventions

- One file per decision. Filename pattern: `NNN-kebab-title.md`.
- `Status:` line at the top. Common values:
  - **Proposed** — under discussion.
  - **Accepted** — decision is in effect.
  - **Deferred to vX.Y+** — recognised but not implemented.
  - **Superseded by ADR-NNN** — replaced; keep the file as history.
- Update `Last review:` when the ADR is consciously re-read; do not
  silently mutate the body without a status change.
- Cross-link related ADRs (`[ADR 001](./001-...)`).

These decisions used to live as bullet points in
`TECH-DECISIONS.md §4 待决策事项`. Treat the ADRs as the source of
truth; that section now only links here.
