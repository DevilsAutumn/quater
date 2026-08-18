"""Signature and type formatting helpers.

Handles griffe object resolution, signature/type string cleanup, and
the wrapping rules for callables shown in the reference pages.
"""

from __future__ import annotations

from typing import Any


def object_for(package: Any, symbol: str) -> Any:
    return resolve(package[symbol])


def resolve(obj: Any) -> Any:
    return getattr(obj, "target", obj)


def annotation(obj: Any) -> str:
    value = getattr(obj, "annotation", None)
    if value is None:
        return "object"
    return str(value)


def init_annotations(obj: Any) -> dict[str, str]:
    init = getattr(obj, "members", {}).get("__init__")
    if init is None:
        return {}
    target = resolve(init)
    parameters = getattr(target, "parameters", ())
    annotations: dict[str, str] = {}
    for parameter in parameters:
        name = getattr(parameter, "name", "")
        value = getattr(parameter, "annotation", None)
        if not name or name == "self" or value is None:
            continue
        annotations[name] = str(value)
    return annotations


def attribute_value(package: Any, symbol: str) -> str:
    value = getattr(object_for(package, symbol), "value", None)
    if value is None:
        return clean_signature(annotation(object_for(package, symbol)))
    return clean_signature(str(value))


def function_signature(obj: Any) -> str | None:
    signature_method = getattr(obj, "signature", None)
    if signature_method is None:
        return None
    return format_signature(clean_signature(str(signature_method())))


def class_signature(package: Any, symbol: str) -> str:
    obj = object_for(package, symbol)
    init = getattr(obj, "members", {}).get("__init__")
    if init is None:
        return symbol
    signature = function_signature(resolve(init))
    if signature is None:
        return symbol
    signature = signature.replace("__init__(", f"{symbol}(", 1)
    signature = signature.removesuffix(" -> None")
    return signature


def method_signature(package: Any, symbol: str, method: str) -> str:
    obj = object_for(package, symbol)
    member = getattr(obj, "members", {}).get(method)
    if member is None:
        raise SystemExit(f"Could not find {symbol}.{method}")
    signature = function_signature(resolve(member))
    if signature is None:
        raise SystemExit(f"Could not read signature for {symbol}.{method}")
    return signature


def callable_signature(package: Any, symbol: str) -> str:
    signature = function_signature(resolve(object_for(package, symbol)))
    if signature is None:
        raise SystemExit(f"Could not read signature for {symbol}")
    return signature


def code_block(code: str) -> list[str]:
    return ["```python", code, "```", ""]


def signature_block(signature: str) -> list[str]:
    return code_block(format_signature(signature))


def format_signature(signature: str, *, max_width: int = 88) -> str:
    if len(signature) <= max_width:
        return signature

    open_index = signature.find("(")
    close_index = signature.rfind(")")
    if open_index == -1 or close_index == -1 or close_index < open_index:
        return signature

    head = signature[:open_index]
    args = split_top_level_commas(signature[open_index + 1 : close_index])
    tail = signature[close_index + 1 :]
    if not args:
        return signature

    lines = [f"{head}("]
    lines.extend(f"    {argument}," for argument in args)
    lines.append(f"){tail}")
    return "\n".join(lines)


def clean_signature(value: str) -> str:
    replacements = {
        "mcp_docs_path: str | None | _Unset = _UNSET": (
            "mcp_docs_path: str | None = '/mcp/docs'"
        ),
        "docs_path: str | None | _Unset = _UNSET": ("docs_path: str | None = '/docs'"),
        "openapi_path: str | None | _Unset = _UNSET": (
            "openapi_path: str | None = '/openapi.json'"
        ),
        "request_id_header: str | None | _Unset = _UNSET": (
            "request_id_header: str | None = 'x-request-id'"
        ),
        "_empty_str_map()": "...",
        "_empty_metadata()": "...",
        "_MCP_PROTOCOL_VERSION": "'2025-11-25'",
        "Callable[['AccessLogEvent'], Awaitable[None]]": (
            "Callable[[AccessLogEvent], Awaitable[None]]"
        ),
        "_DEFAULT_METHODS": (
            "('DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT')"
        ),
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def clean_type(value: str) -> str:
    replacements = {
        "str | None | _Unset": "str | None",
    }
    for old, new in replacements.items():
        value = value.replace(old, new)
    return value


def split_top_level_commas(value: str) -> list[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    escaped = False
    for index, char in enumerate(value):
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char in "([{":
            depth += 1
            continue
        if char in ")]}":
            depth -= 1
            continue
        if char == "," and depth == 0:
            part = value[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1
    tail = value[start:].strip()
    if tail:
        parts.append(tail)
    return parts
