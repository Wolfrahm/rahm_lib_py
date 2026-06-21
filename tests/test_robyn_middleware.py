"""rahm_before_request / rahm_after_request / rahm_exception_handler via robyn.testing.TestClient.

Robyn's TestClient runs after_request middleware only when the handler returns
a `robyn.Response` object — plain string returns short-circuit. All test
handlers therefore return Response explicitly.
"""
import json

import pytest
import robyn
from robyn.testing import TestClient

import rahm
from rahm.robyn import install_rahm


def _ok(body='hello'):
    return robyn.Response(status_code=200, description=body, headers={})


@pytest.fixture
def client(capture_logs):
    app = robyn.Robyn(__file__)
    install_rahm(app)

    @app.get('/')
    def hello(request):
        rahm.log.bind(user_id='u_42')
        rahm.log.info('greeting', 'saying hello')
        return _ok()

    @app.get('/boom')
    def boom(request):
        raise RuntimeError('database connection lost')

    @app.post('/echo')
    def echo(request):
        return _ok('echo')

    @app.post('/post-boom')
    def post_boom(request):
        raise RuntimeError('post died')

    return TestClient(app)


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
    assert greeting[0]['user_id'] == 'u_42'
    assert 'trace_id' in greeting[0]


def test_trace_id_echoed_in_response_header(capture_logs, client):
    response = client.get('/', headers={'X-Trace-Id': 'demo-trace-001'})
    assert response.headers.get('X-Trace-Id') == 'demo-trace-001'
    logs = _logs(capture_logs)
    access = [log for log in logs if log['event'] == 'http_request_completed'][0]
    assert access['trace_id'] == 'demo-trace-001'


def test_generated_trace_id_when_no_header(capture_logs, client):
    response = client.get('/')
    assert response.headers.get('X-Trace-Id') is not None
    logs = _logs(capture_logs)
    access = [log for log in logs if log['event'] == 'http_request_completed'][0]
    assert access['trace_id'] == response.headers.get('X-Trace-Id')


def test_uncaught_exception_logs_error_and_returns_500(capture_logs, client):
    response = client.get('/boom')
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
    # exactly one entry per failed request — no duplicate http_request_completed
    assert [log for log in logs if log['event'] == 'http_request_completed'] == []


def test_scope_does_not_leak_between_requests(capture_logs, client):
    client.get('/')
    client.get('/')
    logs = _logs(capture_logs)
    accesses = [log for log in logs if log['event'] == 'http_request_completed']
    assert len(accesses) == 2
    assert accesses[0]['trace_id'] != accesses[1]['trace_id']


def test_request_body_included_on_exception(capture_logs, client):
    """Body is captured into http_body when the handler raises."""
    client.post('/post-boom', body='{"hello":"world"}')
    logs = _logs(capture_logs)
    err = [log for log in logs if log['event'] == 'uncaught_exception'][0]
    assert err['http_body'] == '{"hello":"world"}'


def test_no_scope_leak_after_uncaught(capture_logs, client):
    """A failed request must not leave trace_id / user_id stuck in the next request's scope."""
    client.get('/boom')
    client.get('/')
    logs = _logs(capture_logs)
    greetings = [log for log in logs if log['event'] == 'greeting']
    errors = [log for log in logs if log['event'] == 'uncaught_exception']
    assert len(errors) == 1
    assert len(greetings) == 1
    # the greeting's trace_id must be the new one, not the boom's
    assert greetings[0]['trace_id'] != errors[0]['trace_id']
    assert greetings[0]['user_id'] == 'u_42'
