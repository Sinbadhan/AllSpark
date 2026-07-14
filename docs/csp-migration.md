# CSP Enforcement (SHA-196 / SHA-213)

## Current state

All HTTP responses carry an enforcing `Content-Security-Policy` header. The
middleware in `allspark/adapters/web_ui.py` generates a fresh nonce for every
request, exposes it to Jinja through a request-scoped `ContextVar`, and stamps
the same nonce into every rendered `<script>` block.

The effective policy is:

```text
default-src 'self';
script-src 'self' 'nonce-<per-request value>';
script-src-attr 'none';
style-src 'self' 'unsafe-inline';
img-src 'self' data:;
connect-src 'self';
object-src 'none';
base-uri 'self';
frame-ancestors 'none'
```

Scripts cannot use `'unsafe-inline'`, and HTML event attributes are disabled
independently through `script-src-attr 'none'`. No CDN or external runtime
resource is required, so the offline execution boundary is unchanged.

## Template inventory

| Template | Nonced script blocks | Event attributes / property handlers |
| -- | --: | --: |
| base.html | 1 | 0 |
| config.html | 1 | 0 |
| executions.html | 1 | 0 |
| index.html | 1 | 0 |
| init.html | 1 | 0 |
| login.html | 1 | 0 |
| repository.html | 1 | 0 |
| system.html | 1 | 0 |
| **Total** | **8** | **0** |

Static controls and dynamically rendered controls use `addEventListener` or
delegation through stable `data-*` commands. User-controlled identifiers are
HTML-escaped before entering data attributes and are passed to functions as
data, not interpolated JavaScript source.

## Response boundary

The CSP middleware wraps the authentication middleware. Enforcement therefore
also applies to JSON APIs, 401 authentication failures, HTML redirects, and the
410 one-time-bootstrap closure response. Login and first-run pages receive the
same per-request nonce contract as initialized pages.

## Automated gates

* `tests/test_sha196_csp.py` proves enforcing-header presence, per-request nonce
  uniqueness, rendered nonce agreement, strict script directives, error-response
  coverage, and a zero-handler template inventory.
* `tests/test_sha213_csp_browser.py` drives installed Chrome across Dashboard,
  System, Config, Executions, Repository, Init, and Login. It performs real
  clicks through migrated handlers and fails on any `securitypolicyviolation`,
  JavaScript error, or unhandled rejection.
* `tests/test_sha196_browser.py` retains the public SKF import to Repository and
  Dashboard stored-XSS regression. Chrome is required in CI rather than skipped.

## Remaining boundary

`style-src 'unsafe-inline'` remains because templates still contain extensive
inline layout declarations and `<style>` blocks. Tightening styles to hashes,
nonces, or static stylesheets is separate defense-in-depth work; it does not
weaken the enforced script policy. A production CSP report collector is also
optional future observability, not a prerequisite for local enforcement.
