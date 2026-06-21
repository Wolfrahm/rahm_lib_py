"""scope() open/close, double-open, scope-less bind/unbind, per-call collision."""
import pytest
import rahm

from .conftest import read_one


def test_fields_inside_scope_are_attached(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1'):
        rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert log['trace_id'] == 't1'
    assert log['user_id'] == 'u1'


def test_scope_drops_fields_on_exit(capture_logs):
    with rahm.log.scope(trace_id='t1'):
        pass
    rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert 'trace_id' not in log


def test_scope_drops_fields_on_exception():
    with pytest.raises(RuntimeError, match='oops'):
        with rahm.log.scope(trace_id='t1'):
            raise RuntimeError('oops')
    from rahm.log import _scope_var
    assert _scope_var.get() is None


def test_reopening_scope_raises():
    with rahm.log.scope(trace_id='t1'):
        with pytest.raises(RuntimeError, match='already active'):
            with rahm.log.scope(trace_id='t2'):
                pass


def test_per_call_kwarg_colliding_with_scope_raises(capture_logs):
    with rahm.log.scope(user_id='u1'):
        with pytest.raises(ValueError, match="user_id"):
            rahm.log.info('evt', 'msg', user_id='u2')


def test_per_call_passes_when_scope_does_not_have_field(capture_logs):
    with rahm.log.scope(trace_id='t1'):
        rahm.log.info('evt', 'msg', user_id='u2')
    log = read_one(capture_logs)
    assert log['user_id'] == 'u2'


def test_bind_outside_scope_raises():
    with pytest.raises(RuntimeError, match='no active scope'):
        rahm.log.bind(x=1)


def test_unbind_outside_scope_raises():
    with pytest.raises(RuntimeError, match='no active scope'):
        rahm.log.unbind('x')
