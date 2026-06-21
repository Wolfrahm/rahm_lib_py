import os
import sys
import logging
import threading
import contextvars
import json
import datetime
import traceback
import pprint
import textwrap


# active scope dict for the current task; mutated in place by bind/unbind.
# asyncio child tasks inherit the parent's dict by reference (so trace_id etc. flows
# down to subtasks). Concurrent *requests* are isolated because each request handler
# runs in its own context and the wrapper calls _scope_var.set(...) fresh.
_scope_var = contextvars.ContextVar('rahm_log_scope', default=None)

_LIBRARY_SET = frozenset({'timestamp', 'application', 'environment', 'file', 'line'})
_CALLER_SET = frozenset({'severity', 'domain', 'event', 'message'})
_RESERVED_KWARGS = frozenset({'include', 'exclude'})  # per-call only; never bindable, never field names


def _reject_reserved(fields, what):
    for name in fields:
        if name in _LIBRARY_SET:
            raise ValueError(f"rahm.log: {name!r} is library-set and can't be {what}")
        if name in _CALLER_SET:
            raise ValueError(f"rahm.log: {name!r} is a caller-set mandatory field and must be passed per call, not {what}")
        if name in _RESERVED_KWARGS:
            raise ValueError(f"rahm.log: {name!r} is a reserved kwarg name and can't be {what}")


# spec 8.4: scope fields are filtered against the domain's allow-list at log time.
# `None` means "no restriction" — all scope fields pass through.
def _domain_allow(domain, level):
    if domain == 'system':
        return None
    if domain == 'auth' and level == logging.WARNING:
        return None
    if domain == 'auth' and level == logging.INFO:
        return frozenset({'trace_id', 'user_id'})
    if domain in ('transaction', 'metric'):
        return frozenset({'trace_id', 'resource_id'})
    return None


class _ScopeContext:

    def __init__(self, fields):
        self._fields = fields
        self._token = None

    def __enter__(self):
        if _scope_var.get() is not None:
            raise RuntimeError("rahm.log: a scope is already active for this task")
        self._token = _scope_var.set(dict(self._fields))
        return self

    def __exit__(self, exc_type, exc_value, tb):
        _scope_var.reset(self._token)


class _BindContext:

    # snapshot is {key: (was_present, old_value)} so `with bind(...)` restores prior
    # state on exit — not just deletes the bound keys.
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        scope = _scope_var.get()
        if scope is None:
            return
        for k, (was_present, old) in self._snapshot.items():
            if was_present:
                scope[k] = old
            else:
                scope.pop(k, None)


