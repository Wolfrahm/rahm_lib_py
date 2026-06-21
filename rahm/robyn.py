"""Robyn framework integration.

Three handlers wire up to a Robyn app:

  * ``rahm_before_request`` — opens a rahm scope binding ``trace_id``,
    ``http_method``, ``http_path``; stashes the request on a contextvar so
    the exception handler can read it later.
  * ``rahm_after_request`` — emits the ``http_request_completed`` access entry
    and clears per-request state.
  * ``rahm_exception_handler`` — turns uncaught Python exceptions into an
    ERROR entry with full request context + a JSON 500 response.

Robyn's ``@app.exception`` handler is called with only the exception (no
request, no response), so per-request state lives on contextvars set in
``rahm_before_request`` and read by both the access-log emitter and the
exception handler.

Wiring:

    import robyn
    from rahm.robyn import install_rahm

    app = robyn.Robyn(__file__)
    install_rahm(app)

Or step-by-step:

    app.before_request()(rahm_before_request)
    app.after_request()(rahm_after_request)
    app.exception(rahm_exception_handler)
"""
import contextvars
import logging
import os
import sys
import time

import robyn
import rahm

from rahm._common import ulid as _ulid, parse_trace_id_setting
from rahm.log import _scope_var, LocalFormatter, JsonFormatter, LogfmtFormatter

_TRACE_ID_ENABLED = parse_trace_id_setting()


# Tag records emitted by Robyn / actix loggers so they satisfy rahm's mandatory
# `event` field. Strip color escapes the upstream loggers emit (rahm formatters
# colorize their own output).
_ANSI_RE = None  # lazy-compile inside the filter; small import-time win
class RobynNormalizer(logging.Filter):

    def filter(self, record):
        global _ANSI_RE
        if _ANSI_RE is None:
            import re
            _ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')
        record.msg = _ANSI_RE.sub('', record.getMessage())
        record.args = ()
        record.event = 'robyn' if record.name.startswith('robyn') else 'actix'
        return True


def _pick_formatter():
    return {
        'text': LocalFormatter,
        'logfmt': LogfmtFormatter,
    }.get(os.environ.get('RAHM_LOG_FORMAT', 'json').lower(), JsonFormatter)()


# Loggers Robyn (and its underlying actix runtime) create at import / startup.
# We attach our handler to each top-level so descendants (robyn.router,
# actix_server.builder, …) propagate up and get formatted by us; then we set
# propagate=False so records don't continue up to the root's lastResort handler.
_ROBYN_LOGGERS = ('robyn', 'actix_server', 'actix_web')

_INSTALLED_MARK = '_rahm_robyn_installed'


def setup_logging():
    """Route Robyn / actix logger output through rahm's formatter.

    Call this once before constructing the Robyn app. Idempotent — calling
    it again is a no-op. `install_rahm(app)` calls it too, but lines emitted
    during ``robyn.Robyn(__file__)`` and route registration fire before
    ``install_rahm`` runs, so call ``setup_logging()`` at import time if you
    want those captured.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_pick_formatter())
    handler.addFilter(RobynNormalizer())
    setattr(handler, _INSTALLED_MARK, True)
    for name in _ROBYN_LOGGERS:
        logger = logging.getLogger(name)
        # purge prior rahm handlers in case setup_logging was called before
        # with a different RAHM_LOG_FORMAT, then re-attach with current config.
        logger.handlers[:] = [h for h in logger.handlers if not getattr(h, _INSTALLED_MARK, False)]
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


# Per-request state shared between the three handlers. Robyn's exception
# handler signature is `(err)` — no request — so we stash what we need here.
_request_var = contextvars.ContextVar('rahm_robyn_request', default=None)
_start_var = contextvars.ContextVar('rahm_robyn_start', default=None)
_trace_id_var = contextvars.ContextVar('rahm_robyn_trace_id', default=None)
_skip_access_var = contextvars.ContextVar('rahm_robyn_skip_access', default=False)


def _open_scope(request):
    fields = {
        'http_method': request.method,
        'http_path': request.url.path,
    }
    trace_id = None
    if _TRACE_ID_ENABLED:
        trace_id = request.headers.get('X-Trace-Id') or _ulid()
        fields['trace_id'] = trace_id
    _scope_var.set(dict(fields))
    _request_var.set(request)
    _start_var.set(time.monotonic())
    _trace_id_var.set(trace_id)
    _skip_access_var.set(False)


def _close_scope():
    _scope_var.set(None)
    _request_var.set(None)
    _start_var.set(None)
    _trace_id_var.set(None)
    _skip_access_var.set(False)


def _emit_access(request, response):
    start = _start_var.get() or time.monotonic()
    duration_ms = round((time.monotonic() - start) * 1000, 3)
    status = getattr(response, 'status_code', 200)
    rahm.log.info(
        'http_request_completed',
        f'{request.method} {request.url.path} {status}',
        http_status=status,
        http_duration_ms=duration_ms,
    )


def _echo_trace_id(response):
    trace_id = _trace_id_var.get()
    if _TRACE_ID_ENABLED and trace_id and hasattr(response, 'headers'):
        try:
            response.headers.set('X-Trace-Id', trace_id)
        except Exception:
            pass


# --- request context for error logging ---

def _headers_block(request):
    out = ''
    for k, values in request.headers.get_headers().items():
        v = ', '.join(values) if isinstance(values, list) else values
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


def _query_block(request):
    qp = request.query_params.to_dict()
    if not qp:
        return ''
    out = ''
    for k, values in qp.items():
        v = values[0] if isinstance(values, list) else values
        out += k + ': ' + str(v) + '\n'
    return out.rstrip('\n')


def _decode_body(body):
    if not body:
        return ''
    if isinstance(body, str):
        return body
    try:
        return body.decode('utf-8')
    except UnicodeDecodeError:
        return f'<binary {len(body)} bytes>'


def _request_context(request):
    return {
        'http_client': request.ip_addr or '',
        'http_headers': _headers_block(request),
        'http_query_params': _query_block(request),
        'http_body': _decode_body(request.body),
    }


# --- middleware + exception handlers ---

def rahm_before_request(request):
    _open_scope(request)
    return request


def rahm_after_request(request, response):
    try:
        if not _skip_access_var.get():
            _emit_access(request, response)
        _echo_trace_id(response)
    finally:
        _close_scope()
    return response


def rahm_exception_handler(err):
    request = _request_var.get()
    start = _start_var.get()
    duration_ms = round((time.monotonic() - start) * 1000, 3) if start else 0.0
    ctx = _request_context(request) if request is not None else {}
    _skip_access_var.set(True)
    rahm.log.error(
        'uncaught_exception',
        f'Uncaught exception - {err}',
        exc_info=(type(err), err, err.__traceback__),
        http_status=500,
        http_duration_ms=duration_ms,
        **ctx,
    )
    return robyn.Response(
        status_code=500,
        description='"internal server error"',
        headers={'Content-Type': 'application/json'},
    )


def install_rahm(app):
    """Register all three handlers on the given Robyn app and route Robyn /
    actix logger output through rahm's formatter."""
    setup_logging()
    app.before_request()(rahm_before_request)
    app.after_request()(rahm_after_request)
    app.exception(rahm_exception_handler)
    return app
