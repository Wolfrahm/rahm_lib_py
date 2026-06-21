import importlib.util
import rahm.log

# import starlette module when starlette is available (optional extra)
spec = importlib.util.find_spec('starlette')
if spec is not None:
    import rahm.starlette

# log
logger = rahm.log.Logger()
log = logger.get()

