"""RAHM_LOG_SEVERITY threshold parsing in Logger.set_logger()."""
import logging

import pytest
from rahm.log import Logger


@pytest.mark.parametrize('value,expected_level', [
    ('debug', logging.DEBUG),
    ('info', logging.INFO),
    ('warning', logging.WARNING),
    ('error', logging.ERROR),
    ('fatal', logging.CRITICAL),
    ('none', logging.CRITICAL + 1),
])
def test_valid_severity_values(monkeypatch, fresh_singleton, value, expected_level):
    monkeypatch.setenv('RAHM_LOG_SEVERITY', value)
    logger = Logger().get()
    assert logger.level == expected_level


def test_uppercase_value_is_normalized(monkeypatch, fresh_singleton):
    monkeypatch.setenv('RAHM_LOG_SEVERITY', 'WARNING')
    logger = Logger().get()
    assert logger.level == logging.WARNING


def test_unknown_severity_raises(monkeypatch, fresh_singleton):
    monkeypatch.setenv('RAHM_LOG_SEVERITY', 'nope')
    with pytest.raises(ValueError, match='RAHM_LOG_SEVERITY'):
        Logger()


def test_default_is_info(monkeypatch, fresh_singleton):
    monkeypatch.delenv('RAHM_LOG_SEVERITY', raising=False)
    logger = Logger().get()
    assert logger.level == logging.INFO


def test_none_suppresses_all_output(monkeypatch, fresh_singleton, capsys):
    monkeypatch.setenv('RAHM_LOG_SEVERITY', 'none')
    logger = Logger().get()
    logger.debug('evt', 'msg')
    logger.info('evt', 'msg')
    logger.warning('evt', 'msg')
    logger.error('evt', 'msg')
    logger.critical('evt', 'msg')
    out = capsys.readouterr().out
    assert out == ''
