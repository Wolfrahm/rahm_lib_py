# Starlette integration

`rahm.starlette` plugs rahm logging into a Starlette app served by uvicorn: one middleware on the app, one logging-config call on uvicorn. Familiarity with [docs/logging.md](logging.md) is assumed — this page only covers the HTTP wiring.

## Install

```sh
uv sync --extra starlette
```

Pulls in `starlette` and `uvicorn` alongside `rahm`.

## What you get

Per request:

- **Scope opened**: `trace_id` (from the `X-Trace-Id` header or a generated lowercase ULID), `http_method`, `http_path`. Every log line your handler emits inside the request inherits those fields.
- **On success**: one `http_request_completed` access entry with `http_status` + `http_duration_ms`. The `X-Trace-Id` header is echoed in the response.
- **On uncaught exception**: one ERROR entry with `event=uncaught_exception`, the full stack, `http_status=500`, request context (`http_client`, `http_headers`, `http_query_params`, `http_body`), and a JSON 500 response to the client.
- **Uvicorn's startup/shutdown lines** flow through rahm's formatter tagged `event=uvicorn` (via `uvicorn_log_config()`).

## Wiring

```python
import rahm
from rahm.starlette import uvicorn_log_config, RahmHttpMiddleware

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import Route

app = Starlette(
    routes=[...],
    middleware=[Middleware(RahmHttpMiddleware)],
)

uvicorn.Config(
    app,
    host='0.0.0.0',
    port=8000,
    log_config=uvicorn_log_config(),
    access_log=False,           # the middleware emits its own access log
).run()
```

Order of imports is irrelevant — `import rahm` can happen before or after uvicorn.

## API

### `RahmHttpMiddleware`

A standard Starlette middleware. Install it via `Middleware(RahmHttpMiddleware)` in the `middleware=[…]` list on `Starlette(...)`. Takes no arguments.

### `uvicorn_log_config() -> dict`

Returns a `logging.config.dictConfig`-shaped dict that wires uvicorn's `uvicorn` and `uvicorn.access` loggers into rahm's formatter (driven by `RAHM_LOG_FORMAT`). Hand it to `uvicorn.Config(log_config=...)`.

Pair with `access_log=False` — the middleware already emits one `http_request_completed` entry per request, and uvicorn's built-in access log would duplicate it.

## Environment variables

| Variable             | Effect                                                                                       |
|----------------------|----------------------------------------------------------------------------------------------|
| `RAHM_LOG_FORMAT`    | Selects the formatter used for both your logs and uvicorn's pass-through lines.              |
| `RAHM_LOG_TRACE_ID`  | `disabled` suppresses trace_id binding and the `X-Trace-Id` response-header echo.            |

All the env vars from [docs/logging.md](logging.md#configuration) still apply.

## Demo

```sh
uv run --env-file .env python -m demo.log_starlette
```

The script (`demo/log_starlette.py`) boots a real uvicorn + Starlette app on a background thread, fires baseline / supplied-trace-id / 404 / uncaught-exception requests, and exits cleanly.

## See also

- [docs/logging.md](logging.md) — core logging concepts the middleware builds on.
- [docs/falcon.md](falcon.md) — same surface for Falcon.
- [docs/robyn.md](robyn.md) — same surface for Robyn.
