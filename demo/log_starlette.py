"""Demo: real uvicorn + Starlette server with the rahm HTTP middleware.

The middleware opens a rahm scope per request, binding trace_id + http_method +
http_path. Subsequent log lines inside the handler inherit those fields. On
success the middleware emits an http_request_completed access entry; on
exception it emits an ERROR with full request context plus a JSON 500.

We pass access_log=False to uvicorn.Config so uvicorn's own access logger
doesn't duplicate the access entry the middleware emits.
"""

import threading
import time
import urllib.request
import urllib.error

import rahm
from rahm.starlette import uvicorn_log_config, RahmHttpMiddleware

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route


async def hello(request):
    # bind a field inside the active scope — every later log line in this request gets it
    rahm.log.bind(user_id='u_42')
    rahm.log.info('greeting', 'saying hello')
    return PlainTextResponse('hello')


async def boom(request):
    raise RuntimeError('database connection lost')


app = Starlette(
    routes=[Route('/', hello), Route('/boom', boom)],
    middleware=[Middleware(RahmHttpMiddleware)],
)

config = uvicorn.Config(
    app,
    host='127.0.0.1',
    port=8765,
    log_config=uvicorn_log_config(),
    access_log=False,
)

server = uvicorn.Server(config)
thread = threading.Thread(target=server.run, daemon=True)
thread.start()

while not server.started:
    time.sleep(0.05)

rahm.log.info('server_started', 'server is up, firing requests')

# baseline request — middleware generates a ULID trace_id
urllib.request.urlopen('http://127.0.0.1:8765/').read()

# client-supplied trace id — middleware echoes it back in X-Trace-Id
req = urllib.request.Request('http://127.0.0.1:8765/', headers={'X-Trace-Id': 'demo-trace-001'})
with urllib.request.urlopen(req) as r:
    assert r.headers.get('X-Trace-Id') == 'demo-trace-001'

try:
    urllib.request.urlopen('http://127.0.0.1:8765/missing', timeout=2)
except urllib.error.HTTPError:
    pass

try:
    urllib.request.urlopen('http://127.0.0.1:8765/boom?user_id=42&tenant=acme', timeout=2)
except urllib.error.HTTPError:
    pass

server.should_exit = True
thread.join(timeout=5)

rahm.log.info('demo_complete', 'done')
