"""RAHM_LOG_FORMAT parsing in Logger.set_logger()."""
import pytest
from rahm.log import JsonFormatter, LocalFormatter, LogfmtFormatter, Logger


# pytest's logging plugin can inject its own LogCaptureHandler onto the rahm
# logger (propagate=False steers it our way), so handler position isn't stable.
# Find the rahm handler by formatter type instead.
def _formatter_types(logger):
    return [type(h.formatter) for h in logger.handlers if h.formatter is not None]


def test_default_format_is_json(monkeypatch, fresh_singleton):
    monkeypatch.delenv('RAHM_LOG_FORMAT', raising=False)
    logger = Logger().get()
    assert JsonFormatter in _formatter_types(logger)


def test_json_format(monkeypatch, fresh_singleton):
    monkeypatch.setenv('RAHM_LOG_FORMAT', 'json')
    logger = Logger().get()
    assert JsonFormatter in _formatter_types(logger)


def test_text_format(monkeypatch, fresh_singleton):
    monkeypatch.setenv('RAHM_LOG_FORMAT', 'text')
    logger = Logger().get()
    assert LocalFormatter in _formatter_types(logger)


def test_logfmt_format(monkeypatch, fresh_singleton):
    monkeypatch.setenv('RAHM_LOG_FORMAT', 'logfmt')
    logger = Logger().get()
    assert LogfmtFormatter in _formatter_types(logger)


def test_uppercase_value_is_normalized(monkeypatch, fresh_singleton):
    monkeypatch.setenv('RAHM_LOG_FORMAT', 'JSON')
    logger = Logger().get()
    assert JsonFormatter in _formatter_types(logger)


def test_unknown_format_raises(monkeypatch, fresh_singleton):
    monkeypatch.setenv('RAHM_LOG_FORMAT', 'yaml')
    with pytest.raises(ValueError, match='RAHM_LOG_FORMAT'):
        Logger()
