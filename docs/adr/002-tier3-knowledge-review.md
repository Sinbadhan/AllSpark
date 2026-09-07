# ADR 002 — Tier 3 Knowledge Expert Review

- **Status:** Accepted — all bundled tiers require content and risk gates
- **Date:** 2026-06-13
- **Last review:** 2026-09-07
- **Related:** PRD §6 knowledge tiers; `allspark/services/knowledge_verifier.py`

## Current decision (supersedes the historical v1 exception below)

AS-11 requires the full bundled inventory, in both languages, to receive
traceable domain risk review. Operational content must also pass the existing
local content-evidence gate. The runtime contract is
`core/models.py:is_actionable_knowledge`; source references alone do not grant
risk approval, and an automated consistency check is not a professional review.
Pending, missing or unknown classifications stay fail-closed. No tier, including
Tier 0, is exempt; a future reviewer-panel workflow is not permission to defer
the present safety gate to v2.

Named reviews must cover the actual hazards and qualifications and pin the
exact content/classification hash. Chinese and English records are separate
review objects. Current source/reference gaps are reported without mutation by
`scripts/knowledge_review_inventory.py`; bundled topics are not claimed to be
cross-referenced merely because they were authored by maintainers.

The cost is reduced immediately actionable content until real reviews exist.
That is preferable to upgrading unverified survival instructions to trusted
guidance. Organising a larger reviewer panel remains future work; cryptographic
SKF transport signing remains separately deferred in ADR 003. Neither changes
the current knowledge trust boundary. Formal decisions and review evidence live
in the Feishu plan and AS-11 task, not Linear.

## Historical context and decision (2026-06-13; superseded)

The following records the original rationale, not the current acceptance rule.

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
