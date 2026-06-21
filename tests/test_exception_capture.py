"""Auto-capture of the active exception in error/fatal (spec 9)."""
import rahm

from .conftest import read_one


def test_error_inside_except_auto_captures(capture_logs):
    try:
        1 / 0
    except ZeroDivisionError:
        rahm.log.error('division_failed', 'cannot divide by zero')
    log = read_one(capture_logs)
    assert log['error_type'] == 'ZeroDivisionError'
    assert log['error_message'] == 'division by zero'
    assert isinstance(log['error_trace'], list)
    assert any('test_exception_capture.py' in frame for frame in log['error_trace'])


def test_fatal_inside_except_auto_captures(capture_logs):
    try:
        raise RuntimeError('boom')
    except RuntimeError:
        rahm.log.fatal('died', 'process about to exit')
    log = read_one(capture_logs)
    assert log['severity'] == 'fatal'
    assert log['error_type'] == 'RuntimeError'
    assert log['error_message'] == 'boom'


def test_info_inside_except_does_not_auto_capture(capture_logs):
    try:
        1 / 0
    except ZeroDivisionError:
        rahm.log.info('soft_skip', 'skipping')
    log = read_one(capture_logs)
    assert 'error_type' not in log


def test_error_outside_except_has_no_error_fields(capture_logs):
    rahm.log.error('something_failed', 'msg')
    log = read_one(capture_logs)
    assert 'error_type' not in log
    assert 'error_message' not in log
    assert 'error_trace' not in log


def test_explicit_exc_info_tuple_used(capture_logs):
    try:
        raise ValueError('explicit')
    except ValueError:
        import sys
        exc = sys.exc_info()
    rahm.log.error('post_mortem', 'msg', exc_info=exc)
    log = read_one(capture_logs)
    assert log['error_type'] == 'ValueError'
    assert log['error_message'] == 'explicit'
