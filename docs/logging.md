# Logging

The core logging capability of rahm. Implements the cross-language Rahm Logging contract (see `guidelines/logging.md`) in Python.

## Framework integrations

Logging works standalone. The pages below wire it into an HTTP framework — per-request `trace_id`, scoped `http_*` fields, an access log per request, and uncaught-exception capture.

- [docs/starlette.md](starlette.md) — Starlette + uvicorn.
- [docs/falcon.md](falcon.md) — Falcon WSGI + ASGI.
- [docs/robyn.md](robyn.md) — Robyn.

## What you get

- **One call shape**: `rahm.log.<severity>(event, message, **fields)`.
- **One wire shape**: a single JSON object per entry on stdout (plus optional `text` and `logfmt` formats for dev / LLM consumption).
- **Per-task scope** (`contextvars`-backed) so cross-cutting fields like `trace_id` flow across many log lines without re-passing them.
- **Domain-based filtering**: `system`, `auth`, `transaction`, `metric` — each domain restricts which severities and scope fields can appear.
- **Auto-capture** of the active exception when you call `.error()` / `.fatal()` inside an `except` block.
- **Uncaught-exception hooks**: `sys.excepthook`, `sys.unraisablehook`, `threading.excepthook` all emit the same shape as your normal logs.
- **Customizable formatters**: subclass `JsonFormatter` or `LogfmtFormatter` and override only the hooks you need.

## Install

```sh
uv sync                       # logging only — no extras needed
```

For framework wiring (Starlette / Falcon / Robyn), see the integration pages linked above.

## Configuration

All env vars are optional and case-insensitive. Unknown values for the enum vars raise `ValueError` at import.

| Variable             | Values                                                     | Default     |
|----------------------|------------------------------------------------------------|-------------|
| `RAHM_APPLICATION`   | string — short service name                                | `unknown`   |
| `RAHM_ENVIRONMENT`   | string — `local`, `staging`, `production`, …               | `unknown`   |
| `RAHM_LOG_FORMAT`    | `json` \| `text` \| `logfmt`                               | `json`      |
| `RAHM_LOG_SEVERITY`  | `debug` \| `info` \| `warning` \| `error` \| `fatal` \| `none` | `info`      |
| `RAHM_LOG_TRACE_ID`  | `enabled` \| `disabled` — HTTP middleware trace_id binding | `enabled`   |

`RAHM_LOG_SEVERITY=none` silences output entirely (useful in tests).

## Calls

```python
import rahm

rahm.log.info('order_placed', 'order placed', order_id='O-1001', amount=49.99)
rahm.log.error('payment_failed', 'payment failed', order_id='O-1001')
```

Positional args are always `event` then `message`. Everything after is a structured field.

- **`event`** is a `snake_case` low-cardinality identifier (use the same event name across many log lines that mean the same thing).
- **`message`** is a one-line human sentence. Don't shove structured data in here — give it a field.
- **`**fields`** become top-level keys in the JSON output, in insertion order (canonical fields first; see "Output formats" below).

Severities, in order: `debug`, `info`, `warning`, `error`, `fatal`. Each is a method on `rahm.log`.

## Domains

A domain tags an entry as system / auth / transaction / metric. Default is `system`. Add `domain=` per call.

```python
rahm.log.info('user_signed_in', 'user signed in', domain='auth', user_id='u_42')
rahm.log.warning('payment_declined', 'card declined',
                 domain='transaction', resource_id='order_O-1001', reason='insufficient_funds')
```

Allowed values: `system` (default), `auth`, `metric`, `transaction`.

### Severity restrictions

| Domain        | Allowed severities |
|---------------|--------------------|
| `system`      | debug → fatal      |
| `auth`        | info, warning      |
| `transaction` | info, warning      |
| `metric`      | info, warning      |

Pairing a non-system domain with `debug` / `error` / `fatal` coerces the entry to `system` and emits a misuse warning.

### Scope-field filtering

Each non-system domain also restricts which **scope** fields can appear. Scope fields not in the allow-list are dropped at log time; per-call kwargs always pass through.

| Domain        | Severities      | Scope fields allowed             |
|---------------|-----------------|----------------------------------|
| `system`      | debug → fatal   | all                              |
| `auth` (info) | info            | `trace_id`, `user_id`            |
| `auth` (warn) | warning         | all                              |
| `transaction` | info, warning   | `trace_id`, `resource_id`        |
| `metric`      | info, warning   | `trace_id`, `resource_id`        |

Override per call with reserved kwargs:

- `include=['field', ...]` — keep scope fields the domain would drop.
- `exclude=['field', ...]` — drop scope fields the domain would keep (works in `system` too).

```python
with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1', noisy='leak'):
    rahm.log.info('paid', 'recorded', domain='transaction', include=['user_id'])
    # → trace_id, resource_id, user_id (noisy is dropped, user_id is rescued)
```

## Scopes

A scope is the per-task field set every log line inside the block inherits. Open with `with rahm.log.scope(...)`. Add/remove fields with `bind` / `unbind`.

```python
with rahm.log.scope(trace_id='abc-123', request_id='req-1'):
    rahm.log.info('request_start', 'inside scope')
    rahm.log.bind(user_id='u_42')                       # persists for the rest of the scope
    rahm.log.info('user_auth', 'user authed')
    with rahm.log.bind(step='validate'):                # temporary; auto-restores on exit
        rahm.log.info('validate_step', 'in sub-block')
    rahm.log.unbind('user_id')                          # remove explicitly
```

