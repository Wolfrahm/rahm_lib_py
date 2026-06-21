"""Wire format: one JSON object per line, mandatory fields, canonical order."""
import json
import re

import rahm

from .conftest import read_one

ISO_MS = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$')


def test_mandatory_fields_present(capture_logs):
    rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    for field in ('timestamp', 'severity', 'application', 'environment',
                  'domain', 'event', 'message', 'file', 'line'):
        assert field in log, f"missing mandatory field: {field}"


def test_default_domain_is_system(capture_logs):
    rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert log['domain'] == 'system'


def test_severity_is_lowercase(capture_logs):
    rahm.log.warning('evt', 'msg')
    log = read_one(capture_logs)
    assert log['severity'] == 'warning'


def test_timestamp_is_rfc3339_milliseconds(capture_logs):
    rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert ISO_MS.match(log['timestamp']), log['timestamp']


def test_field_order(capture_logs):
    rahm.log.info('evt', 'msg', extra_field='x')
    raw = capture_logs.getvalue().strip()
    parsed = json.loads(raw)
    keys = list(parsed.keys())
    # canonical leading order: timestamp, severity, application, environment,
    # domain, event, message, file, line, ... extras at the end
    expected_prefix = ['timestamp', 'severity', 'application', 'environment',
                      'domain', 'event', 'message', 'file', 'line']
    assert keys[:len(expected_prefix)] == expected_prefix
    assert 'extra_field' in keys[len(expected_prefix):]


def test_one_json_object_per_line(capture_logs):
    rahm.log.info('a', 'm1')
    rahm.log.info('b', 'm2')
    rahm.log.info('c', 'm3')
    lines = [line for line in capture_logs.getvalue().splitlines() if line]
    assert len(lines) == 3
    for line in lines:
        json.loads(line)  # parses cleanly


def test_application_and_environment_from_env(capture_logs):
    rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert log['application'] == 'rahm_test'
    assert log['environment'] == 'test'


def test_line_field_is_string(capture_logs):
    rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert isinstance(log['line'], str)
    assert log['line'].isdigit()


def test_file_field_points_at_caller(capture_logs):
    rahm.log.info('evt', 'msg')
    log = read_one(capture_logs)
    assert log['file'].endswith('test_wire_shape.py')
