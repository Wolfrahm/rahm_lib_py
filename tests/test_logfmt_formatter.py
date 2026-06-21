"""LogfmtFormatter: quoting, escaping, field order, nested values, subclass hooks."""
import io
import json
import re

import rahm
from rahm.log import LogfmtFormatter, _logfmt_value


def _emit_with_formatter(formatter, call=None):
    """Capture one log line emitted under `formatter`."""
    buf = io.StringIO()
    handler = rahm.log.handlers[0]
    original_stream, original_formatter = handler.stream, handler.formatter
    handler.stream = buf
    handler.setFormatter(formatter)
    try:
        if call is None:
            rahm.log.info('order_placed', 'order placed', order_id='O-1001', amount=49.99)
        else:
            call()
    finally:
        handler.stream = original_stream
        handler.setFormatter(original_formatter)
    return buf.getvalue().strip()


_PAIR = re.compile(r'(\w+)=("(?:\\.|[^"\\])*"|[^ ]+)')


def parse_logfmt(line):
    """Lightweight parser for tests — returns a dict of {key: raw_value_string}."""
    return {m.group(1): m.group(2) for m in _PAIR.finditer(line)}


# ---------- value-level helpers ----------

def test_value_bare_string():
    assert _logfmt_value('plain') == 'plain'


def test_value_bare_path_with_dots_and_slashes():
    assert _logfmt_value('main.py') == 'main.py'
    assert _logfmt_value('/var/log/app.log') == '/var/log/app.log'


def test_value_quoted_when_contains_space():
    assert _logfmt_value('hello world') == '"hello world"'


def test_value_quoted_when_contains_equals():
    assert _logfmt_value('a=b') == '"a=b"'


def test_value_escapes_double_quote():
    assert _logfmt_value('he said "hi"') == r'"he said \"hi\""'


def test_value_escapes_backslash():
    assert _logfmt_value('a\\b') == r'"a\\b"'


def test_value_escapes_newline():
    assert _logfmt_value('line1\nline2') == r'"line1\nline2"'


def test_value_escapes_carriage_return_and_tab():
    assert _logfmt_value('a\rb\tc') == r'"a\rb\tc"'


def test_value_empty_string_quoted():
    assert _logfmt_value('') == '""'


def test_value_int_bare():
    assert _logfmt_value(42) == '42'


def test_value_float_bare():
    assert _logfmt_value(49.99) == '49.99'


def test_value_bool_lowercase():
    assert _logfmt_value(True) == 'true'
    assert _logfmt_value(False) == 'false'


def test_value_none_as_null():
    assert _logfmt_value(None) == 'null'


def test_value_dict_is_json_string_quoted():
    out = _logfmt_value({'k': 'v', 'n': 1})
    # round-trippable: strip outer quotes, unescape, parse JSON
    inner = out[1:-1].replace(r'\"', '"').replace(r'\\', '\\')
    assert json.loads(inner) == {'k': 'v', 'n': 1}


def test_value_list_is_json_string_quoted():
    out = _logfmt_value([1, 2, 3])
    inner = out[1:-1].replace(r'\"', '"').replace(r'\\', '\\')
    assert json.loads(inner) == [1, 2, 3]


# ---------- end-to-end formatter ----------

def test_basic_record_fields():
    line = _emit_with_formatter(LogfmtFormatter())
    parsed = parse_logfmt(line)
    assert parsed['severity'] == 'info'
    assert parsed['domain'] == 'system'
    assert parsed['event'] == 'order_placed'
    assert parsed['message'] == '"order placed"'  # quoted, has space
    assert parsed['order_id'] == 'O-1001'
    assert parsed['amount'] == '49.99'


def test_no_internal_newlines_in_output():
    line = _emit_with_formatter(LogfmtFormatter())
    assert '\n' not in line


def test_timestamp_rfc3339_milliseconds_in_logfmt():
    line = _emit_with_formatter(LogfmtFormatter())
    parsed = parse_logfmt(line)
    assert re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$', parsed['timestamp'])


def test_field_order_canonical():
    line = _emit_with_formatter(LogfmtFormatter())
    keys = [m.group(1) for m in _PAIR.finditer(line)]
    expected_prefix = ['timestamp', 'severity', 'application', 'environment',
                       'domain', 'event', 'message', 'file', 'line']
    assert keys[:len(expected_prefix)] == expected_prefix


def test_nested_dict_field_renders_quoted_json():
    line = _emit_with_formatter(
        LogfmtFormatter(),
        call=lambda: rahm.log.info('evt', 'msg', payload={'k': 'v', 'n': 1}),
    )
    parsed = parse_logfmt(line)
    inner = parsed['payload'][1:-1].replace(r'\"', '"').replace(r'\\', '\\')
    assert json.loads(inner) == {'k': 'v', 'n': 1}


def test_nested_list_field_renders_quoted_json():
    line = _emit_with_formatter(
        LogfmtFormatter(),
        call=lambda: rahm.log.info('evt', 'msg', tags=['a', 'b', 'c']),
    )
    parsed = parse_logfmt(line)
    inner = parsed['tags'][1:-1].replace(r'\"', '"').replace(r'\\', '\\')
    assert json.loads(inner) == ['a', 'b', 'c']


def test_string_with_quotes_round_trips():
    line = _emit_with_formatter(
        LogfmtFormatter(),
        call=lambda: rahm.log.info('evt', 'msg', note='he said "hi"'),
    )
    parsed = parse_logfmt(line)
    assert parsed['note'] == r'"he said \"hi\""'


def test_truncation_marker_appears_in_logfmt():
    line = _emit_with_formatter(
        LogfmtFormatter(),
        call=lambda: rahm.log.info('evt', 'msg', payload='x' * 80_000),
    )
    parsed = parse_logfmt(line)
    inner = parsed['payload'][1:-1].replace(r'\"', '"').replace(r'\\', '\\')
    decoded = json.loads(inner)
    assert decoded['truncated'] is True
    assert decoded['original_bytes'] > 0


# ---------- subclass hooks ----------

class CustomerFormatter(LogfmtFormatter):
    field_order = ['timestamp', 'level', 'application', 'environment', 'tenant',
                   'domain', 'event', 'msg', 'file', 'line']

    def format_timestamp(self, dt):
        return str(int(dt.timestamp()))

    def transform_fields(self, log):
        log['tenant'] = 'acme'

    def rename_keys(self, log):
        log['level'] = log.pop('severity')
        log['msg'] = log.pop('message')


def test_subclass_field_order():
    line = _emit_with_formatter(CustomerFormatter())
    keys = [m.group(1) for m in _PAIR.finditer(line)]
    assert keys[:5] == ['timestamp', 'level', 'application', 'environment', 'tenant']


def test_subclass_format_timestamp():
    line = _emit_with_formatter(CustomerFormatter())
    parsed = parse_logfmt(line)
    assert parsed['timestamp'].isdigit()


def test_subclass_transform_fields_adds_tenant():
    line = _emit_with_formatter(CustomerFormatter())
    parsed = parse_logfmt(line)
    assert parsed['tenant'] == 'acme'


def test_subclass_rename_keys():
    line = _emit_with_formatter(CustomerFormatter())
    parsed = parse_logfmt(line)
    assert parsed['level'] == 'info'
    assert parsed['msg'] == '"order placed"'
    assert 'severity' not in parsed
    assert 'message' not in parsed
