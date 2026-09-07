from email.message import Message

import pytest

from scripts.smoke_installed_web import validate_rendered_page


def _headers(*, include_csp: bool = True) -> Message:
    headers = Message()
    headers["Content-Type"] = "text/html; charset=utf-8"
    if include_csp:
        headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src-attr 'none'; object-src 'none'"
        )
    return headers


def _body() -> str:
    return (
        '<!DOCTYPE html><button id="immediate-danger-open"></button>'
        '<section id="immediate-danger-dialog"></section>'
    )


def test_installed_web_smoke_contract_accepts_first_run_page() -> None:
    validate_rendered_page(200, _headers(), _body())


@pytest.mark.parametrize(
    ("status", "headers", "body", "error"),
    [
        (500, _headers(), "", "expected HTTP 200"),
        (200, Message(), "", "did not render HTML"),
        (200, _headers(include_csp=False), _body(), "missing the enforcing CSP"),
        (200, _headers(), "<!DOCTYPE html>", "immediate-danger-open"),
    ],
)
def test_installed_web_smoke_contract_fails_closed(
    status: int, headers: Message, body: str, error: str
) -> None:
    with pytest.raises(RuntimeError, match=error):
        validate_rendered_page(status, headers, body)
