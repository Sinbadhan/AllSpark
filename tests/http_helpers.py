"""Explicit non-browser API client; boundary tests use raw TestClient instead.

The marker cannot be sent by a cross-origin browser without CORS preflight.
It is not an authentication bypass: Host, Origin and token checks still run.
"""
from fastapi.testclient import TestClient as RawTestClient


class LocalAPIClient(RawTestClient):
    def __init__(self, *args, headers=None, **kwargs):
        super().__init__(*args, headers={"X-AllSpark-Request": "1", **(headers or {})}, **kwargs)
