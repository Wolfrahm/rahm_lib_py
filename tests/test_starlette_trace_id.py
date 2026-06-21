"""Trace ID generation + RAHM_LOG_TRACE_ID env-var toggle."""
import importlib
import re

import pytest


CROCKFORD = '0123456789abcdefghjkmnpqrstvwxyz'
_ULID_RE = re.compile(rf'^[{CROCKFORD}]{{26}}$')


def test_ulid_is_26_chars_crockford():
    from rahm.starlette import _ulid
    for _ in range(100):
        u = _ulid()
        assert _ULID_RE.match(u), f"bad ulid: {u!r}"


def test_ulids_are_unique():
    from rahm.starlette import _ulid
    ids = {_ulid() for _ in range(1000)}
    assert len(ids) == 1000


def test_default_trace_id_enabled(monkeypatch):
    monkeypatch.delenv('RAHM_LOG_TRACE_ID', raising=False)
    import rahm.starlette
    importlib.reload(rahm.starlette)
    assert rahm.starlette._TRACE_ID_ENABLED is True


def test_trace_id_disabled(monkeypatch):
    monkeypatch.setenv('RAHM_LOG_TRACE_ID', 'disabled')
    import rahm.starlette
    importlib.reload(rahm.starlette)
    assert rahm.starlette._TRACE_ID_ENABLED is False


def test_trace_id_invalid_raises(monkeypatch):
    monkeypatch.setenv('RAHM_LOG_TRACE_ID', 'sometimes')
    import rahm.starlette
    with pytest.raises(ValueError, match='RAHM_LOG_TRACE_ID'):
        importlib.reload(rahm.starlette)


def test_trace_id_uppercase_normalized(monkeypatch):
    monkeypatch.setenv('RAHM_LOG_TRACE_ID', 'ENABLED')
    import rahm.starlette
    importlib.reload(rahm.starlette)
    assert rahm.starlette._TRACE_ID_ENABLED is True


def test_middleware_skips_trace_id_when_disabled(monkeypatch, capture_logs):
    monkeypatch.setenv('RAHM_LOG_TRACE_ID', 'disabled')
    import rahm.starlette
    importlib.reload(rahm.starlette)

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    async def hello(request):
        return PlainTextResponse('hi')

    app = Starlette(
        routes=[Route('/', hello)],
        middleware=[Middleware(rahm.starlette.RahmHttpMiddleware)],
    )
    client = TestClient(app)
    response = client.get('/')
    assert 'x-trace-id' not in response.headers

    import json
    logs = [json.loads(line) for line in capture_logs.getvalue().splitlines() if line.strip()]
    access = [log for log in logs if log['event'] == 'http_request_completed'][0]
    assert 'trace_id' not in access