class RahmLogger(logging.Logger):

    # stacklevel=3: from inside super().log() the chain is _emit (1) → severity method (2) → caller (3),
    # so file/line in the record points at the user's call site instead of our wrapper.
    def _emit(self, level, event, message, **fields):
        if 'extra' in fields:
            raise TypeError("rahm.log: pass custom fields as kwargs, not extra={...}")
        exc_info = fields.pop('exc_info', None)
        stack_info = fields.pop('stack_info', False)
        include = set(fields.pop('include', ()))
        exclude = set(fields.pop('exclude', ()))
        # spec 9: error/fatal inside an except block auto-capture the active exception.
        if level in (logging.ERROR, logging.CRITICAL):
            active = sys.exc_info()
            if active[0] is not None:
                exc_info = active
        domain = fields.pop('domain', 'system')
        domain = self._validate_domain(level, domain)
        scope = _scope_var.get() or {}
        for name in fields:
            if name in scope:
                raise ValueError(f"attribute {name!r} already set in scope")
        # spec 8.4: drop scope fields not in the domain allow-list. per-call args bypass.
        # include= rescues a scope field that would be dropped; exclude= drops a scope field
        # that would be kept. exclude wins on collision.
        allowed = _domain_allow(domain, level)
        if allowed is not None:
            scope = {k: v for k, v in scope.items() if (k in allowed or k in include) and k not in exclude}
        elif exclude:
            scope = {k: v for k, v in scope.items() if k not in exclude}
        extra = {'event': event, 'domain': domain, **scope, **fields}
        super().log(level, message, extra=extra, exc_info=exc_info, stack_info=stack_info, stacklevel=3)


    # spec 8.4: only system|auth|metric|transaction are valid; debug/error/fatal require system.
    # misuses are coerced to system and surfaced as a warning so the call site can be fixed.
    def _validate_domain(self, level, domain):
        if domain not in ('system', 'auth', 'metric', 'transaction'):
            self._log(
                logging.WARNING,
                f"rahm.log: unknown domain {domain!r}, coercing to 'system'",
                (),
                extra={'event': 'rahm_misuse', 'domain': 'system'},
                stacklevel=4,
            )
            return 'system'
        if level in (logging.DEBUG, logging.ERROR, logging.CRITICAL) and domain != 'system':
            severity = logging.getLevelName(level).lower()
            self._log(
                logging.WARNING,
                f"rahm.log: domain={domain!r} not valid with severity={severity!r}, coercing to 'system'",
                (),
                extra={'event': 'rahm_misuse', 'domain': 'system'},
                stacklevel=4,
            )
            return 'system'
        return domain

    def debug(self, event, message, **fields):    self._emit(logging.DEBUG, event, message, **fields)
    def info(self, event, message, **fields):     self._emit(logging.INFO, event, message, **fields)
    def warning(self, event, message, **fields):  self._emit(logging.WARNING, event, message, **fields)
    def error(self, event, message, **fields):    self._emit(logging.ERROR, event, message, **fields)
    def critical(self, event, message, **fields): self._emit(logging.CRITICAL, event, message, **fields)
    fatal = critical

    def exception(self, event, message, **fields):
        fields.setdefault('exc_info', True)
        self._emit(logging.ERROR, event, message, **fields)


    def scope(self, **fields):
        _reject_reserved(fields, 'bound to a scope')
        return _ScopeContext(fields)


    def bind(self, **fields):
        scope = _scope_var.get()
        if scope is None:
            raise RuntimeError("rahm.log: no active scope; open one with rahm.log.scope(...)")
        _reject_reserved(fields, 'bound to a scope')
        snapshot = {k: (k in scope, scope.get(k)) for k in fields}
        scope.update(fields)
        return _BindContext(snapshot)


    def unbind(self, name):
        scope = _scope_var.get()
        if scope is None:
            raise RuntimeError("rahm.log: no active scope; open one with rahm.log.scope(...)")
        if name not in scope:
            raise KeyError(f"rahm.log: {name!r} is not bound in the active scope")
        del scope[name]


class Logger:

    def __init__(self):
        self.logger = self.set_logger()

        # set hooks
        sys.excepthook = self.handle_exception
        sys.unraisablehook = self.handle_unraisable
        threading.excepthook = self.handle_threading_exception


    def set_logger(self):

        # render CRITICAL as "FATAL" — convention here: if it stops the program, it's fatal
        logging.addLevelName(logging.CRITICAL, 'FATAL')

        # set format
        match os.environ.get('RAHM_LOG_FORMAT', 'json').lower():
            case 'text':
                formatter = LocalFormatter()
            case 'json':
                formatter = JsonFormatter()
            case 'logfmt':
                formatter = LogfmtFormatter()
            case _:
                raise ValueError('Incorrect format name in the RAHM_LOG_FORMAT environment variable')

        # set log level
        match os.environ.get('RAHM_LOG_SEVERITY', 'info').lower():
            case 'debug':
                level = logging.DEBUG
            case 'info':
                level = logging.INFO
            case 'warning':
                level = logging.WARNING
            case 'error':
                level = logging.ERROR
            case 'fatal':
                level = logging.CRITICAL
            case 'none':
                # above CRITICAL — nothing emitted by the standard log methods passes the threshold
                level = logging.CRITICAL + 1
            case _:
                raise ValueError('Incorrect severity name in the RAHM_LOG_SEVERITY environment variable')

        # create handler — stdout is the wire; stderr is reserved for crash output
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)

        # only the 'rahm' logger uses our subclass; restore the default so other libs
        # (uvicorn, etc.) get plain logging.Logger and aren't affected by our signature.
        logging.setLoggerClass(RahmLogger)
        logger = logging.getLogger('rahm')
        logging.setLoggerClass(logging.Logger)
        logger.setLevel(level)
        logger.addHandler(handler)
        # don't bubble records to the root logger — frameworks like Robyn install
        # their own root handler in verbose mode and would re-print every record.
        logger.propagate = False

        return logger


    def get(self):
        return self.logger


    # uncaught main-thread exception → process exits → FATAL
    def handle_exception(self, exc_type, exc_value, exc_traceback):

        if exc_type.__name__ in ['KeyboardInterrupt', 'SystemExit']:
            self.logger.info('application_closed', f'Application closed by {exc_type.__name__}')
        else:
            self.logger.critical('uncaught_exception', 'Uncaught exception', exc_info=(exc_type, exc_value, exc_traceback))


    # exception during GC/finalization → process keeps running → ERROR, not FATAL
    def handle_unraisable(self, exc):

        self.logger.error('unraisable_exception', 'Unraisable exception', exc_info=(exc.exc_type, exc.exc_value, exc.exc_traceback), error_err_msg=exc.err_msg, error_object=exc.object)


    # only the worker thread dies, main thread keeps running → ERROR, not FATAL
    def handle_threading_exception(self, args):

        self.logger.error('uncaught_threading_exception', 'Uncaught threading exception', exc_info=(args.exc_type, args.exc_value, args.exc_traceback), error_thread=args.thread)


