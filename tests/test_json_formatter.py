"""Subclassing JsonFormatter — field_order, format_timestamp, transform_fields, rename_keys."""
import io
import json
import logging

import rahm
from rahm.log import JsonFormatter


class CustomFormatter(JsonFormatter):
    field_order = [
        'timestamp', 'level', 'application', 'environment', 'tenant',
        'domain', 'event', 'msg', 'file', 'line',
    ]

    def format_timestamp(self, dt):
        return dt.timestamp()

    def transform_fields(self, log):
        log['tenant'] = 'acme'

    def rename_keys(self, log):
        log['level'] = log.pop('severity')
        log['msg'] = log.pop('message')


def _emit_with_formatter(formatter):
    """Capture one log line emitted under `formatter`."""
    buf = io.StringIO()
    handler = rahm.log.handlers[0]
    original_stream, original_formatter = handler.stream, handler.formatter
    handler.stream = buf
    handler.setFormatter(formatter)
    try:
        rahm.log.info('order_placed', 'order placed', order_id='O-1', amount=49.99)
    finally:
        handler.stream = original_stream
        handler.setFormatter(original_formatter)
    return json.loads(buf.getvalue().strip())


def test_custom_field_order():
    log = _emit_with_formatter(CustomFormatter())
    keys = list(log.keys())
    assert keys[:5] == ['timestamp', 'level', 'application', 'environment', 'tenant']


def test_format_timestamp_override_to_unix_seconds():
    log = _emit_with_formatter(CustomFormatter())
    assert isinstance(log['timestamp'], (int, float))


def test_transform_fields_can_add_a_field():
    log = _emit_with_formatter(CustomFormatter())
    assert log['tenant'] == 'acme'


def test_rename_keys_replaces_canonical_names():
    log = _emit_with_formatter(CustomFormatter())
    assert 'severity' not in log
    assert 'message' not in log
    assert log['level'] == 'info'
    assert log['msg'] == 'order placed'


def test_default_formatter_no_renames():
    log = _emit_with_formatter(JsonFormatter())
    assert log['severity'] == 'info'
    assert log['message'] == 'order placed'


def test_subclass_with_no_overrides_works():
    class Bare(JsonFormatter):
        pass

    log = _emit_with_formatter(Bare())
    assert log['severity'] == 'info'
    assert log['message'] == 'order placed'
