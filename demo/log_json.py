"""Demo: JSON output — the canonical wire format.

Same two-pass structure as log_logfmt.py:
  1. vanilla JsonFormatter — what every service gets by default.
  2. a customer subclass — overriding the four hooks (`field_order`,
     `format_timestamp`, `transform_fields`, `rename_keys`) to reshape the
     output without touching the library.

Runs regardless of RAHM_LOG_FORMAT — the demo swaps formatters in at runtime.
"""
import rahm
from rahm.log import JsonFormatter


# ----- pass 1: vanilla json -----

rahm.log.handlers[0].setFormatter(JsonFormatter())

print('--- vanilla json ---')

rahm.log.info('order_placed', 'order placed', order_id='O-1001', amount=49.99)

rahm.log.info('user_signed_in', 'user signed in', domain='auth', user_id='u_42')

rahm.log.warning('payment_declined', 'card declined',
                 domain='transaction', resource_id='order_O-1001',
                 reason='insufficient funds')

# nested values stay nested in JSON (no stringification — JSON IS the wire format).
rahm.log.info('payload_received', 'pipeline payload arrived',
              payload={'kind': 'invoice', 'lines': [{'sku': 'A-1', 'qty': 3},
                                                     {'sku': 'B-7', 'qty': 1}]})

# auto-captured exception — error_type / error_message / error_trace
try:
    1 / 0
except ZeroDivisionError:
    rahm.log.error('division_failed', 'cannot divide by zero')

# scope + bind + domain filtering
with rahm.log.scope(trace_id='t_demo', user_id='u_42', resource_id='r_99'):
    rahm.log.info('viewed', 'resource viewed', domain='transaction')


# ----- pass 2: customer subclass -----

class CustomerJsonFormatter(JsonFormatter):
    """Customer wants:
    - 'level' / 'msg' instead of 'severity' / 'message'
    - a 'tenant' field on every line
    - unix-second timestamp instead of ISO + Z
    """

    field_order = [
        'timestamp', 'level', 'application', 'environment', 'tenant',
        'domain', 'event', 'msg', 'file', 'line',
        'error_type', 'error_message', 'error_trace',
    ]

    def format_timestamp(self, dt):
        return dt.timestamp()

    def transform_fields(self, log):
        log['tenant'] = 'acme-corp'

    def rename_keys(self, log):
        log['level'] = log.pop('severity')
        log['msg'] = log.pop('message')


rahm.log.handlers[0].setFormatter(CustomerJsonFormatter())

print()
print('--- customer-customized json ---')

rahm.log.info('order_placed', 'order placed', order_id='O-1001', amount=49.99)
rahm.log.warning('payment_retry', 'payment retry', order_id='O-1001', attempt=2)
