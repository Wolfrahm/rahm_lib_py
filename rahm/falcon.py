"""Falcon framework integration.

`RahmFalconMiddleware` (WSGI) and `RahmFalconAsyncMiddleware` (ASGI) open a
rahm scope per request — binding `trace_id`, `http_method`, `http_path` — and
emit an `http_request_completed` access entry on the way out.

`rahm_error_handler` / `rahm_error_handler_async` registered against
`Exception` turn truly uncaught Python exceptions into an ERROR entry (full
stack + request context) plus a JSON 500. Falcon's built-in handlers for
`HTTPError` and `HTTPStatus` are more specific, so they keep handling 4xx/3xx
without going through this handler.

Wiring (WSGI):

    import falcon
    from rahm.falcon import RahmFalconMiddleware, rahm_error_handler

    app = falcon.App(middleware=[RahmFalconMiddleware()])
    app.add_error_handler(Exception, rahm_error_handler)

Wiring (ASGI):

    import falcon.asgi
    from rahm.falcon import RahmFalconAsyncMiddleware, rahm_error_handler_async

    app = falcon.asgi.App(middleware=[RahmFalconAsyncMiddleware()])
    app.add_error_handler(Exception, rahm_error_handler_async)
"""
import time

import falcon
import rahm

from rahm._common import ulid as _ulid, parse_trace_id_setting

_TRACE_ID_ENABLED = parse_trace_id_setting()


# --- per-request scope: opened in process_request, closed in process_response ---

def _open_scope(req):
    fields = {
        'http_method': req.method,
        'http_path': req.path,
    }
    trace_id = None
    if _TRACE_ID_ENABLED:
        trace_id = req.get_header('X-Trace-Id') or _ulid()
        fields['trace_id'] = trace_id
    scope_cm = rahm.log.scope(**fields)
    scope_cm.__enter__()
    req.context.rahm_scope = scope_cm
    req.context.rahm_trace_id = trace_id
    req.context.rahm_start = time.monotonic()
    req.context.rahm_skip_access = False


def _close_scope(req):
    req.context.rahm_scope.__exit__(None, None, None)


def _status_code(resp):
    status = resp.status
    if isinstance(status, int):
        return status
    return int(str(status).split(' ', 1)[0])


def _emit_access(req, resp):
    duration_ms = round((time.monotonic() - req.context.rahm_start) * 1000, 3)
    status = _status_code(resp)
    rahm.log.info(
        'http_request_completed',
        f'{req.method} {req.path} {status}',
        http_status=status,
        http_duration_ms=duration_ms,
    )


def _finalize_response(req, resp):
    try:
        if not req.context.rahm_skip_access:
            _emit_access(req, resp)
        if _TRACE_ID_ENABLED and req.context.rahm_trace_id:
            resp.set_header('X-Trace-Id', req.context.rahm_trace_id)
    finally:
        _close_scope(req)


# --- request context for error logging ---

def _headers_block(req):
    out = ''
    for k, v in req.headers.items():
        name = k.lower()
        if name == 'cookie':
            out += 'cookie: \n'
            for cookie in [s.strip() for s in v.split(';')]:
                cname, _, cvalue = cookie.partition('=')
                out += '  name: ' + cname + '\n'
                out += '  value: ' + cvalue + '\n'
        else:
            out += name + ': ' + v + '\n'
    return out.rstrip('\n')


def _query_block(req):
    query = req.query_string or ''
    if not query:
        return ''
    out = ''
    for param in query.split('&'):
        k, _, v = param.partition('=')
        out += k + ': ' + v + '\n'
    return out.rstrip('\n')


def _client(req):
    return req.remote_addr or ''


def _decode_body(body):
    if not body:
        return ''
    try:
        return body.decode('utf-8')
    except UnicodeDecodeError:
        return f'<binary {len(body)} bytes>'


def _wsgi_body(req):
    try:
        body = req.bounded_stream.read()
    except Exception:
        return '<unavailable>'
    return _decode_body(body)


async def _asgi_body(req):
    try:
        body = await req.stream.read()
    except Exception:
        return '<unavailable>'
    return _decode_body(body)


def _wsgi_request_context(req):
    return {
        'http_client': _client(req),
        'http_headers': _headers_block(req),
        'http_query_params': _query_block(req),
        'http_body': _wsgi_body(req),
    }


async def _asgi_request_context(req):
    return {
        'http_client': _client(req),
        'http_headers': _headers_block(req),
        'http_query_params': _query_block(req),
        'http_body': await _asgi_body(req),
    }


# --- middlewares ---

class RahmFalconMiddleware:
    """WSGI: opens a per-request scope and emits the access log on the way out."""

    def process_request(self, req, resp):
        _open_scope(req)

    def process_response(self, req, resp, resource, req_succeeded):
        _finalize_response(req, resp)


class RahmFalconAsyncMiddleware:
    """ASGI counterpart of RahmFalconMiddleware."""

    async def process_request(self, req, resp):
        _open_scope(req)

    async def process_response(self, req, resp, resource, req_succeeded):
        _finalize_response(req, resp)


# --- error handlers ---

# Falcon registers default handlers for HTTPError/HTTPStatus that are more
# specific than Exception, so this only catches true uncaught Python errors.
# We log the error and signal the middleware to skip its own access log so
# each failed request produces exactly one entry, matching the Starlette story.
def _log_uncaught(req, ex, ctx):
    duration_ms = round((time.monotonic() - req.context.rahm_start) * 1000, 3)
    req.context.rahm_skip_access = True
    rahm.log.error(
        'uncaught_exception',
        f'Uncaught exception - {ex}',
        exc_info=(type(ex), ex, ex.__traceback__),
        http_status=500,
        http_duration_ms=duration_ms,
        **ctx,
    )


def _render_500(resp):
    resp.status = falcon.HTTP_500
    resp.content_type = falcon.MEDIA_JSON
    resp.text = '"internal server error"'


def rahm_error_handler(req, resp, ex, params):
    _log_uncaught(req, ex, _wsgi_request_context(req))
    _render_500(resp)


async def rahm_error_handler_async(req, resp, ex, params):
    _log_uncaught(req, ex, await _asgi_request_context(req))
    _render_500(resp)
