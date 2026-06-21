"""LocalFormatter smoke tests — text mode runs cleanly and suppresses deploy-wide fields."""
import io
import re

import rahm
from rahm.log import LocalFormatter


_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')


def _strip_ansi(s):
    return _ANSI_RE.sub('', s)


def _emit_text(call):
    buf = io.StringIO()
    handler = rahm.log.handlers[0]
    original_stream, original_formatter = handler.stream, handler.formatter
    handler.stream = buf
    handler.setFormatter(LocalFormatter())
    try:
        call()
    finally:
        handler.stream = original_stream
        handler.setFormatter(original_formatter)
    return buf.getvalue()


def test_text_output_includes_message():
    out = _emit_text(lambda: rahm.log.info('order_placed', 'order placed'))
    assert 'order placed' in out


def test_text_folds_event_and_domain_into_title():
    out = _emit_text(lambda: rahm.log.warning('demo_warning', 'Warning event happened'))
    title_line = _strip_ansi(out.splitlines()[0])
    # event leads the title, domain trails after the suffix
    assert 'demo_warning : Warning event happened' in title_line
    assert title_line.rstrip().endswith('- system')
    # event/domain must NOT also appear as separate rows
    for line in out.splitlines()[1:]:
        stripped = line.lstrip()
        assert not stripped.startswith('| event'), line
        assert not stripped.startswith('| domain'), line


def test_text_title_keeps_suffix_normal_weight():
    """Body is bold, but file:line and domain after it stay non-bold."""
    out = _emit_text(lambda: rahm.log.warning('evt', 'a msg'))
    title_line = out.splitlines()[0]
    bold, reset = '\x1b[1m', '\x1b[0m'
    # body is wrapped in bold; the trailing " - file:line - domain" is not
    assert bold + 'a msg' + reset in title_line
    # everything after the last reset on the line should be plain text (no bold marker)
    tail = title_line.rsplit(reset, 1)[1]
    assert bold not in tail
    assert ' - system' in tail


def test_text_key_column_auto_adapts_to_longest_key():
    out = _emit_text(lambda: rahm.log.info(
        'evt', 'msg',
        short='a', a_much_longer_field_name='b',
    ))
    # longest key is `a_much_longer_field_name` (24); event ('evt', 3) and
    # short keys pad to match — `:` must line up across every row.
    plain_lines = [_strip_ansi(line) for line in out.splitlines() if line.strip()]
    colon_positions = {line.index(':') for line in plain_lines}
    # exactly one colon column for the title + the two field rows
    assert len(colon_positions) == 1, (colon_positions, plain_lines)
    # ...and `evt` must be padded out to (max_key_len + 1) chars
    assert 'evt' + ' ' * (len('a_much_longer_field_name') + 1 - len('evt')) + ':' in _strip_ansi(out)


def test_text_suppresses_timestamp_application_environment():
    out = _emit_text(lambda: rahm.log.info('evt', 'msg'))
    # constants in JSON, hidden in dev terminal — but they're env-driven so just check
    # the timestamp ISO format isn't there
    assert '2026-' not in out
    assert 'rahm_test' not in out  # application value


def test_text_renders_severity_uppercase():
    out = _emit_text(lambda: rahm.log.error('evt', 'msg'))
    assert 'ERROR' in out


def test_text_each_severity_runs():
    for method in ('debug', 'info', 'warning', 'error'):
        out = _emit_text(lambda m=method: getattr(rahm.log, m)('evt', 'a msg'))
        assert 'a msg' in out


def test_text_handles_dict_field():
    out = _emit_text(lambda: rahm.log.info('evt', 'msg', payload={'k': 'v'}))
    assert 'payload' in out
    assert "'k'" in out or 'k' in out


def test_text_truncates_oversize_field():
    """Spec 5 says the 64 KiB cap applies to all formats — text included."""
    out = _emit_text(lambda: rahm.log.info('evt', 'msg', payload='x' * 80_000))
    # the field is replaced with a truncation marker dict rendered via pprint
    assert "'truncated': True" in out
    assert "'original_bytes':" in out
    # the original 80_000-byte payload must NOT be in the rendered output
    assert 'x' * 1000 not in out


def test_text_handles_exception_capture():
    def call():
        try:
            1 / 0
        except ZeroDivisionError:
            rahm.log.error('div_failed', 'cannot divide')

    out = _emit_text(call)
    assert 'cannot divide' in out
    assert 'ZeroDivisionError' in out or 'division by zero' in out
