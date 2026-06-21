"""bind / unbind / with-bind snapshot-restore semantics."""
import pytest
import rahm

from .conftest import read_one


def test_bind_adds_field_to_scope(capture_logs):
    with rahm.log.scope(trace_id='t1'):
        rahm.log.bind(user_id='u_42')
        rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert log['user_id'] == 'u_42'


def test_bind_overwrites_previous_value(capture_logs):
    with rahm.log.scope(user_id='u_old'):
        rahm.log.bind(user_id='u_new')
        rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert log['user_id'] == 'u_new'


def test_unbind_removes_field(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u_42'):
        rahm.log.unbind('user_id')
        rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert 'user_id' not in log


def test_unbind_missing_key_raises():
    with rahm.log.scope(trace_id='t1'):
        with pytest.raises(KeyError, match='not bound'):
            rahm.log.unbind('user_id')


def test_with_bind_auto_restores_after_block(capture_logs):
    with rahm.log.scope(trace_id='t1'):
        with rahm.log.bind(step='validate'):
            rahm.log.info('inside', 'in block')
        rahm.log.info('outside', 'after block')
    logs = capture_logs.getvalue().splitlines()
    import json
    inside = json.loads(logs[0])
    outside = json.loads(logs[1])
    assert inside['step'] == 'validate'
    assert 'step' not in outside


def test_with_bind_restores_prior_value_not_just_deletes(capture_logs):
    with rahm.log.scope(user_id='u_original'):
        with rahm.log.bind(user_id='u_temp'):
            rahm.log.info('inside', 'in block')
        rahm.log.info('outside', 'after block')
    import json
    lines = capture_logs.getvalue().splitlines()
    inside = json.loads(lines[0])
    outside = json.loads(lines[1])
    assert inside['user_id'] == 'u_temp'
    assert outside['user_id'] == 'u_original'


def test_with_bind_restores_on_exception(capture_logs):
    with rahm.log.scope(user_id='u_original'):
        with pytest.raises(RuntimeError):
            with rahm.log.bind(user_id='u_temp'):
                raise RuntimeError('oops')
        rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert log['user_id'] == 'u_original'


def test_multiple_fields_in_one_bind(capture_logs):
    with rahm.log.scope(trace_id='t1'):
        rahm.log.bind(a=1, b=2, c=3)
        rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert log['a'] == 1
    assert log['b'] == 2
    assert log['c'] == 3
