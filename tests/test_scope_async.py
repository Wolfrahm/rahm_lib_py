"""Per-task isolation: contextvars (not threading.local). Child tasks inherit."""
import asyncio
import json

import pytest
import rahm

from .conftest import read_logs


async def test_child_task_inherits_parent_scope(capture_logs):
    """asyncio child tasks see parent's scope (by-reference) so trace_id flows down."""
    async def child():
        rahm.log.info('child_evt', 'from child')

    with rahm.log.scope(trace_id='t1'):
        await asyncio.create_task(child(), name='child-task')

    logs = read_logs(capture_logs)
    assert logs[0]['trace_id'] == 't1'


async def test_concurrent_scopes_dont_leak(capture_logs):
    """Two top-level tasks each open their own scope; neither sees the other's fields."""
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def task_a():
        with rahm.log.scope(trace_id='A'):
            started.set()
            await proceed.wait()
            rahm.log.info('a_evt', 'from a')

    async def task_b():
        # wait for A to be inside its scope, then run B in parallel
        await started.wait()
        with rahm.log.scope(trace_id='B'):
            rahm.log.info('b_evt', 'from b')
        proceed.set()

    # important: each top-level task must run in its OWN context so the scope
    # contextvar is isolated between them.
    ctx_a, ctx_b = __import__('contextvars').copy_context(), __import__('contextvars').copy_context()
    t_a = asyncio.create_task(task_a(), context=ctx_a)
    t_b = asyncio.create_task(task_b(), context=ctx_b)
    await asyncio.gather(t_a, t_b)

    logs = read_logs(capture_logs)
    by_event = {log['event']: log for log in logs}
    assert by_event['a_evt']['trace_id'] == 'A'
    assert by_event['b_evt']['trace_id'] == 'B'


async def test_child_task_can_open_its_own_scope_after_parent_exits(capture_logs):
    async def child():
        # parent's scope already closed by the time we run; we can open our own
        with rahm.log.scope(trace_id='child_t'):
            rahm.log.info('child_evt', 'from child')

    with rahm.log.scope(trace_id='parent_t'):
        pass
    await asyncio.create_task(child())

    [log] = read_logs(capture_logs)
    assert log['trace_id'] == 'child_t'
