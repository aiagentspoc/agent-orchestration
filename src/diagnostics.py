"""Full-fidelity remote-error capture for the pipeline (D22 / PLAN §2.10).

For this proof of concept **nothing about a remote failure is truncated,
summarised, sanitised, swallowed or retried**: a real project should start from
complete information about how and how often the provider and the substrate
actually fail, and a retry policy is a decision to be made *from* that data
rather than one baked in before it exists.

This module is the single place that knows provider-specific attribute names.
``src/orchestrator.py`` must import no concrete provider (PLAN §5, must-not 16),
so it asks here instead and receives a typed
:class:`~src.schemas.RemoteErrorDetail`.

The attribute surfaces it walks, verified against the installed packages:

* ``openai.APIStatusError`` — ``status_code``, ``response``, ``body``,
  ``request_id``, ``code``, ``param``, ``type``; subclasses include
  ``RateLimitError``, ``AuthenticationError``, ``BadRequestError`` and
  ``InternalServerError``. ``APIConnectionError`` / ``APITimeoutError`` carry a
  request but **no** response, so nothing here may assume one.
* ``strands.types.exceptions`` — ``EventLoopException``,
  ``ModelThrottledException``, ``StructuredOutputException``,
  ``ContextWindowOverflowException``, ``MaxTokensReachedException`` and
  ``MCPClientInitializationError`` all wrap the underlying provider error rather
  than exposing its fields, which is exactly why the ``__cause__`` walk exists.
"""

import traceback
from collections.abc import Iterator

from .schemas import RemoteErrorDetail

__all__ = ["describe_exception", "format_traceback", "qualified_type_name"]


def qualified_type_name(exc: BaseException) -> str:
    """Return the fully-qualified class name of ``exc``.

    Args:
        exc: Any exception.

    Returns:
        ``"module.ClassName"``, e.g. ``"openai.RateLimitError"``.
    """
    cls = type(exc)
    return f"{cls.__module__}.{cls.__qualname__}"


def _chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield ``exc`` and every exception beneath it, outermost first.

    Follows ``__cause__`` (explicit ``raise ... from``) and, when absent, the
    implicit ``__context__`` that Python sets inside an ``except`` block, so a
    wrapper raised without ``from`` still cannot hide the provider error.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        nxt = current.__cause__
        if nxt is None and not current.__suppress_context__:
            nxt = current.__context__
        current = nxt


def _response_body(exc: BaseException) -> str | None:
    """Read the raw HTTP response body off a provider error, if it has one.

    Prefers the verbatim wire text over the parsed ``body`` object, because the
    parsed form is a projection and D22 wants what the server actually sent.
    """
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            text = response.text
        except Exception as read_error:  # the reason is preserved in the body, never swallowed
            return f"<response body unavailable: {qualified_type_name(read_error)}: {read_error}>"
        if text:
            return str(text)
    body = getattr(exc, "body", None)
    if body is not None:
        return str(body)
    return None


def describe_exception(exc: BaseException) -> RemoteErrorDetail:
    """Extract every remote-call diagnostic reachable from ``exc``, verbatim.

    Walks the exception chain and takes the first non-``None`` value for each
    field, so a Strands wrapper around an ``openai`` error still yields the HTTP
    status code, the provider error code and type, and the request ID.

    Args:
        exc: The exception caught by the pipeline.

    Returns:
        A :class:`~src.schemas.RemoteErrorDetail`. Fields that no exception in
        the chain carries are ``None``; ``cause_chain`` always has at least one
        entry and is never truncated.
    """
    detail = RemoteErrorDetail()
    for current in _chain(exc):
        detail.cause_chain.append(f"{qualified_type_name(current)}: {current}")
        if detail.status_code is None:
            status_code = getattr(current, "status_code", None)
            detail.status_code = int(status_code) if isinstance(status_code, int) else None
        if detail.provider_code is None:
            code = getattr(current, "code", None)
            detail.provider_code = str(code) if code is not None else None
        if detail.provider_type is None:
            provider_type = getattr(current, "type", None)
            detail.provider_type = str(provider_type) if provider_type is not None else None
        if detail.request_id is None:
            request_id = getattr(current, "request_id", None)
            detail.request_id = str(request_id) if request_id is not None else None
        if detail.body is None:
            detail.body = _response_body(current)
    return detail


def format_traceback(exc: BaseException) -> str:
    """Format the full traceback of ``exc``, including its chained causes.

    Args:
        exc: The exception caught by the pipeline.

    Returns:
        The complete formatted traceback. An exception that was never raised has
        no ``__traceback__``; it still formats to its type and message.
    """
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
