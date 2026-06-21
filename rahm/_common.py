"""Bits shared between framework integration modules.

Lives here so importing one framework integration doesn't drag in another's
dependencies.
"""
import os
import time


_CROCKFORD = '0123456789abcdefghjkmnpqrstvwxyz'


# Crockford base32, lowercase. 48-bit ms timestamp + 80-bit random = 128 bits → 26 chars.
def ulid():
    n = (int(time.time() * 1000) << 80) | int.from_bytes(os.urandom(10), 'big')
    out = []
    for _ in range(26):
        n, r = divmod(n, 32)
        out.append(_CROCKFORD[r])
    return ''.join(reversed(out))


# RAHM_LOG_TRACE_ID=disabled turns off trace_id binding + response-header echo in
# HTTP middlewares. App code that explicitly binds trace_id is unaffected.
# Parsed at import time of each framework module so per-module reload() picks
# up env-var changes in tests.
def parse_trace_id_setting():
    setting = os.environ.get('RAHM_LOG_TRACE_ID', 'enabled').lower()
    if setting not in ('enabled', 'disabled'):
        raise ValueError('Incorrect value in the RAHM_LOG_TRACE_ID environment variable')
    return setting == 'enabled'
