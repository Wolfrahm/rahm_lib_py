"""Per-domain scope-field allow-lists + include/exclude reserved kwargs (spec 8.4)."""
import rahm

from .conftest import read_one


def test_system_keeps_all_scope_fields(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1', noisy='leak'):
        rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    for f in ('trace_id', 'user_id', 'resource_id', 'noisy'):
        assert log[f]


def test_auth_info_keeps_only_trace_and_user(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1', noisy='leak'):
        rahm.log.info('signed_in', 'msg', domain='auth')
    log = read_one(capture_logs)
    assert log['trace_id'] == 't1'
    assert log['user_id'] == 'u1'
    assert 'resource_id' not in log
    assert 'noisy' not in log


def test_auth_warning_keeps_all_scope_fields(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1', noisy='leak'):
        rahm.log.warning('unusual', 'msg', domain='auth')
    log = read_one(capture_logs)
    for f in ('trace_id', 'user_id', 'resource_id', 'noisy'):
        assert log[f]


def test_transaction_keeps_only_trace_and_resource(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1', noisy='leak'):
        rahm.log.info('paid', 'msg', domain='transaction')
    log = read_one(capture_logs)
    assert log['trace_id'] == 't1'
    assert log['resource_id'] == 'r1'
    assert 'user_id' not in log
    assert 'noisy' not in log


def test_metric_keeps_only_trace_and_resource(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1'):
        rahm.log.info('m', 'msg', domain='metric')
    log = read_one(capture_logs)
    assert log['trace_id'] == 't1'
    assert log['resource_id'] == 'r1'
    assert 'user_id' not in log


def test_include_rescues_a_dropped_scope_field(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1'):
        rahm.log.info('paid', 'msg', domain='transaction', include=['user_id'])
    log = read_one(capture_logs)
    assert log['trace_id'] == 't1'
    assert log['resource_id'] == 'r1'
    assert log['user_id'] == 'u1'


def test_exclude_drops_a_kept_scope_field_in_system(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1', noisy='leak'):
        rahm.log.info('evt', 'msg', exclude=['noisy'])
    log = read_one(capture_logs)
    assert log['trace_id'] == 't1'
    assert log['user_id'] == 'u1'
    assert 'noisy' not in log


def test_exclude_wins_over_include(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1'):
        rahm.log.info('paid', 'msg', domain='transaction',
                      include=['user_id'], exclude=['user_id'])
    log = read_one(capture_logs)
    assert 'user_id' not in log


def test_per_call_kwargs_bypass_allow_list(capture_logs):
    # noisy is *not* in the transaction allow-list, but it's passed as a per-call
    # kwarg (not via scope), so it survives.
    with rahm.log.scope(trace_id='t1', resource_id='r1'):
        rahm.log.info('paid', 'msg', domain='transaction', custom_field='kept')
    log = read_one(capture_logs)
    assert log['custom_field'] == 'kept'


def test_include_exclude_themselves_dont_leak_into_output(capture_logs):
    with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1'):
        rahm.log.info('paid', 'msg', domain='transaction', include=['user_id'])
    log = read_one(capture_logs)
    assert 'include' not in log
    assert 'exclude' not in log
