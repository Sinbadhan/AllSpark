# ADR 002 — Tier 3 Knowledge Expert Review

- **Status:** Deferred to v2.0+
- **Date:** 2026-06-13
- **Last review:** 2026-06-13
- **Related:** PRD §6 knowledge tiers; `allspark/services/knowledge_verifier.py`

## Context

The knowledge base is split into tiers:

- **Tier 0/1/2** — survival fundamentals, agriculture, mechanics, etc.
  Authored by maintainers, cross-referenced against open sources.
- **Tier 3** — community organisation, civic engineering, advanced
  medicine, civilizational rebuilding. High consequence if wrong.

The verification flow (`KnowledgeVerifier`) checks structural integrity
(format, source presence, internal consistency, cross-references,
labelled level), not whether the content is *true*. Tier 3 entries
need a stronger signal than "the schema validates".

## Options considered

1. **Single maintainer review (status quo).**
   The release maintainer reads every Tier 3 entry before it lands on
   `main`. Simple; not scalable; single point of taste failure.
2. **Two-of-three reviewer panel.**
   Each Tier 3 entry must collect approvals from two named domain
   reviewers from a published roster. Hard to bootstrap until the
   community exists.
3. **External citation + mandatory source link.**
   Tier 3 entries refuse to merge without at least one verifiable
   external citation (URL, ISBN, archive snapshot). Mechanical, easy
   to enforce in CI; does not catch a credible-but-wrong source.
4. **Out-of-band attestation (signed reviewer note).**
   Reviewer signs a one-line attestation that gets stored in the
   knowledge entry. Combined with option 2 or 3.

## Decision

**v1.0 ships option 1 augmented by a lightweight option 3 in the
contributor guide.** Tier 3 entries must include at least one source
link in `references:`; reviewers reject if missing. The maintainer
remains the final gate.

**v2.0 evaluates option 2 + 4.** A two-reviewer panel with signed
attestations becomes feasible once the contributor base reaches a
size where domain coverage is realistic. ADR 003 (SKF signing) gives
us the cryptographic primitives needed for option 4; we should not
build a parallel signing system.

## When to revisit

- A Tier 3 entry causes a real-world reported issue.
- The contributor base grows past ~5 active reviewers with distinct
  domain expertise.
- v2.0 planning kicks off.

## Consequences

- For v1.0 we publish `CONTRIBUTING.md` guidance: Tier 3 = mandatory
  citation + maintainer review. No automation beyond schema checks.
- The verification flow's "verification" field stays advisory — it
  reflects what the verifier *can* check, not domain-expert sign-off.
- When ADR 003's signing scheme lands, this ADR will piggyback on it
  rather than introduce a separate trust path.
