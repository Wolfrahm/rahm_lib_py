import sys
sys.path.append('/app')
import rahm
import json


extra = {'abc': '123', 'def': '456', 'xyz': {'abc': '123', 'def': '456'}}
jsonattr = json.dumps(extra)

rahm.log.debug('demo_debug', 'Debug event happened', **extra)
rahm.log.info('demo_info', 'Info event happened', jsonattr=jsonattr)
rahm.log.warning('demo_warning', 'Warning event happened')
rahm.log.error('demo_error', 'Error event happened')
rahm.log.fatal('demo_fatal', 'Fatal event happened')


# test unraisable
class Naughty:
    def __del__(self):
        return 1 / 0
Naughty()



# test threading
import threading

def foo():
    return 1 / 0

threading.Thread(target=foo).start()



# test unraisable inside an asyncio task (populates taskName)
import asyncio

async def worker():
    Naughty()
    await asyncio.sleep(0)

async def main():
    await asyncio.create_task(worker(), name='ingest-worker')

asyncio.run(main())



# test unraisable with populated err_msg and object (simulates CPython's internal finalization paths)
from types import SimpleNamespace

try:
    raise ZeroDivisionError('division by zero')
except ZeroDivisionError as e:
    args = SimpleNamespace(
        exc_type=type(e),
        exc_value=e,
        exc_traceback=e.__traceback__,
        err_msg='Exception ignored while finalizing connection pool',
        object='ConnectionPool(name="primary")',
    )
    sys.unraisablehook(args)



# auto-capture: error/fatal inside an except block grabs the active exception
try:
    1 / 0
except ZeroDivisionError:
    rahm.log.error('division_failed', 'cannot divide by zero')


# domain-based allow-list: scope fields get filtered per spec 8.4
with rahm.log.scope(trace_id='t1', user_id='u1', resource_id='r1', noisy_internal='leak'):
    rahm.log.info('signed_in', 'user signed in', domain='auth')                       # auth+info → only trace_id, user_id survive
    rahm.log.warning('unusual_login', 'unusual login', domain='auth')                 # auth+warning → everything survives
    rahm.log.info('payment_recorded', 'payment recorded', domain='transaction')      # transaction → trace_id, resource_id only
    rahm.log.info('payment_with_user', 'payment recorded',
                  domain='transaction', include=['user_id'])                          # include= rescues user_id
    rahm.log.info('system_with_drop', 'system entry', exclude=['noisy_internal'])    # exclude= drops a field even in system


# test uncaught
def foo():
    return 1 / 0
foo()

print('BOOO')
