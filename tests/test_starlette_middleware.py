"""RahmHttpMiddleware via Starlette TestClient.

We don't boot real uvicorn — TestClient drives the ASGI app in-process. That
lets us assert on captured log output without TCP, threads, or sleeps.
"""
import io
import json

import pytest
import rahm
from rahm.starlette import RahmHttpMiddleware

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


async def _hello(request):
    rahm.log.bind(user_id='u_42')
    rahm.log.info('greeting', 'saying hello')
    return PlainTextResponse('hello')


async def _boom(request):
    raise RuntimeError('database connection lost')


@pytest.fixture
def client(capture_logs):
    app = Starlette(
        routes=[Route('/', _hello), Route('/boom', _boom)],
        middleware=[Middleware(RahmHttpMiddleware)],
    )
    # Starlette converts dispatch-raised exceptions into a 500 by default; we
    # want to assert on what the middleware logs, then drop the raised error.
    return TestClient(app, raise_server_exceptions=False)


def _logs(buf):
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def test_success_emits_access_log(capture_logs, client):
    response = client.get('/')
    assert response.status_code == 200
    logs = _logs(capture_logs)
    access = [log for log in logs if log['event'] == 'http_request_completed']
    assert len(access) == 1
    assert access[0]['http_method'] == 'GET'
    assert access[0]['http_path'] == '/'
    assert access[0]['http_status'] == 200
    assert 'http_duration_ms' in access[0]


def test_scope_fields_propagate_to_handler_logs(capture_logs, client):
    client.get('/')
    logs = _logs(capture_logs)
    greeting = [log for log in logs if log['event'] == 'greeting']
    assert len(greeting) == 1
    assert greeting[0]['http_method'] == 'GET'
    assert greeting[0]['http_path'] == '/'
    assert greeting[0]['user_id'] == 'u_42'  # bound inside the handler
    assert 'trace_id' in greeting[0]


def test_trace_id_echoed_in_response_header(capture_logs, client):
    response = client.get('/', headers={'X-Trace-Id': 'demo-trace-001'})
    assert response.headers['x-trace-id'] == 'demo-trace-001'
    logs = _logs(capture_logs)
    access = [log for log in logs if log['event'] == 'http_request_completed'][0]
    assert access['trace_id'] == 'demo-trace-001'


def test_generated_trace_id_when_no_header(capture_logs, client):
    response = client.get('/')
    assert 'x-trace-id' in response.headers
    logs = _logs(capture_logs)
    access = [log for log in logs if log['event'] == 'http_request_completed'][0]
    assert access['trace_id'] == response.headers['x-trace-id']


def test_uncaught_exception_logs_error_and_returns_500(capture_logs, client):
    response = client.get('/boom?user=42')
    assert response.status_code == 500
    logs = _logs(capture_logs)
    errors = [log for log in logs if log['event'] == 'uncaught_exception']
    assert len(errors) == 1
    err = errors[0]
    assert err['severity'] == 'error'
    assert err['error_type'] == 'RuntimeError'
    assert err['error_message'] == 'database connection lost'
    assert err['http_status'] == 500
    assert err['http_method'] == 'GET'
    assert err['http_path'] == '/boom'
    assert 'http_client' in err
    assert 'http_headers' in err
    assert 'http_query_params' in err
    assert 'http_body' in err


def test_scope_does_not_leak_between_requests(capture_logs, client):
    client.get('/')
    client.get('/')
    logs = _logs(capture_logs)
    accesses = [log for log in logs if log['event'] == 'http_request_completed']
    assert len(accesses) == 2
    assert accesses[0]['trace_id'] != accesses[1]['trace_id']


def test_request_body_included_on_exception(capture_logs):
    """Handler raises *without* consuming the body, so the middleware can
    still read it to populate http_body."""
    async def post_boom(request):
        raise RuntimeError('post died')

    app = Starlette(
        routes=[Route('/post-boom', post_boom, methods=['POST'])],
        middleware=[Middleware(RahmHttpMiddleware)],
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.post('/post-boom', content='{"hello":"world"}')

    logs = _logs(capture_logs)
    err = [log for log in logs if log['event'] == 'uncaught_exception'][0]
    assert err['http_body'] == '{"hello":"world"}'


def test_consumed_body_then_raise_does_not_crash_middleware(capture_logs):
    """Handler reads request.body() then raises. Middleware's own body re-read
    fails, but it must still log the exception (with http_body=<unavailable>)."""
    async def post_boom(request):
        await request.body()
        raise RuntimeError('post died after reading body')

    app = Starlette(
        routes=[Route('/post-boom', post_boom, methods=['POST'])],
        middleware=[Middleware(RahmHttpMiddleware)],
    )
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post('/post-boom', content='{"hello":"world"}')
    assert response.status_code == 500

    logs = _logs(capture_logs)
    err = [log for log in logs if log['event'] == 'uncaught_exception'][0]
    assert err['error_type'] == 'RuntimeError'
    assert err['http_body'] == '<unavailable>'


def test_binary_body_does_not_crash_middleware(capture_logs):
    """Non-UTF-8 body must not itself crash the middleware while it tries to
    log the original exception."""
    async def post_boom(request):
        raise RuntimeError('boom')

    app = Starlette(
        routes=[Route('/post', post_boom, methods=['POST'])],
        middleware=[Middleware(RahmHttpMiddleware)],
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.post('/post', content=b'\xff\xfe\xfd binary garbage')

    logs = _logs(capture_logs)
    err = [log for log in logs if log['event'] == 'uncaught_exception'][0]
    assert 'binary' in err['http_body'].lower()
