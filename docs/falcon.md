# Falcon integration

`rahm.falcon` plugs rahm logging into a Falcon app (WSGI or ASGI): one middleware on the app, one error handler registered on `Exception`. Familiarity with [docs/logging.md](logging.md) is assumed — this page only covers the HTTP wiring.

## Install

```sh
uv sync --extra falcon
```

Pulls in `falcon` and `granian` (the production server) alongside `rahm`.

## What you get

Per request:

- **Scope opened**: `trace_id` (from `X-Trace-Id` or a generated lowercase ULID), `http_method`, `http_path`. Every log line your responder emits inside the request inherits those fields.
- **On success**: one `http_request_completed` access entry with `http_status` + `http_duration_ms`. The `X-Trace-Id` header is echoed in the response.
- **On `falcon.HTTPError` / `falcon.HTTPStatus`** (e.g. 404, 401): Falcon's built-in handlers render the response; the middleware still emits one `http_request_completed` access entry with the correct status. Our generic `Exception` handler is *not* invoked — Falcon dispatches to the most specific registered handler.
- **On uncaught Python exception**: one ERROR entry with `event=uncaught_exception`, the full stack, `http_status=500`, request context (`http_client`, `http_headers`, `http_query_params`, `http_body`), and a JSON 500 response. The access log is suppressed so each failed request produces exactly one entry.

## Wiring — WSGI

```python
import falcon
from rahm.falcon import RahmFalconMiddleware, rahm_error_handler

app = falcon.App(middleware=[RahmFalconMiddleware()])
app.add_error_handler(Exception, rahm_error_handler)
```

## Wiring — ASGI

```python
import falcon.asgi
from rahm.falcon import RahmFalconAsyncMiddleware, rahm_error_handler_async

app = falcon.asgi.App(middleware=[RahmFalconAsyncMiddleware()])
app.add_error_handler(Exception, rahm_error_handler_async)
```

The two halves compose: register only the middleware if you want to keep your own exception-handling logic; the per-request scope and access log still work.

## API

### `RahmFalconMiddleware()` / `RahmFalconAsyncMiddleware()`

Falcon middleware classes (sync / async). Open the scope in `process_request`, emit the access log in `process_response`, close the scope on the way out. Skipped when our error handler already logged.

### `rahm_error_handler(req, resp, ex, params)` / `rahm_error_handler_async(req, resp, ex, params)`

Falcon error handlers. Register against `Exception`. They log `uncaught_exception` with request context + render a JSON 500. Because Falcon's built-in handlers for `HTTPError` / `HTTPStatus` are more specific, this handler is only invoked for genuinely-uncaught Python exceptions.

## Environment variables

| Variable             | Effect                                                                                       |
|----------------------|----------------------------------------------------------------------------------------------|
| `RAHM_LOG_TRACE_ID`  | `disabled` suppresses trace_id binding and the `X-Trace-Id` response-header echo.            |

All the env vars from [docs/logging.md](logging.md#configuration) still apply.

## Demo

```sh
uv run --env-file .env python -m demo.log_falcon
```

The script (`demo/log_falcon.py`) serves a real Falcon WSGI app on **Granian** — the same server used in production, so the demo exercises the rahm integration (and its error handling) on the real runtime. Granian is multi-process: it spawns worker processes that import the `demo.log_falcon:app` target, so the request-firing block is guarded by `if __name__ == '__main__'`. The server runs on the main thread while a background thread fires baseline / supplied-trace-id / 404 / uncaught-exception requests, then trips Granian's interrupt for a clean shutdown.

## See also

- [docs/logging.md](logging.md) — core logging concepts the middleware builds on.
- [docs/starlette.md](starlette.md) — same surface for Starlette.
- [docs/robyn.md](robyn.md) — same surface for Robyn.
