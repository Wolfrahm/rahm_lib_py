"""Domain validation and coercion (spec 8.4)."""
import pytest
import rahm

from .conftest import read_logs


@pytest.mark.parametrize('domain', ['system', 'auth', 'metric', 'transaction'])
def test_known_domains_accepted(capture_logs, domain):
    rahm.log.info('evt', 'msg', domain=domain)
    [log] = read_logs(capture_logs)
    assert log['domain'] == domain


def test_unknown_domain_coerced_to_system_with_warning(capture_logs):
    rahm.log.info('evt', 'msg', domain='bogus')
    logs = read_logs(capture_logs)
    # one warning about the misuse + one entry for the actual call
    assert len(logs) == 2
    misuse, actual = logs
    assert misuse['severity'] == 'warning'
    assert misuse['event'] == 'rahm_misuse'
    assert 'bogus' in misuse['message']
    assert actual['domain'] == 'system'


@pytest.mark.parametrize('method', ['debug', 'error', 'fatal'])
@pytest.mark.parametrize('domain', ['auth', 'transaction', 'metric'])
def test_debug_error_fatal_require_system(capture_logs, method, domain):
    getattr(rahm.log, method)('evt', 'msg', domain=domain)
    logs = read_logs(capture_logs)
    assert len(logs) == 2
    misuse, actual = logs
    assert misuse['event'] == 'rahm_misuse'
    assert domain in misuse['message']
    assert actual['domain'] == 'system'


@pytest.mark.parametrize('domain', ['auth', 'transaction', 'metric'])
def test_info_warning_allowed_for_all_domains(capture_logs, domain):
    rahm.log.info('evt', 'msg', domain=domain)
    rahm.log.warning('evt', 'msg', domain=domain)
    logs = read_logs(capture_logs)
    assert len(logs) == 2
    assert all(log['domain'] == domain for log in logs)


def test_domain_kwarg_not_echoed_into_extras(capture_logs):
    rahm.log.info('evt', 'msg', domain='auth')
    [log] = read_logs(capture_logs)
    # domain is a top-level mandatory field, not duplicated as a custom field
    assert log['domain'] == 'auth'
