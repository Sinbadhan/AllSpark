# ADR 001 — Spark-to-Spark Communication Encryption

- **Status:** Deferred to v2.0+
- **Date:** 2026-06-13
- **Last review:** 2026-06-13
- **Related:** PRD §11 communication; `allspark/services/spark_network.py`

## Context

Spark-to-Spark communication today uses UDP beacons for discovery and
TCP for knowledge exchange (see `spark_network.py`). Traffic is sent
in cleartext on the assumption that operators run on a trusted LAN,
Wi-Fi Direct ad-hoc, or Bluetooth PAN segment.

For a post-disaster setting this is a defensible default — there is
usually no PKI, no DNS, and limited spectrum — but the assumption is
not durable: ZIM/SKF packs and governance messages can carry sensitive
content (community plans, medical records, location data). Cleartext
on a contested radio link is unsafe.

We need to record the decision now so v1.0 ships with eyes open.

## Options considered

1. **Cleartext + trusted-network assumption (status quo).**
   No code change. Document it. Operators must isolate the network.
2. **Pre-shared key + ChaCha20-Poly1305.**
   Symmetric AEAD, simple key derivation from a passphrase
   (`scrypt`/`argon2`). Cheap to deploy; rotation is manual.
3. **X25519 ECDH + ChaCha20-Poly1305 with TOFU pinning.**
   Forward secrecy, no shared secret needed. Trust on first contact;
   each spark pins peer public keys after the first handshake.
4. **Full PKI (per-spark Ed25519 identity + signed introductions).**
   Strongest, but requires an introducer / community trust ceremony.

## Decision

**v1.0 ships option 1.** Document the trust boundary in
`SECURITY.md` and `docs/CONFIGURATION.md`. Refuse to send Tier 3
governance/health payloads over an unencrypted link by default; gate
that behind an explicit opt-in flag (future task, not blocking v1.0).

**v2.0 evaluates option 3 (X25519 + ChaCha20 + TOFU).** Option 2 is
cheaper to implement but does not survive a single key leak; option 4
needs a social process this project does not yet have.

## When to revisit

- A field deployment reports cleartext capture or replay attacks.
- Tier 3 content needs to flow over unfamiliar links (cross-community
  trades, mesh extensions).
- v2.0 planning kicks off, regardless of incident pressure.

## Consequences

- v1.0 documentation must explicitly call cleartext communication a
  trust-boundary contract.
- Any future encryption layer should be additive — packet framing must
  leave room for a version byte and a cipher suite identifier so we
  can roll forward without breaking existing peers.
- This ADR is paired with [ADR 003](./003-skf-package-signing.md);
  knowledge-pack integrity and link-layer confidentiality are separate
  concerns and should not be conflated.
