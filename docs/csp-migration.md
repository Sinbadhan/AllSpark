# CSP Migration Plan (SHA-196)

## Current state

A **Content-Security-Policy-Report-Only** header is stamped on every response
by `allspark/adapters/web_ui.py` (`add_csp_header` middleware). Report-Only
mode logs violations to the browser console **without blocking** anything, so
the existing inline scripts keep working. This is the baseline second line of
defense alongside SHA-147's SKF input/output sanitization.

The policy (see `CSP_REPORT_ONLY`):

```
default-src 'self';
script-src 'self';              /* NO 'unsafe-inline' - the migration target */
style-src 'self' 'unsafe-inline';   /* templates use inline styles + <style> */
img-src 'self' data:;
connect-src 'self';
object-src 'none';
base-uri 'self';
frame-ancestors 'none';
```

No external resources are loaded (no CDNs, no Google Fonts) - the app is fully
self-hosted, so `default-src 'self'` covers everything.

## Why Report-Only, not enforcing

The templates use **8 inline `<script>` blocks** and **88 inline event
handlers** (`onclick`/`onkeydown`/`onchange`/...). An enforcing CSP with
`script-src 'self'` (no `'unsafe-inline'`) would block all of them and break
the UI. Report-Only surfaces each violation so it can be migrated deliberately.

### Inline inventory (per template)

| Template | `<script>` blocks | Inline handlers |
| -- | -- | -- |
| base.html | 1 | 7 |
| config.html | 1 | 0 |
| executions.html | 1 | 11 |
| index.html | 1 | 17 |
| init.html | 1 | 12 |
| login.html | 1 | 0 |
| repository.html | 1 | 21 |
| system.html | 1 | 20 |
| **Total** | **8** | **88** |

## Migration steps (to switch to enforcing CSP)

1. **Move inline `<script>` blocks to external files.** Each template's script
   block becomes a per-page `.js` file served from a static path (or a single
   bundled file). If a script must stay inline, use a per-request nonce and
   `script-src 'self' 'nonce-<...>'`.
2. **Replace inline event handlers with `addEventListener`.** Move
   `onclick="openResourceEdit(...)"` etc. to JS that queries by `data-*`
   attributes (e.g. `data-rtype`, `data-action`) and attaches listeners. The
   SHA-147 `data-kid` event-delegation pattern (already used for SKF entries)
   is the reference.
3. **Watch the Report-Only console** during manual/CI browser runs to catch
   any remaining violations before enforcing.
4. **Switch the header** from `Content-Security-Policy-Report-Only` to
   `Content-Security-Policy` (enforcing) in `add_csp_header` once the console
   is clean.
5. *(Optional)* **Add a report endpoint** (`report-uri /api/csp/report` or
   `report-to`) to collect violations in production. The endpoint should be
   unauthenticated (CSP reports can't carry cookies), rate-limited, and log
   only the violation fields needed for triage.

## Browser regression gate

`tests/test_sha196_browser.py` drives an installed Chrome in headless mode over
the local DevTools protocol. It uses a temporary database and loopback-only
server, imports malicious SKF metadata through `/api/skf/import`, and checks the
Repository and Dashboard list/detail DOM states. CI fails rather than skips when
Chrome is absent.

## Remaining risk

* **Strict CSP enforcement** - blocked on the inline script/handler migration
  above.
* **`style-src 'unsafe-inline'`** - left in place because templates use inline
  styles heavily. Tightening to nonce-based styles is a separate, larger
  migration and lower risk than script injection.

## Verification

* `tests/test_sha196_csp.py` asserts the Report-Only header is present on HTML
  and API responses, the enforcing header is absent, and `script-src` has no
  `'unsafe-inline'`.
* `tests/test_sha196_browser.py` covers the real SKF import -> API -> browser DOM
  path without external network access or a browser download.
* CSP enforcement remains a manual pre-flip check until the inline migration is
  complete; Report-Only is observability, not active blocking.
