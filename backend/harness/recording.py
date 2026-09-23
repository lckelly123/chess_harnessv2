"""Optional turn-scoped observation. No prompts, decisions or tools are changed."""

import asyncio
import inspect
from contextvars import ContextVar
from functools import wraps

# An observer is installed only by the positional runner. Match turns stay inert.
current_recorder = ContextVar("positional_pass_recorder", default=None)


async def complete_pass(client, state, **kwargs):
    recorder = current_recorder.get()
    if recorder is not None:
        await asyncio.to_thread(recorder.begin, state)
    response = await client.complete(**kwargs)
    if recorder is not None:
        await asyncio.to_thread(recorder.response, response)
    return response


def record_node(function):
    """Observe returned state, including retry/rollback events, or a terminal error."""
    if inspect.iscoroutinefunction(function):

        @wraps(function)
        async def asynchronous(*args, **kwargs):
            recorder = current_recorder.get()
            try:
                result = await function(*args, **kwargs)
            except BaseException as exc:
                if recorder is not None:
                    await asyncio.to_thread(recorder.fail, exc)
                raise
            if recorder is not None:
                await asyncio.to_thread(recorder.state, args[-1], result)
            return result

        return asynchronous

    @wraps(function)
    def synchronous(*args, **kwargs):
        recorder = current_recorder.get()
        try:
            result = function(*args, **kwargs)
        except BaseException as exc:
            if recorder is not None:
                recorder.fail(exc, rollback=bool(args[-1].get("pending_tools")))
            raise
        if recorder is not None:
            recorder.state(args[-1], result)
        return result

    return synchronous


def recorded_tool(function, *args, **kwargs):
    recorder = current_recorder.get()
    if recorder is None:
        return function(*args, **kwargs)
    index = recorder.tool_started(function, args, kwargs)
    try:
        result = function(*args, **kwargs)
    except Exception as exc:
        recorder.tool_finished(index, error=str(exc))
        raise
    recorder.tool_finished(index, result=result)
    return result
