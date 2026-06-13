# ADR 003 — SKF Knowledge-Pack Signing

- **Status:** Deferred to v2.0+
- **Date:** 2026-06-13
- **Last review:** 2026-06-13
- **Related:** PRD §6/§12 knowledge packs; `allspark/services/skf_manager.py`

## Context

SKF (Spark Knowledge Format) is a ZIP-packaged exchange format used to
move curated knowledge between AllSpark instances. Today the package
carries:

- A manifest describing producer / version / category.
- Knowledge entries serialised as YAML.
- A SHA256 digest covering the payload.

The SHA256 protects against accidental corruption (incomplete copy,
disk error, partial transfer). It does **not** protect against a
malicious producer or an attacker who substitutes a SKF in transit and
recomputes the digest. A field-deployed AllSpark with permissive trust
will silently merge whatever it imports.

Recent hardening (2026-06-13, commit `f176cf1`) confined the Web SKF
endpoints to `~/.allspark/skf/`, which closes the *path-traversal*
attack surface but does not address *content authenticity*.

## Options considered

1. **SHA256 only (status quo).**
   Detects corruption. Does not detect substitution. Fine for
   trusted couriers, dangerous for shared mesh distribution.
2. **HMAC with shared secret.**
   Symmetric authenticity. Same drawbacks as ADR 001 option 2 — key
   leakage breaks the entire community.
3. **Ed25519 detached signature + trusted-issuer list.**
   Each producer holds an Ed25519 keypair. The SKF carries a detached
   signature; importers maintain a list of trusted public keys, with
   per-entry override. Issuer rotation via list updates.
4. **Sigstore-style transparency log.**
   Heavier infrastructure. Excessive for a project that targets
   offline operation.
5. **Web-of-trust (PGP-style).**
   Strong but socially expensive; needs a key-signing process the
   project cannot operate yet.

## Decision

**v1.0 ships option 1.** Document explicitly in `SECURITY.md` that
SKF imports trust whoever produced the package. Importers must vet
the source out-of-band. The Web API path-traversal hardening landed
in 2026-06-13 closes the file-system attack vector; content
authenticity is a separate, deferred problem.

**v2.0 evaluates option 3 (Ed25519 + trusted-issuer list).** Option 2
is rejected as a half-measure; options 4 and 5 are over-engineered for
the deployment story.

## When to revisit

- A field-reported incident involving a tampered SKF.
- The community begins routine cross-spark exchange that bypasses
  out-of-band trust (mesh trades, shared archives).
- v2.0 planning kicks off.

## Consequences

- `SECURITY.md` for v1.0 must spell out the trust model: AllSpark
  validates SKF *integrity* (SHA256) and *path safety*, not
  *authenticity*.
- The pack format must reserve an optional `signature` field in the
  manifest now, even though it goes unused, so that v2.0 importers
  can verify against legacy v1.0 packs without a format break.
- This ADR pairs with [ADR 001](./001-spark-network-encryption.md):
  link-layer confidentiality and pack authenticity are independent
  decisions.
