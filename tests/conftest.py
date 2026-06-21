"""Shared pytest fixtures for the rahm test suite.

`rahm/__init__.py` runs `Logger()` at import time. That installs three sys.*
hooks and attaches a stdout StreamHandler to the singleton 'rahm' logger.

Two layers of isolation:

  - `isolate_logger` (autouse): snapshot the singleton's scope/handlers/level
    once at import, restore them before *and* after each test so leakage from
    tests that call `Logger()` (threshold, format_env, …) can't poison the next.
  - `fresh_singleton` (opt-in): some tests want to call `Logger()` and assert
    on its handler. Clears the singleton's handler list first so `Logger()`
    leaves exactly one — the new one. Autouse teardown restores originals.

`capture_logs` redirects the singleton's original handler stream to a StringIO
so tests can read the JSON they emitted. `read_logs`/`read_one` parse it.
"""
from __future__ import annotations

import io
import json
import os
import sys
from typing import Iterator

import pytest

# Env vars must be set before `import rahm` so the singleton Logger is built
# with the JSON formatter (what tests assert against). Force the values rather
# than setdefault — if the shell or a loaded .env has RAHM_LOG_FORMAT=text,
# the tests would parse text output as JSON and fail.
os.environ['RAHM_APPLICATION'] = 'rahm_test'
os.environ['RAHM_ENVIRONMENT'] = 'test'
os.environ['RAHM_LOG_FORMAT'] = 'json'
os.environ['RAHM_LOG_SEVERITY'] = 'debug'
os.environ['RAHM_LOG_TRACE_ID'] = 'enabled'

import rahm  # noqa: E402

# `rahm/__init__.py` does `log = logger.get()`, so `rahm.log` (the attribute) is
# the singleton Logger *instance*, not the module. Grab the actual module from
# sys.modules so we can poke at module-level state (like `_scope_var`).
_log_module = sys.modules['rahm.log']

# Singleton snapshot — captured once at conftest import.
_initial_handlers = list(rahm.log.handlers)
_initial_level = rahm.log.level


@pytest.fixture(autouse=True)
def isolate_logger() -> Iterator[None]:
    """Reset rahm singleton state before AND after each test."""
    _log_module._scope_var.set(None)
    rahm.log.handlers[:] = _initial_handlers
    rahm.log.setLevel(_initial_level)
    yield
    _log_module._scope_var.set(None)
    rahm.log.handlers[:] = _initial_handlers
    rahm.log.setLevel(_initial_level)


@pytest.fixture
def fresh_singleton() -> Iterator[None]:
    """Clear the singleton's handler list so tests calling `Logger()` start blank.

    Autouse teardown restores the original handlers + level afterward, so this
    fixture only has setup semantics."""
    rahm.log.handlers[:] = []
    yield


@pytest.fixture
def capture_logs() -> Iterator[io.StringIO]:
    """Redirect the rahm handler to a StringIO; restore on teardown."""
    if not rahm.log.handlers:
        # `fresh_singleton` cleared them; pin a handler now so the test can capture.
        import logging
        from rahm.log import JsonFormatter
        h = logging.StreamHandler(io.StringIO())
        h.setFormatter(JsonFormatter())
        rahm.log.addHandler(h)
    handler = rahm.log.handlers[0]
    original = handler.stream
    buf = io.StringIO()
    handler.stream = buf
    try:
        yield buf
    finally:
        handler.stream = original


def read_logs(buf: io.StringIO) -> list[dict]:
    """Parse each non-empty line of captured JSON output into a dict."""
    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def read_one(buf: io.StringIO) -> dict:
    """Convenience: assert exactly one log line was emitted, return it."""
    logs = read_logs(buf)
    assert len(logs) == 1, f"expected 1 log line, got {len(logs)}: {logs}"
    return logs[0]
