"""UvicornNormalizer filter: expand %-args, drop color_message, set event=uvicorn."""
import logging

from rahm.starlette import UvicornNormalizer, uvicorn_log_config


def _make_record(msg, args=(), **extra):
    record = logging.LogRecord(
        name='uvicorn', level=logging.INFO, pathname='', lineno=0,
        msg=msg, args=args, exc_info=None,
    )
    for k, v in extra.items():
        setattr(record, k, v)
    return record


def test_expands_format_args():
    rec = _make_record('hello %s', ('world',))
    UvicornNormalizer().filter(rec)
    assert rec.msg == 'hello world'
    assert rec.args == ()


def test_strips_color_message():
    rec = _make_record('hello', color_message='\x1b[1mhello\x1b[0m')
    UvicornNormalizer().filter(rec)
    assert not hasattr(rec, 'color_message')


def test_tags_event_uvicorn():
    rec = _make_record('Started server process [%d]', (1234,))
    UvicornNormalizer().filter(rec)
    assert rec.event == 'uvicorn'


def test_filter_returns_truthy():
    rec = _make_record('msg')
    assert UvicornNormalizer().filter(rec) is True


def test_uvicorn_log_config_shape():
    config = uvicorn_log_config()
    assert config['version'] == 1
    assert 'rahm' in config['formatters']
    assert 'uvicorn_normalizer' in config['filters']
    assert 'rahm' in config['handlers']
    for logger_name in ('uvicorn', 'uvicorn.access'):
        assert logger_name in config['loggers']
        assert config['loggers'][logger_name]['handlers'] == ['rahm']
        assert config['loggers'][logger_name]['propagate'] is False


def test_uvicorn_log_config_text_format(monkeypatch):
    monkeypatch.setenv('RAHM_LOG_FORMAT', 'text')
    from rahm.log import LocalFormatter
    config = uvicorn_log_config()
    assert config['formatters']['rahm']['()'] is LocalFormatter


def test_uvicorn_log_config_json_format(monkeypatch):
    monkeypatch.setenv('RAHM_LOG_FORMAT', 'json')
    from rahm.log import JsonFormatter
    config = uvicorn_log_config()
    assert config['formatters']['rahm']['()'] is JsonFormatter


def test_uvicorn_log_config_logfmt_format(monkeypatch):
    monkeypatch.setenv('RAHM_LOG_FORMAT', 'logfmt')
    from rahm.log import LogfmtFormatter
    config = uvicorn_log_config()
    assert config['formatters']['rahm']['()'] is LogfmtFormatter