### Rules

- One active scope per task. Reopening raises.
- `bind` / `unbind` outside a scope raise.
- A per-call kwarg colliding with a scope field raises `attribute '<name>' already set in scope`.
- The mandatory fields the library sets (`timestamp`, `application`, `environment`, `file`, `line`) and the caller-set mandatory fields (`severity`, `domain`, `event`, `message`) can't be scope-bound.
- Per-task isolation via `contextvars`. asyncio child tasks inherit the parent's scope (so `trace_id` flows down).

## Exception capture

Inside an `except` block, `.error()` and `.fatal()` automatically capture the active exception into `error_type` / `error_message` / `error_trace`. No `exc_info=True` needed.

```python
try:
    do_thing()
except SomeError:
    rahm.log.error('thing_failed', 'thing went wrong')   # picks up the exception
```

## Uncaught exceptions

`rahm` installs three Python-level hooks at import time:

| Hook                         | Fires when                                              | Severity | Event                          |
|------------------------------|---------------------------------------------------------|----------|--------------------------------|
| `sys.excepthook`             | uncaught exception in main thread (process exits)       | FATAL    | `uncaught_exception`           |
| `sys.unraisablehook`         | exception during GC / `__del__` / weakref callback      | ERROR    | `unraisable_exception`         |
| `threading.excepthook`       | uncaught exception in a worker thread (thread dies)     | ERROR    | `uncaught_threading_exception` |

Convention: **FATAL = the process actually stopped**. Unraisable and threading exceptions stay at ERROR because the process keeps running.

See `demo/log_cli.py` for a runnable demo of all three.

## Output formats

### text (dev)

Colored, multi-line CLI output. `timestamp`, `application`, `environment` are suppressed (deploy-wide constants, noise in dev). `event` and `domain` are folded into the title line.

```
INFO   | order_placed        : order placed - main.py:42 - system
       | order_id            : O-1001
       | amount              : 49.99
```

### json (wire)

One JSON object per line, fields in canonical order:

```json
{"timestamp": "2026-06-15T10:23:14.123Z", "severity": "info", "application": "rahm", "environment": "production", "domain": "system", "event": "order_placed", "message": "order placed", "file": "main.py", "line": "42", "order_id": "O-1001", "amount": 49.99}
```

### logfmt (LLM-friendly)

One line of `key=value` pairs per entry. Bare values where safe; quoted with `\\` / `\"` / `\n` / `\r` / `\t` escapes when not. Nested dicts/lists are JSON-stringified inside quotes so each entry stays single-line.

```
timestamp=2026-06-15T10:23:14.123Z severity=info application=rahm environment=production domain=system event=order_placed message="order placed" file=main.py line=42 order_id=O-1001 amount=49.99
```

### Field order (all three formats)

```
timestamp, severity, application, environment, domain, event, message,
source location (file, line, …),
runtime context (thread, process, task_name, …),
error_* (when present),
…then anything else from kwargs in insertion order
```

### Truncation

Entries are capped at 64 KiB in every format. Oversize lines replace the largest top-level field with `{"truncated": true, "original_bytes": N}` (rendered per format) until the entry fits. Entries are never split or dropped.

## Customizing the JSON or logfmt format

Subclass `JsonFormatter` or `LogfmtFormatter` and override only the hooks you need. Both expose the same four hooks (`field_order`, `format_timestamp`, `transform_fields`, `rename_keys`) so swapping output formats doesn't require re-learning the API.

```python
import os
import rahm
from rahm.log import JsonFormatter


class CustomerFormatter(JsonFormatter):

    field_order = [
        'timestamp', 'level', 'application', 'environment', 'tenant', 'domain', 'event', 'msg',
        'file', 'line', 'function',
        'thread', 'thread_name', 'process', 'process_name', 'task_name',
        'error_type', 'error_message', 'error_trace',
        'error_err_msg', 'error_object', 'error_thread',
    ]

    def format_timestamp(self, dt):
        return dt.timestamp()                            # unix seconds, not ISO

    def transform_fields(self, log):
        log['tenant'] = os.environ['CUSTOMER_TENANT']    # add
        log.pop('process', None)                         # remove

    def rename_keys(self, log):
        log['level'] = log.pop('severity')               # rename to customer vocabulary
        log['msg'] = log.pop('message')


rahm.log.handlers[0].setFormatter(CustomerFormatter())
```

Each hook has a single responsibility:

- `field_order` — class attribute, a list of keys in the order they appear on the wire.
- `format_timestamp(dt)` — return any JSON-serializable value (string, int, float).
- `transform_fields(log)` — add, remove, or rewrite values in the dict. The library sets `application` / `environment` itself; you don't need to call `super()`.
- `rename_keys(log)` — pop & set keys to translate to customer vocabulary.

For `LogfmtFormatter` the hooks are identical — same names, same signatures.

See `demo/log_json.py` and `demo/log_logfmt.py` for runnable examples that include a customer subclass.

## Demos

- `demo/log_cli.py` — every severity, scopes + bind/unbind, domain filtering, auto-capture, the uncaught-exception hook trio.
- `demo/log_json.py` — vanilla `JsonFormatter` + a customer subclass.
- `demo/log_logfmt.py` — vanilla `LogfmtFormatter` + a customer subclass.

Run any of them with:

```sh
uv run --env-file .env python -m demo.log_cli
```

