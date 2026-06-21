"""64 KiB entry cap: replace largest top-level field with truncation marker (spec 5)."""
import json

import rahm

from .conftest import read_one


def test_oversize_field_replaced_with_marker(capture_logs):
    big = 'x' * 80_000
    rahm.log.info('evt', 'msg', payload=big)
    log = read_one(capture_logs)
    assert log['payload'] == {'truncated': True, 'original_bytes': len(json.dumps(big).encode('utf-8'))}


def test_entry_fits_under_limit_after_truncation(capture_logs):
    rahm.log.info('evt', 'msg', payload='y' * 80_000)
    line = capture_logs.getvalue().strip()
    assert len(line.encode('utf-8')) <= 65536


def test_largest_field_picked_when_multiple_big(capture_logs):
    rahm.log.info('evt', 'msg', small='a' * 30_000, large='b' * 80_000)
    log = read_one(capture_logs)
    assert log['large'] == {'truncated': True, 'original_bytes': len(json.dumps('b' * 80_000).encode('utf-8'))}
    assert log['small'] == 'a' * 30_000


def test_truncation_idempotent_no_infinite_loop(capture_logs):
    """Multiple oversize fields force repeated truncation; the truncation marker
    itself must not be re-replaced (the candidates filter guards against that)."""
    rahm.log.info('evt', 'msg', a='x' * 80_000, b='y' * 80_000)
    log = read_one(capture_logs)
    truncated = sum(1 for v in log.values() if isinstance(v, dict) and v.get('truncated'))
    assert truncated >= 1


def test_small_entry_not_touched(capture_logs):
    rahm.log.info('evt', 'msg', payload='tiny')
    log = read_one(capture_logs)
    assert log['payload'] == 'tiny'
