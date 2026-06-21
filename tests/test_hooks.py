"""sys.excepthook, sys.unraisablehook, threading.excepthook adapters.

We use the Logger instance that `rahm/__init__.py` created (`rahm.logger`)
rather than constructing a new one, so we don't have to manage extra handlers.
The autouse `isolate_logger` fixture restores singleton state on teardown.
"""
import json
import sys
import threading
from types import SimpleNamespace

import rahm

from .conftest import read_logs


def test_excepthook_emits_fatal_uncaught(capture_logs):
    try:
        raise RuntimeError('main thread died')
    except RuntimeError:
        rahm.logger.handle_exception(*sys.exc_info())
    [log] = read_logs(capture_logs)
    assert log['severity'] == 'fatal'
    assert log['event'] == 'uncaught_exception'
    assert log['error_type'] == 'RuntimeError'
    assert log['error_message'] == 'main thread died'


def test_excepthook_keyboardinterrupt_becomes_info(capture_logs):
    try:
        raise KeyboardInterrupt()
    except KeyboardInterrupt:
        rahm.logger.handle_exception(*sys.exc_info())
    [log] = read_logs(capture_logs)
    assert log['severity'] == 'info'
    assert log['event'] == 'application_closed'
    assert 'KeyboardInterrupt' in log['message']


def test_excepthook_systemexit_becomes_info(capture_logs):
    try:
        raise SystemExit(0)
    except SystemExit:
        rahm.logger.handle_exception(*sys.exc_info())
    [log] = read_logs(capture_logs)
    assert log['severity'] == 'info'
    assert log['event'] == 'application_closed'


def test_unraisable_hook_emits_error(capture_logs):
    try:
        raise ZeroDivisionError('division by zero')
    except ZeroDivisionError as e:
        args = SimpleNamespace(
            exc_type=type(e),
            exc_value=e,
            exc_traceback=e.__traceback__,
            err_msg='Exception ignored in __del__',
            object='ConnectionPool(name="primary")',
        )
    rahm.logger.handle_unraisable(args)
    [log] = read_logs(capture_logs)
    assert log['severity'] == 'error'
    assert log['event'] == 'unraisable_exception'
    assert log['error_type'] == 'ZeroDivisionError'
    assert log['error_err_msg'] == 'Exception ignored in __del__'
    assert log['error_object'] == 'ConnectionPool(name="primary")'


def test_threading_hook_emits_error_with_thread_field(capture_logs):
    worker = threading.Thread(name='worker-1', target=lambda: None)
    try:
        raise RuntimeError('worker died')
    except RuntimeError as e:
        args = SimpleNamespace(
            exc_type=type(e),
            exc_value=e,
            exc_traceback=e.__traceback__,
            thread=worker,
        )
    rahm.logger.handle_threading_exception(args)
    [log] = read_logs(capture_logs)
    assert log['severity'] == 'error'
    assert log['event'] == 'uncaught_threading_exception'
    assert log['error_type'] == 'RuntimeError'
    assert log['error_message'] == 'worker died'
    assert 'worker-1' in log['error_thread']
