"""Mandatory + reserved field names can't be scope-bound."""
import pytest
import rahm


@pytest.mark.parametrize('name', ['timestamp', 'application', 'environment', 'file', 'line'])
def test_library_set_fields_cant_be_in_scope(name):
    with pytest.raises(ValueError, match='library-set'):
        rahm.log.scope(**{name: 'x'})


@pytest.mark.parametrize('name', ['severity', 'domain', 'event', 'message'])
def test_caller_set_mandatory_fields_cant_be_in_scope(name):
    with pytest.raises(ValueError, match='caller-set mandatory'):
        rahm.log.scope(**{name: 'x'})


@pytest.mark.parametrize('name', ['include', 'exclude'])
def test_reserved_kwargs_cant_be_in_scope(name):
    with pytest.raises(ValueError, match='reserved kwarg'):
        rahm.log.scope(**{name: ['x']})


@pytest.mark.parametrize('name', ['timestamp', 'severity', 'include', 'exclude'])
def test_reserved_names_cant_be_bound(name):
    with rahm.log.scope(trace_id='t1'):
        with pytest.raises(ValueError):
            rahm.log.bind(**{name: 'x'})
