# Robyn integration

`rahm.robyn` plugs rahm logging into a [Robyn](https://robyn.tech/) app: three hook functions (`before_request`, `after_request`, `exception`) registered via a one-call `install_rahm(app)`, plus an optional `setup_logging()` to route Robyn's own startup chatter through rahm's formatter. Familiarity with [docs/logging.md](logging.md) is assumed — this page only covers the HTTP wiring.

## Install

```sh
uv sync --extra robyn
```

Pulls in `robyn` alongside `rahm`.

## What you get

Per request:

- **Scope opened** in `before_request`: `trace_id` (from `X-Trace-Id` or a generated lowercase ULID), `http_method`, `http_path`. The active request is also stashed on a contextvar so the exception handler can read it.
- **On success**: one `http_request_completed` access entry in `after_request` with `http_status` + `http_duration_ms`. The `X-Trace-Id` header is echoed in the response.
- **On uncaught Python exception**: one ERROR entry with `event=uncaught_exception`, the full stack, `http_status=500`, request context (`http_client`, `http_headers`, `http_query_params`, `http_body`), and a JSON 500 response. The access log is suppressed so each failed request produces exactly one entry.
- **Robyn's startup chatter** (route registration, `Starting server at …`, actix worker init) flows through rahm's formatter tagged `event=robyn` / `event=actix` — but only if you call `setup_logging()` before constructing the app.

## Wiring

```python
from rahm.robyn import install_rahm, setup_logging

setup_logging()              # before importing robyn — see note below
import robyn

app = robyn.Robyn(__file__)
install_rahm(app)
```

### Why call `setup_logging()` before `import robyn`

Robyn emits the first log lines (`SERVER IS RUNNING IN VERBOSE/DEBUG MODE`, route-registration messages) at `robyn.Robyn(__file__)` construction and at `@app.get(...)` decorator time — **before** `install_rahm(app)` runs. Calling `setup_logging()` first attaches rahm's formatter to the `robyn`, `actix_server`, `actix_web` parent loggers so those early lines are captured.

`install_rahm(app)` also calls `setup_logging()` (idempotent), so it's safe to skip the explicit call — you only lose the handful of lines that fire during `Robyn(__file__)` and route registration.

## API

### `install_rahm(app) -> app`

Registers all three handlers on the given Robyn app and calls `setup_logging()`. Returns the app for chaining.

### `setup_logging()`

Attaches rahm's formatter (driven by `RAHM_LOG_FORMAT`) to the `robyn`, `actix_server`, and `actix_web` loggers; tags their records with `event=robyn` or `event=actix` via `RobynNormalizer`; silences propagation to root. Idempotent.

### `rahm_before_request(request) -> request`

The `@app.before_request()` hook. Opens the scope, stashes the request on a contextvar, records the start time. Always returns the request unchanged.

### `rahm_after_request(request, response) -> response`

The `@app.after_request()` hook. Emits the access log, echoes `X-Trace-Id` in the response, clears per-request state. Skipped when the exception handler already logged.

### `rahm_exception_handler(err) -> robyn.Response`

The `@app.exception` handler. Logs `uncaught_exception` with request context (read from the contextvar set by `rahm_before_request`) and returns a JSON 500 `robyn.Response`.

You can register the three individually if you don't want the `install_rahm(app)` helper:

```python
from rahm.robyn import (
    setup_logging,
    rahm_before_request,
    rahm_after_request,
    rahm_exception_handler,
)

setup_logging()
import robyn
app = robyn.Robyn(__file__)
app.before_request()(rahm_before_request)
app.after_request()(rahm_after_request)
app.exception(rahm_exception_handler)
```

## TestClient gotcha

Robyn's `robyn.testing.TestClient` only invokes `after_request` middleware when the handler returns a `robyn.Response` object — plain string returns short-circuit at the test client and the access log never fires.

For tests, return `Response` explicitly:

```python
@app.get('/')
def hello(request):
    return robyn.Response(status_code=200, description='hello', headers={})
```

The real Rust-backed server has no such limitation — string returns are converted to `Response` upstream of middleware. This affects test code only.

## Environment variables

| Variable             | Effect                                                                                       |
|----------------------|----------------------------------------------------------------------------------------------|
| `RAHM_LOG_FORMAT`    | Selects the formatter used for both your logs and Robyn / actix pass-through lines.          |
| `RAHM_LOG_TRACE_ID`  | `disabled` suppresses trace_id binding and the `X-Trace-Id` response-header echo.            |

All the env vars from [docs/logging.md](logging.md#configuration) still apply.

## Demo

```sh
uv run --env-file .env python -m demo.log_robyn
```

The script (`demo/log_robyn.py`) boots a real Robyn server on a background thread, fires baseline / supplied-trace-id / 404 / uncaught-exception requests, and exits cleanly.

## See also

- [docs/logging.md](logging.md) — core logging concepts the middleware builds on.
- [docs/starlette.md](starlette.md) — same surface for Starlette.
- [docs/falcon.md](falcon.md) — same surface for Falcon.
