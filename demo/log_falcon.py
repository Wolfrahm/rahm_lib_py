"""Demo: real Falcon WSGI app served by Granian with the rahm middleware + error handler.

Granian is the production server, so this demo runs the rahm integration on the
exact runtime used in prod — confirming the error story (uncaught exception ->
one ERROR entry + JSON 500, access log suppressed) behaves identically there.

Granian is multi-process: it spawns worker processes (spawn start method on
macOS) that import the `demo.log_falcon:app` target. The orchestration below is
guarded by `if __name__ == '__main__'` so worker processes only build the app —
they never re-run the request-firing block. Granian's `serve()` blocks the main
thread, so a background thread fires the requests and then trips Granian's
interrupt (the same hook its signal handlers use) to make `serve()` return.

For ASGI deployments use `RahmFalconAsyncMiddleware` + `rahm_error_handler_async`
against `falcon.asgi.App`, served with `interface=Interfaces.ASGI`.
"""
import socket
import threading
import time
import urllib.error
import urllib.request

import falcon
import rahm
from rahm.falcon import RahmFalconMiddleware, rahm_error_handler

from granian.server import Server
from granian.constants import Interfaces


class Hello:
    def on_get(self, req, resp):
        # bind a field inside the active scope — later log lines in this request get it
        rahm.log.bind(user_id='u_42')
        rahm.log.info('greeting', 'saying hello')
        resp.text = 'hello'


class Boom:
    def on_get(self, req, resp):
        raise RuntimeError('database connection lost')


app = falcon.App(middleware=[RahmFalconMiddleware()])
app.add_error_handler(Exception, rahm_error_handler)
app.add_route('/', Hello())
app.add_route('/boom', Boom())


def _wait_until_bound(host, port, timeout=10.0):
    # Granian's main process binds the listening socket before workers are ready;
    # a raw connect tells us the port is up without generating an HTTP log line.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)


def _fire_requests(server):
    _wait_until_bound('127.0.0.1', 8765)

    rahm.log.info('server_started', 'server is up, firing requests')

    # baseline request — middleware generates a ULID trace_id. Generous timeout:
    # the first request may wait in the listen backlog until a worker is ready.
    urllib.request.urlopen('http://127.0.0.1:8765/', timeout=10).read()

    # client-supplied trace id — middleware echoes it back in X-Trace-Id
    req = urllib.request.Request('http://127.0.0.1:8765/', headers={'X-Trace-Id': 'demo-trace-001'})
    with urllib.request.urlopen(req) as r:
        assert r.headers.get('X-Trace-Id') == 'demo-trace-001'

    # 404 — Falcon's default HTTPNotFound handler renders the response, middleware still logs access
    try:
        urllib.request.urlopen('http://127.0.0.1:8765/missing', timeout=2)
    except urllib.error.HTTPError:
        pass

    # uncaught exception — error handler emits ERROR + 500
    try:
        urllib.request.urlopen('http://127.0.0.1:8765/boom?user_id=42&tenant=acme', timeout=2)
    except urllib.error.HTTPError:
        pass

    rahm.log.info('demo_complete', 'done')
    # trip the same interrupt Granian's signal handlers use; serve() unblocks
    # and runs its graceful shutdown.
    server.signal_handler_interrupt()


if __name__ == '__main__':
    server = Server(
        target='demo.log_falcon:app',
        address='127.0.0.1',
        port=8765,
        interface=Interfaces.WSGI,
        workers=1,
        log_enabled=False,
    )
    threading.Thread(target=_fire_requests, args=(server,), daemon=True).start()
    server.serve()
