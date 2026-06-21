"""Demo: real Falcon WSGI app with the rahm middleware + error handler.

Booted on a background thread with stdlib `wsgiref.simple_server` so the demo
stays self-contained (no extra runtime to install). The middleware opens a
rahm scope per request binding trace_id + http_method + http_path; the error
handler turns uncaught exceptions into an ERROR with full request context
plus a JSON 500.

For ASGI deployments use `RahmFalconAsyncMiddleware` + `rahm_error_handler_async`
against `falcon.asgi.App` — same surface, async signatures.
"""
import threading
import time
import urllib.error
import urllib.request
from wsgiref.simple_server import make_server, WSGIRequestHandler

import falcon
import rahm
from rahm.falcon import RahmFalconMiddleware, rahm_error_handler


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


# silence wsgiref's built-in stderr access log — rahm emits its own
class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        return


server = make_server('127.0.0.1', 8765, app, handler_class=_QuietHandler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()

# wsgiref accepts connections immediately; small yield to let the bind settle.
time.sleep(0.05)

rahm.log.info('server_started', 'server is up, firing requests')

# baseline request — middleware generates a ULID trace_id
urllib.request.urlopen('http://127.0.0.1:8765/').read()

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

server.shutdown()
thread.join(timeout=5)

rahm.log.info('demo_complete', 'done')