class LocalFormatter(logging.Formatter):

    # colors https://gist.github.com/fnky/458719343aabd01cfb17a3a4f7296797
    red = '\x1b[38;5;196m'
    orange = '\x1b[38;5;208m'
    green = '\x1b[38;5;40m'
    blue = '\x1b[38;5;81m'
    bold = '\x1b[1m'
    reset = '\x1b[0m'

    # folded into the title line and skipped in the per-row loop
    _SUPPRESSED_FIELDS = ('severity', 'message', 'event', 'domain')
    # records produced by these hooks carry a generic `message` that just restates
    # the event ("Uncaught exception", …) — fall back to error_message for the body
    _HOOK_FUNCTIONS = ('handle_exception', 'handle_unraisable', 'handle_threading_exception')

    def format(self, record):
        parser = LogRecordParser()
        log = parser.filter(parser.to_dict(record))
        # spec 5: 64 KiB cap applies to every format. truncation marker dicts
        # render via the dict branch in _render_field_value.
        _truncate_to_fit(log)
        # drop deploy-wide constants from CLI output — useful in JSON, noise in dev terminal
        for k in ('timestamp', 'application', 'environment'):
            log.pop(k, None)

        color = self._pick_color(log['severity'])
        key_width = self._compute_key_width(log)

        reset = self.reset
        col1_level = f"{color + log['severity'].upper():<{7 + len(color)}}{'|' + reset:<{2 + len(reset)}}"
        col1_blank = f"{color + '':<{7 + len(color)}}{'|' + reset:<{2 + len(reset)}}"
        col2_blank = f"{'':<{key_width}}{':':<2}"

        output = [col1_level + self._build_title(log, key_width)]
        for key, value in log.items():
            if key in self._SUPPRESSED_FIELDS:
                continue
            if 'function' not in log and key in ('file', 'line'):
                continue
            rendered = self._render_field_value(key, value)
            output += self._format_data(col1_blank, col2_blank, key, rendered, key_width)
        output.append('')
        return '\n'.join(output)


    def _pick_color(self, severity):
        return {
            'fatal': self.red,
            'error': self.red,
            'warning': self.orange,
            'info': self.green,
            'debug': self.blue,
        }.get(severity, '')


    # key column width auto-adapts to the longest key actually shown
    # (event in the title + every key that survives the row loop).
    # +1 so every row has at least one space between key and colon.
    def _compute_key_width(self, log):
        displayed = [
            k for k in log
            if k not in self._SUPPRESSED_FIELDS
            and not ('function' not in log and k in ('file', 'line'))
        ]
        return max([len(k) for k in displayed] + [len(log.get('event', ''))]) + 1


    def _build_title(self, log, key_width):
        bold, reset = self.bold, self.reset
        is_hook = log.get('function') in self._HOOK_FUNCTIONS
        body = log['error_message'] if is_hook and 'error_message' in log else log['message']
        # only event and body are bold; the separator, file:line, and domain stay
        # normal so the eye lands on what actually identifies the entry.
        title = bold + f"{log.get('event', ''):<{key_width}}" + reset + ': ' + bold + body + reset
        if 'function' not in log:
            title += ' - ' + log['file'] + ':' + log['line']
        if 'domain' in log:
            title += ' - ' + log['domain']
        return title


    # decide what string to display for a field value — multi-line wrapping is
    # done downstream by _format_data, so this just shapes the value.
    def _render_field_value(self, key, value):
        bold, reset = self.bold, self.reset
        if key == 'error_trace':
            # bold the final frame so the eye lands on the failing call site
            lines = []
            last = len(value) - 1
            for i, frame in enumerate(value):
                start, end = (bold, reset) if i == last else ('', '')
                for line in frame.split('\n'):
                    lines.append(start + line + end)
            return '\n'.join(lines)
        if key in ('error_message', 'req_url'):
            return bold + str(value) + reset
        if isinstance(value, dict):
            return pprint.pformat(value, indent=2, depth=4)
        if isinstance(value, str) and self._is_json(value):
            return json.dumps(json.loads(value), indent=2, default=str)
        return str(value)


    def _is_json(self, data):
        try:
            json.loads(data)
        except ValueError:
            return False
        return True


    # format long and/or multiline strings for CLI output
    def _format_data(self, col1_blank, col2_blank, key, value, key_width):
        output = []
        key_printed = False
        for line in value.split('\n'):
            indent = ''
            indent_lenght = len(line) - len(line.lstrip())
            text_lenght = 76 - indent_lenght
            indent = ' ' * indent_lenght
            line = line.lstrip()  # remove indent to add it later to every split line
            line = '\n'.join(textwrap.wrap(line, width=text_lenght))
            lines = line.split('\n')

            for _key, _line in enumerate(lines):

                if key_printed is True:
                    extra_indent = '  '
                    if _key == 0:
                        extra_indent = ''
                    output.append(col1_blank + col2_blank + indent + extra_indent + _line)
                else:
                    output.append(col1_blank + f"{key:<{key_width}}{':':<2}" + indent + _line)
                    key_printed = True
        return output


