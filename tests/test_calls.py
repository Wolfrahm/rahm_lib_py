"""Per-severity log methods take (event, message, **fields)."""
import pytest
import rahm

from .conftest import read_one


@pytest.mark.parametrize('method,severity', [
    ('debug', 'debug'),
    ('info', 'info'),
    ('warning', 'warning'),
    ('error', 'error'),
    ('critical', 'fatal'),
    ('fatal', 'fatal'),
])
def test_each_severity_method(capture_logs, method, severity):
    getattr(rahm.log, method)('evt', 'msg')
    log = read_one(capture_logs)
    assert log['severity'] == severity
    assert log['event'] == 'evt'
    assert log['message'] == 'msg'


def test_custom_fields_passed_as_kwargs(capture_logs):
    rahm.log.info('evt', 'msg', order_id='O-1', amount=49.99, tags=['a', 'b'])
    log = read_one(capture_logs)
    assert log['order_id'] == 'O-1'
    assert log['amount'] == 49.99
    assert log['tags'] == ['a', 'b']


def test_passing_extra_kwarg_raises(capture_logs):
    with pytest.raises(TypeError, match='pass custom fields as kwargs'):
        rahm.log.info('evt', 'msg', extra={'k': 'v'})


def test_exception_method_sets_exc_info(capture_logs):
    try:
        raise ValueError('boom')
    except ValueError:
        rahm.log.exception('evt', 'msg')
    log = read_one(capture_logs)
    assert log['severity'] == 'error'
    assert log['error_type'] == 'ValueError'
    assert log['error_message'] == 'boom'


def test_message_is_stringified(capture_logs):
    rahm.log.info('evt', 12345)
    log = read_one(capture_logs)
    assert log['message'] == '12345'
