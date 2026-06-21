import logging
import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
import rahm
from rahm._common import ulid as _ulid, parse_trace_id_setting
from rahm.log import LocalFormatter, JsonFormatter, LogfmtFormatter

_TRACE_ID_ENABLED = parse_trace_id_setting()


# uvicorn emits records as a template msg + args tuple. expand them into the
# final string so the standard rahm formatter (which reads record.msg directly)
# doesn't need to know about %-substitution. also drop uvicorn's ANSI-colored
# duplicate of the message — pure noise once we have our own colored output.
class UvicornNormalizer(logging.Filter):

    def filter(self, record):
        record.msg = record.getMessage()
        record.args = ()
        record.__dict__.pop('color_message', None)
        # uvicorn's own startup/shutdown lines don't know about rahm's event convention;
        # tag them so they don't emit event=None and violate the mandatory-field rule.
        record.event = 'uvicorn'
        return True


# pass class objects, not dotted strings: dictConfig resolves 'rahm.log.X' via
# getattr(rahm, 'log'), and rahm/__init__.py rebinds rahm.log to the Logger
# instance — so attribute lookup on the class would fail at uvicorn boot.
def uvicorn_log_config():
    formatter = {
        'text': LocalFormatter,
        'logfmt': LogfmtFormatter,
    }.get(os.environ.get('RAHM_LOG_FORMAT', 'json').lower(), JsonFormatter)
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {'rahm': {'()': formatter}},
        'filters': {'uvicorn_normalizer': {'()': UvicornNormalizer}},
        'handlers': {
            'rahm': {
                'class': 'logging.StreamHandler',
                'formatter': 'rahm',
                'filters': ['uvicorn_normalizer'],
            },
        },
        'loggers': {
            'uvicorn': {'handlers': ['rahm'], 'level': 'INFO', 'propagate': False},
            'uvicorn.access': {'handlers': ['rahm'], 'level': 'INFO', 'propagate': False},
        },
    }


# Opens a rahm scope at request entry (trace_id + http_method + http_path),
# emits http_request_completed on success, and turns uncaught exceptions into
# an ERROR entry plus a JSON 500. When installed, pass access_log=False to
# uvicorn.Config so uvicorn's own access logger doesn't duplicate this entry.
class RahmHttpMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        scope_fields = {
            'http_method': request.method,
            'http_path': request.url.path,
        }
        trace_id = None
        if _TRACE_ID_ENABLED:
            trace_id = request.headers.get('x-trace-id') or _ulid()
            scope_fields['trace_id'] = trace_id
        start = time.monotonic()
        with rahm.log.scope(**scope_fields):
            try:
                response = await call_next(request)
            except Exception as exc:
                duration_ms = round((time.monotonic() - start) * 1000, 3)
                ctx = await self._request_context(request)
                rahm.log.error(
                    'uncaught_exception',
                    f'Uncaught exception - {exc}',
                    exc_info=True,
                    http_status=500,
                    http_duration_ms=duration_ms,
                    **ctx,
                )
                return JSONResponse(status_code=500, content='internal server error')

            duration_ms = round((time.monotonic() - start) * 1000, 3)
            rahm.log.info(
                'http_request_completed',
                f'{request.method} {request.url.path} {response.status_code}',
                http_status=response.status_code,
                http_duration_ms=duration_ms,
            )
            if _TRACE_ID_ENABLED:
                response.headers['x-trace-id'] = trace_id
            return response


    async def _request_context(self, request):
        # headers — cookies get name/value broken out for readability
        headers = ''
        for header in request.headers.raw:
            if header[0].decode('utf-8') == 'cookie':
                cookies = header[1].decode('utf-8').split(';')
                cookies = [s.strip() for s in cookies]
                headers = 'cookie: \n'
                for cookie in cookies:
                    # partition (not split) so '=' inside the value stays in the value
                    name, _, value = cookie.partition('=')
                    headers += '  name: ' + name + '\n'
                    headers += '  value: ' + value + '\n'
            else:
                headers += header[0].decode('utf-8') + ': ' + header[1].decode('utf-8') + '\n'
        headers = headers[:-1]

        # query params
        query_params = ''
        if str(request.query_params) != '':
            params = str(request.query_params).split('&')
            for param in params:
                param = param.split('=')
                query_params += param[0] + ': ' + param[1] + '\n'
            query_params = query_params[:-1]

        # body — two failure modes the middleware must survive:
        # 1. handler already consumed the body before raising → re-reading
        #    raises because the ASGI receive stream is empty.
        # 2. binary uploads (file POSTs etc.) aren't UTF-8 decodable.
        # Both fall back to placeholders so logging the original exception
        # can't itself crash.
        try:
            body = await request.body()
        except Exception:
            req_body = '<unavailable>'
        else:
            try:
                req_body = body.decode('utf-8')
            except UnicodeDecodeError:
                req_body = f'<binary {len(body)} bytes>'

        return {
            'http_client': request.client.host,
            'http_headers': headers,
            'http_query_params': query_params,
            'http_body': req_body,
        }