# canonical field order shared by JsonFormatter and LogfmtFormatter.
# customers override `field_order` on their subclass to change it.
_CANONICAL_FIELD_ORDER = [
    'timestamp',
    'severity',
    'application',
    'environment',
    'domain',
    'event',
    'message',
    'file',
    'line',
    'function',
    'thread',
    'thread_name',
    'process',
    'process_name',
    'task_name',
    'error_type',
    'error_message',
    'error_trace',
    'error_err_msg',
    'error_object',
    'error_thread',
]


# 64 KiB cap (spec 5): replace the largest top-level field with a truncation
# marker until the entry fits. JSON-equivalent bytes are the yardstick across
# all formats — simpler and predictable, even if the actual serialized output
# for text/logfmt is a bit smaller or bigger.
def _truncate_to_fit(log, limit=65536):
    while len(json.dumps(log, default=str).encode('utf-8')) > limit:
        candidates = {
            k: len(json.dumps(v, default=str).encode('utf-8'))
            for k, v in log.items()
            if not (isinstance(v, dict) and v.get('truncated') is True)
        }
        if not candidates:
            break
        biggest = max(candidates, key=candidates.get)
        log[biggest] = {'truncated': True, 'original_bytes': candidates[biggest]}


class JsonFormatter(logging.Formatter):

    field_order = _CANONICAL_FIELD_ORDER

    def format(self, record):

        parser = LogRecordParser()
        log = parser.to_dict(record)
        log = parser.filter(log)

        if 'timestamp' in log:
            log['timestamp'] = self.format_timestamp(log['timestamp'])

        self.transform_fields(log)
        self.rename_keys(log)

        ordered = {key: log.pop(key) for key in self.field_order if key in log}
        ordered.update(log)

        _truncate_to_fit(ordered)

        return json.dumps(ordered, default=str)


    # subclass hooks below — override only what differs for a customer format.

    def format_timestamp(self, dt):
        return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


    # add, remove, or rewrite fields — no-op by default; customers override to extend
    def transform_fields(self, log):
        pass


    # rename standard keys to customer vocabulary (e.g. severity → level)
    def rename_keys(self, log):
        pass


# logfmt: one line of key=value per entry. Bare value unless it's empty or
# contains whitespace / `"` / `=` / `\` — then double-quoted with `\\`, `\"`,
# `\n`, `\r`, `\t` escaped. Nested values (dicts, lists) are JSON-stringified
# inside quotes so the entry stays single-line but the structure round-trips.
_LOGFMT_QUOTE_TRIGGERS = ' \t\n\r"=\\'

def _logfmt_quote(s):
    s = s.replace('\\', '\\\\').replace('"', '\\"')
    s = s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
    return '"' + s + '"'


def _logfmt_value(v):
    if v is None:
        return 'null'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (dict, list, tuple)):
        return _logfmt_quote(json.dumps(v, default=str))
    s = str(v)
    if not s or any(c in s for c in _LOGFMT_QUOTE_TRIGGERS):
        return _logfmt_quote(s)
    return s


