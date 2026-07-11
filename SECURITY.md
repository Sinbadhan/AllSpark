# Security Policy

AllSpark is offline-first software for local survival decision support. Security work should protect local data, knowledge integrity, and safe operation in degraded environments.

## Supported versions

| Version | Supported |
|---------|-----------|
| 1.0.x | Yes |
| 0.7.x | Yes (maintenance) |
| Older versions | No |

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting or GitHub Security Advisories for this repository. If a private maintainer contact is added later, this file should be updated before public release.

When reporting, include:

- Affected version or commit.
- Steps to reproduce.
- Impact and affected data or subsystem.
- Whether the issue requires local access, network access, crafted SKF packages, model files, or database files.
- Any suggested mitigation.

Please do not disclose exploitable issues publicly until maintainers have had a reasonable chance to assess and fix them.

## Security boundaries

AllSpark is not a substitute for professional medical, legal, engineering, or emergency response advice. The software should fail conservatively when confidence is low.

High-risk inputs include:

- SKF knowledge packages and imported archives.
- External knowledge base files.
- Local model files and model metadata.
- SQLite databases and backups.
- Network exchange payloads on LAN or future disaster channels.

Treat these as untrusted unless their origin and integrity are known.

## Sensitive data

Do not commit or publish:

- `~/.allspark/` runtime data.
- Local databases, journals, snapshots, and backups.
- Survivor profiles, diary entries, locations, or resource status.
- Local model weights.
- Private keys, tokens, certificates, or environment files.
- Logs that may include personal or operational details.

The repository `.gitignore` is configured to exclude common runtime data, local models, logs, secrets, and generated build outputs.

## Network features

Network exchange features should assume a hostile or unreliable local network. Future changes should prefer explicit user action, input validation, clear trust boundaries, and defensive parsing over automatic trust.

## Disclosure expectations

Maintainers should acknowledge security reports when possible, assess severity, prepare a fix or mitigation, and document any user action required. If a fix is not possible immediately, document safe workarounds.
