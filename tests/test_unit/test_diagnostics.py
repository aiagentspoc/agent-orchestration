"""Unit tests for full-fidelity remote-error capture (Phase 6, Batch 3; PLAN §2.10 / D22).

These tests build **genuine** provider exceptions — ``openai.RateLimitError`` on a
real ``httpx.Response`` — rather than hand-rolled stand-ins, because the whole
point of :mod:`src.diagnostics` is that it knows the real attribute surface.
"""

import httpx
import openai
import pytest
from strands.types.exceptions import StructuredOutputException

from src.diagnostics import describe_exception, format_traceback
from src.schemas import RemoteErrorDetail

_ERROR_BODY: dict[str, object] = {
    "message": "Rate limit reached for gpt-5.4 in organization org-abc on tokens per min.",
    "type": "rate_limit_error",
    "code": "rate_limit_exceeded",
    "param": None,
}


def _rate_limit_error(message: str | None = None) -> openai.RateLimitError:
    """Build a real ``openai.RateLimitError`` carrying a 429 response."""
    request = httpx.Request("POST", "https://strong.example.invalid/openai/v1/chat/completions")
    response = httpx.Response(
        429,
        request=request,
        headers={"x-request-id": "req_abc123"},
        json={"error": _ERROR_BODY},
    )
    return openai.RateLimitError(
        message or str(_ERROR_BODY["message"]),
        response=response,
        body=_ERROR_BODY,
    )


def test_describe_exception_extracts_openai_status_error_fields() -> None:
    """HTTP status, provider code/type, request ID and body all survive into the record."""
    detail = describe_exception(_rate_limit_error())

    assert isinstance(detail, RemoteErrorDetail)
    assert detail.status_code == 429
    assert detail.provider_code == "rate_limit_exceeded"
    assert detail.provider_type == "rate_limit_error"
    assert detail.request_id == "req_abc123"
    assert detail.body is not None
    assert "rate_limit_exceeded" in detail.body
    assert detail.cause_chain and "RateLimitError" in detail.cause_chain[0]


def test_describe_exception_walks_cause_chain() -> None:
    """A Strands wrapper must not hide the provider error underneath it."""
    provider_error = _rate_limit_error()
    try:
        try:
            raise provider_error
        except openai.RateLimitError as exc:
            raise StructuredOutputException("Failed to produce structured output") from exc
    except StructuredOutputException as wrapper:
        detail = describe_exception(wrapper)

    # The outermost exception carries none of these; only the chain walk finds them.
    assert detail.status_code == 429
    assert detail.provider_code == "rate_limit_exceeded"
    assert detail.request_id == "req_abc123"
    assert len(detail.cause_chain) == 2
    assert "StructuredOutputException" in detail.cause_chain[0]
    assert "RateLimitError" in detail.cause_chain[1]


def test_describe_exception_handles_plain_exception() -> None:
    """A non-provider exception yields nulls, not a crash inside the error path."""
    detail = describe_exception(ValueError("nothing remote about this"))

    assert detail.status_code is None
    assert detail.provider_code is None
    assert detail.provider_type is None
    assert detail.request_id is None
    assert detail.body is None
    assert detail.cause_chain == ["builtins.ValueError: nothing remote about this"]


def test_describe_exception_never_truncates_message() -> None:
    """D22: the provider message reaches the record verbatim, however long."""
    long_message = "Rate limit reached for gpt-5.4 in organization org-abc. " * 60
    detail = describe_exception(_rate_limit_error(long_message))

    assert long_message in detail.cause_chain[0]
    assert len(detail.cause_chain[0]) > len(long_message)


def test_format_traceback_includes_the_full_cause_chain() -> None:
    """The formatted traceback carries both frames and the chaining explanation."""
    try:
        try:
            raise _rate_limit_error()
        except openai.RateLimitError as exc:
            raise StructuredOutputException("wrapper") from exc
    except StructuredOutputException as wrapper:
        formatted = format_traceback(wrapper)

    assert "Traceback (most recent call last)" in formatted
    assert "RateLimitError" in formatted
    assert "StructuredOutputException" in formatted
    assert "direct cause" in formatted


def test_format_traceback_of_a_never_raised_exception_is_still_useful() -> None:
    """An exception with no ``__traceback__`` still formats to its type and message."""
    formatted = format_traceback(ValueError("never raised"))

    assert "ValueError" in formatted
    assert "never raised" in formatted


@pytest.mark.parametrize(
    "exc",
    [
        openai.APIConnectionError(request=httpx.Request("POST", "https://example.invalid/v1/x")),
        openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid/v1/x")),
    ],
)
def test_describe_exception_handles_transport_errors_without_a_response(exc: Exception) -> None:
    """Connection and timeout errors carry no HTTP response; capture must not assume one."""
    detail = describe_exception(exc)

    assert detail.status_code is None
    assert detail.cause_chain
    assert "openai" in detail.cause_chain[0]
