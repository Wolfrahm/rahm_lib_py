# Rahm Lib Py

A general framework for the Wolfrahm projects. Logging is the first capability; more will follow.

## Current capabilities

| Capability | Status   | Documentation                                                 |
|------------|----------|---------------------------------------------------------------|
| Logging    | shipping | [docs/logging.md](docs/logging.md)                            |
| Starlette  | shipping | [docs/starlette.md](docs/starlette.md) — `rahm.starlette`     |
| Falcon     | shipping | [docs/falcon.md](docs/falcon.md) — `rahm.falcon`              |
| Robyn      | shipping | [docs/robyn.md](docs/robyn.md) — `rahm.robyn`                 |

## Install

From GitHub, into your own project:

```sh
uv add "rahm @ git+https://github.com/Wolfrahm/rahm_lib_py.git"
uv add "rahm[starlette] @ git+https://github.com/Wolfrahm/rahm_lib_py.git"
uv add "rahm[falcon]    @ git+https://github.com/Wolfrahm/rahm_lib_py.git"
uv add "rahm[robyn]     @ git+https://github.com/Wolfrahm/rahm_lib_py.git"
uv add "rahm @ git+https://github.com/Wolfrahm/rahm_lib_py.git@v0.0.1"   # pinned to a tag
```

Each extra is independent — install only what you use.

Inside this repo (development):

```sh
uv sync                       # runtime only (logging)
uv sync --extra starlette     # + starlette + uvicorn
uv sync --extra falcon        # + falcon (WSGI + ASGI)
uv sync --extra robyn         # + robyn
```

## Hello world

```python
import rahm

rahm.log.info('order_placed', 'order placed', order_id='O-1001', amount=49.99)
rahm.log.error('payment_failed', 'payment failed', order_id='O-1001')
```

That's the whole logging surface in two lines. See [docs/logging.md](docs/logging.md) for everything else: env vars, output formats, domains, scopes, exception capture, uncaught hooks, customizing formatters.

## Demos

`demo/` holds runnable scripts you can `python -m`:

| Script                        | Capability   | What it shows                                                              |
|-------------------------------|--------------|----------------------------------------------------------------------------|
| `demo/log_cli.py`             | logging      | severities, scopes + bind/unbind, domain filtering, auto-capture, hooks    |
| `demo/log_json.py`            | logging      | vanilla `JsonFormatter` + a customer subclass                              |
| `demo/log_logfmt.py`          | logging      | vanilla `LogfmtFormatter` + a customer subclass                            |
| `demo/log_starlette.py`       | starlette    | uvicorn + Starlette + `RahmHttpMiddleware`                                 |
| `demo/log_falcon.py`          | falcon       | Falcon WSGI + `RahmFalconMiddleware` + `rahm_error_handler`                |
| `demo/log_robyn.py`           | robyn        | real Robyn server + `install_rahm(app)`                                    |

```sh
uv run --env-file .env python -m demo.log_cli
```

## Tests

```sh
uv run pytest
```

## License

MIT. Repository: <https://github.com/Wolfrahm/rahm_lib_py>.
