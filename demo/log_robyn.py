"""Demo: real Robyn server with the rahm middleware + exception handler.

Robyn's exception handler signature is just ``(err)`` — no request, no
response — so per-request state (request object, start time, trace_id)
lives on contextvars set by ``rahm_before_request``. The exception handler
reads them to populate `http_headers`, `http_query_params`, etc.

For TestClient compatibility, handlers return a ``robyn.Response`` explicitly:
Robyn's TestClient runs ``after_request`` middleware only when the handler
returns a Response object. The real server has no such limitation.
"""
import threading
import time
import urllib.error
import urllib.request

import rahm
from rahm.robyn import install_rahm, setup_logging


# call before constructing the app so route-registration + startup lines
# from `robyn.logger` and `actix_server.*` flow through rahm's formatter.
setup_logging()

import robyn  # noqa: E402

app = robyn.Robyn(__file__)
install_rahm(app)


@app.get('/')
def hello(request):
    # bind a field inside the active scope — later log lines get it
    rahm.log.bind(user_id='u_42')
    rahm.log.info('greeting', 'saying hello')
    return robyn.Response(status_code=200, description='hello', headers={})


@app.get('/boom')
def boom(request):
    raise RuntimeError('database connection lost')


thread = threading.Thread(
    target=lambda: app.start(host='127.0.0.1', port=8766),
    daemon=True,
)
thread.start()

# Robyn starts its actix workers asynchronously — give them a moment to bind.
time.sleep(0.8)

rahm.log.info('server_started', 'server is up, firing requests')

# baseline request — middleware generates a ULID trace_id
urllib.request.urlopen('http://127.0.0.1:8766/').read()

# client-supplied trace id — middleware echoes it back in X-Trace-Id
req = urllib.request.Request('http://127.0.0.1:8766/', headers={'X-Trace-Id': 'demo-trace-001'})
with urllib.request.urlopen(req) as r:
    assert r.headers.get('X-Trace-Id') == 'demo-trace-001'

# 404 — no route registered for /missing
try:
    urllib.request.urlopen('http://127.0.0.1:8766/missing', timeout=2)
except urllib.error.HTTPError:
    pass

# uncaught exception — handler emits ERROR + 500
try:
    urllib.request.urlopen('http://127.0.0.1:8766/boom?user_id=42&tenant=acme', timeout=2)
except urllib.error.HTTPError:
    pass

rahm.log.info('demo_complete', 'done')