class LogfmtFormatter(logging.Formatter):

    field_order = _CANONICAL_FIELD_ORDER

    def format(self, record):

        parser = LogRecordParser()
        log = parser.to_dict(record)
        log = parser.filter(log)

        if 'timestamp' in log:
            log['timestamp'] = self.format_timestamp(log['timestamp'])

        self.transform_fields(log)
        self.rename_keys(log)

        ordered = {key: log.pop(key) for key in self.field_order if key in log}
        ordered.update(log)

        _truncate_to_fit(ordered)

        return ' '.join(f'{k}={_logfmt_value(v)}' for k, v in ordered.items())


    # subclass hooks — same shape as JsonFormatter so customers can swap formats
    # without re-learning the API.

    def format_timestamp(self, dt):
        return dt.isoformat(timespec='milliseconds').replace('+00:00', 'Z')


    def transform_fields(self, log):
        pass


    def rename_keys(self, log):
        pass


class LogRecordParser:

    def to_dict(self, record):

        # Accessing `logging.LogRecord` attributes
        log_record = {
            'severity': getattr(record, 'levelname', None).lower(),
            'domain': getattr(record, 'domain', 'system'),
            'event': getattr(record, 'event', None),
            'message': str(getattr(record, 'msg', None)),

            'timestamp': datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc),
            'application': os.environ.get('RAHM_APPLICATION', 'unknown'),
            'environment': os.environ.get('RAHM_ENVIRONMENT', 'unknown'),

            'file': getattr(record, 'filename', None),
            'module': getattr(record, 'module', None),
            'function': getattr(record, 'funcName', None),
            'line': str(getattr(record, 'lineno', None)),
            'logger_name': getattr(record, 'name', None),
            'logger_path': getattr(record, 'pathname', None),

            'thread': str(getattr(record, 'thread', None)),
            'thread_name': getattr(record, 'threadName', None),
            'process': str(getattr(record, 'process', None)),
            'process_name': getattr(record, 'processName', None),
            'task_name': getattr(record, 'taskName', None)
        }

        # extra fiels
        for key, value in record.__dict__.items():
            if key not in ['args', 'created', 'exc_info', 'exc_text', 'filename', 'funcName', 'getMessage', 'levelname', 'levelno', 'lineno', 'module', 'msecs', 'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated', 'stack_info', 'taskName', 'thread', 'threadName']:
                log_record[key] = value

        # match stdlib's truthy convention — None, False, and 0 all mean "no exception"
        if record.exc_info:
            if record.exc_info[0] is not None:
                log_record['error_type'] = record.exc_info[0].__name__
            if record.exc_info[1] is not None:
                log_record['error_message'] = str(record.exc_info[1])
            if record.exc_info[2] is not None:
                backtrace = traceback.extract_tb(record.exc_info[2])
                tb = traceback.format_list(backtrace)

                # clean up
                _backtrace = []
                for line in tb:
                    line = line.strip()
                    line = line.replace('File "', '', 1).replace('", line ', ':', 1).replace(', in ', ':', 1)

                    # functionality to shorten backtraces by remove the lines who point to modules
                    # I'm in doubt if this a good idea, because it will also shorten the backtrace for our own modules
                    # if os.environ['RAHM_LOG_MODULE_BACKTRACE'] == 'false' and line[:4] == '/opt':
                    #     continue

                    _backtrace.append(line)

                log_record['error_trace'] = _backtrace

        return log_record


    # framework bridges where the python logger name is rahm-internal noise,
    # not something the developer set themselves — strip the meta fields.
    _BRIDGE_LOGGER_PREFIXES = ('rahm', 'uvicorn', 'robyn', 'actix_server', 'actix_web')

    def filter(self, log_record):

        name = log_record['logger_name'] or ''
        if any(name == p or name.startswith(p + '.') for p in self._BRIDGE_LOGGER_PREFIXES):
            del(log_record['logger_name'], log_record['logger_path'])

        if 'function' in log_record and log_record['function'] in ['handle_exception', 'handle_unraisable', 'handle_threading_exception', 'dispatch']:
            del(log_record['module'], log_record['file'], log_record['line'])
        else:
            del(log_record['module'], log_record['function'], log_record['thread'], log_record['thread_name'], log_record['process'], log_record['process_name'], log_record['task_name'])

        return log_record
