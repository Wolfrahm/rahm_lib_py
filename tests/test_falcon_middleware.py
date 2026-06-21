"""RahmFalconMiddleware + rahm_error_handler via falcon.testing.TestClient.

Mirrors test_http_middleware.py one-to-one: each scenario the Starlette
middleware covers should hold for Falcon too. We run against the WSGI
variant (`falcon.App`); the ASGI variant shares all the same code paths.
"""
import json

import falcon
import pytest
from falcon import testing

import rahm
from rahm.falcon import RahmFalconMiddleware, rahm_error_handler


class _Hello:
    def on_get(self, req, resp):
        rahm.log.bind(user_id='u_42')
        rahm.log.info('greeting', 'saying hello')
        resp.text = 'hello'


class _Boom:
    def on_get(self, req, resp):
        raise RuntimeError('database connection lost')


@pytest.fixture
def client(capture_logs):
    app = falcon.App(middleware=[RahmFalconMiddleware()])
    app.add_error_handler(Exception, rahm_error_handler)
    app.add_route('/', _Hello())
    app.add_route('/boom', _Boom())
    return testing.TestClient(app)


def _logs(buf):
    return [json.loads(line) for line in buf.getvalue().splitlines() if line.strip()]


def test_success_emits_access_log(capture_logs, client):
    response = client.simulate_get('/')
    assert response.status_code == 200
    logs = _logs(capture_logs)
    access = [log for log in logs if log['event'] == 'http_request_completed']
    assert len(access) == 1
    assert access[0]['http_method'] == 'GET'
    assert access[0]['http_path'] == '/'
    assert access[0]['http_status'] == 200
    assert 'http_duration_ms' in access[0]


def test_scope_fields_propagate_to_handler_logs(capture_logs, client):
    client.simulate_get('/')
    logs = _logs(capture_logs)
    greeting = [log for log in logs if log['event'] == 'greeting']
    assert len(greeting) == 1
    assert greeting[0]['http_method'] == 'GET'
    assert greeting[0]['http_path'] == '/'
    assert greeting[0]['user_id'] == 'u_42'
    assert 'trace_id' in greeting[0]


def test_trace_id_echoed_in_response_header(capture_logs, client):
    response = client.simulate_get('/', headers={'X-Trace-Id': 'demo-trace-001'})
    assert response.headers['x-trace-id'] == 'demo-trace-001'
    logs = _logs(capture_logs)
    access = [log for log in logs if log['event'] == 'http_request_completed'][0]
    assert access['trace_id'] == 'demo-trace-001'


def test_generated_trace_id_when_no_header(capture_logs, client):
    response = client.simulate_get('/')
    assert 'x-trace-id' in response.headers
    logs = _logs(capture_logs)
    access = [log for log in logs if log['event'] == 'http_request_completed'][0]
    assert access['trace_id'] == response.headers['x-trace-id']


def test_uncaught_exception_logs_error_and_returns_500(capture_logs, client):
    response = client.simulate_get('/boom', query_string='user=42')
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
    # one entry per failed request — no duplicate http_request_completed
    assert [log for log in logs if log['event'] == 'http_request_completed'] == []


def test_scope_does_not_leak_between_requests(capture_logs, client):
    client.simulate_get('/')
    client.simulate_get('/')
    logs = _logs(capture_logs)
    accesses = [log for log in logs if log['event'] == 'http_request_completed']
    assert len(accesses) == 2
    assert accesses[0]['trace_id'] != accesses[1]['trace_id']


def test_request_body_included_on_exception(capture_logs):
    """Handler raises without consuming the body, so the error handler can
    still read it to populate http_body."""

    class _PostBoom:
        def on_post(self, req, resp):
            raise RuntimeError('post died')

    app = falcon.App(middleware=[RahmFalconMiddleware()])
    app.add_error_handler(Exception, rahm_error_handler)
    app.add_route('/post-boom', _PostBoom())
    client = testing.TestClient(app)
    client.simulate_post('/post-boom', body='{"hello":"world"}')

    logs = _logs(capture_logs)
    err = [log for log in logs if log['event'] == 'uncaught_exception'][0]
    assert err['http_body'] == '{"hello":"world"}'


def test_consumed_body_then_raise_does_not_crash_middleware(capture_logs):
    """Handler reads the body then raises. Middleware/error_handler's own
    body re-read fails, but logging still succeeds with http_body=''."""

    class _PostBoom:
        def on_post(self, req, resp):
            req.bounded_stream.read()
            raise RuntimeError('post died after reading body')

    app = falcon.App(middleware=[RahmFalconMiddleware()])
    app.add_error_handler(Exception, rahm_error_handler)
    app.add_route('/post-boom', _PostBoom())
    client = testing.TestClient(app)
    response = client.simulate_post('/post-boom', body='{"hello":"world"}')
    assert response.status_code == 500

    logs = _logs(capture_logs)
    err = [log for log in logs if log['event'] == 'uncaught_exception'][0]
    assert err['error_type'] == 'RuntimeError'
    # body was already consumed by the handler; re-read yields an empty buffer
    assert err['http_body'] in ('', '<unavailable>')


def test_binary_body_does_not_crash_middleware(capture_logs):
    """Non-UTF-8 body must not crash logging."""

    class _PostBoom:
        def on_post(self, req, resp):
            raise RuntimeError('boom')

    app = falcon.App(middleware=[RahmFalconMiddleware()])
    app.add_error_handler(Exception, rahm_error_handler)
    app.add_route('/post', _PostBoom())
    client = testing.TestClient(app)
    client.simulate_post('/post', body=b'\xff\xfe\xfd binary garbage')

    logs = _logs(capture_logs)
    err = [log for log in logs if log['event'] == 'uncaught_exception'][0]
    assert 'binary' in err['http_body'].lower()


def test_http_error_still_logs_access(capture_logs, client):
    """Falcon's built-in HTTPNotFound handler renders the 404 — middleware
    should still emit an http_request_completed entry, not uncaught_exception."""
    response = client.simulate_get('/missing')
    assert response.status_code == 404
    logs = _logs(capture_logs)
    events = [log['event'] for log in logs]
    assert 'http_request_completed' in events
    assert 'uncaught_exception' not in events
    access = [log for log in logs if log['event'] == 'http_request_completed'][0]
    assert access['http_status'] == 404
