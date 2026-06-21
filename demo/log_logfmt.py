"""Demo: logfmt output (compact key=value, useful when an LLM is the log consumer).

Runs regardless of RAHM_LOG_FORMAT — the demo swaps in LogfmtFormatter at runtime,
the same way log_json.py demonstrates JsonFormatter customization.

Two passes:
  1. vanilla LogfmtFormatter — what every service gets by setting RAHM_LOG_FORMAT=logfmt.
  2. a customer subclass — showing that the same `transform_fields` / `rename_keys`
     hooks JsonFormatter exposes also work for LogfmtFormatter.
"""
import rahm
from rahm.log import LogfmtFormatter


# ----- pass 1: vanilla logfmt -----

rahm.log.handlers[0].setFormatter(LogfmtFormatter())

print('--- vanilla logfmt ---')

rahm.log.info('order_placed', 'order placed', order_id='O-1001', amount=49.99)

rahm.log.info('user_signed_in', 'user signed in', domain='auth', user_id='u_42')

rahm.log.warning('payment_declined', 'card declined',
                 domain='transaction', resource_id='order_O-1001',
                 reason='insufficient funds')

# nested values are JSON-stringified inside the quoted value, so the entry
# stays one line per record without losing structure.
rahm.log.info('payload_received', 'pipeline payload arrived',
              payload={'kind': 'invoice', 'lines': [{'sku': 'A-1', 'qty': 3},
                                                     {'sku': 'B-7', 'qty': 1}]})

# auto-captured exception — error_type / error_message / error_trace flow through
try:
    1 / 0
except ZeroDivisionError:
    rahm.log.error('division_failed', 'cannot divide by zero')

# scope + bind + domain filtering
with rahm.log.scope(trace_id='t_demo', user_id='u_42', resource_id='r_99'):
    rahm.log.info('viewed', 'resource viewed', domain='transaction')


# ----- pass 2: customer subclass -----

class CustomerLogfmtFormatter(LogfmtFormatter):
    """Same hooks as the JsonFormatter customer demo:
    - rename `severity` → `level`, `message` → `msg`
    - add a `tenant` field
    - reorder so the customer fields lead
    """

    field_order = [
        'timestamp', 'level', 'application', 'environment', 'tenant',
        'domain', 'event', 'msg', 'file', 'line',
        'error_type', 'error_message', 'error_trace',
    ]

    def transform_fields(self, log):
        log['tenant'] = 'acme-corp'

    def rename_keys(self, log):
        log['level'] = log.pop('severity')
        log['msg'] = log.pop('message')


rahm.log.handlers[0].setFormatter(CustomerLogfmtFormatter())

print()
print('--- customer-customized logfmt ---')

rahm.log.info('order_placed', 'order placed', order_id='O-1001', amount=49.99)
rahm.log.warning('payment_retry', 'payment retry', order_id='O-1001', attempt=2)
