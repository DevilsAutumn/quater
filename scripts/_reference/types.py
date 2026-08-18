"""Type name rendering, links, and small string helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable

from _reference.pages import PAGES, ReferencePage
from _reference.signatures import clean_type


def slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return normalized.strip("-")


def symbol_anchor(value: str) -> str:
    if value == "__version__":
        return "symbol-version"
    return f"symbol-{slug(value)}"


def symbol_heading(value: str) -> str:
    return f"## {value} {{#{symbol_anchor(value)}}}"


def is_private_member(name: str) -> bool:
    return name.startswith("_")


def import_link(name: str, page: ReferencePage) -> str:
    target = f"./{page.slug}#{symbol_anchor(name)}"
    return f"[`{name}`]({target})"


def type_cell(value: str) -> str:
    text = clean_type(value)
    if not any(type_reference(match.group(0)) for match in type_words(text)):
        return f"`{table_code(text)}`"

    escaped = table_text(text)
    return re.sub(
        r"\b[A-Za-z_][A-Za-z0-9_]*\b",
        lambda match: type_token(match.group(0)),
        escaped,
    )


def type_name_cell(name: str) -> str:
    anchor = f'<span id="{type_anchor(name)}"></span>'
    link = public_type_reference(name)
    if link is not None:
        return f"{anchor}[`{name}`]({link})"
    return f"{anchor}`{name}`"


def type_token(name: str) -> str:
    link = type_reference(name)
    if link is None:
        return name
    return f"[`{name}`]({link})"


def type_words(value: str) -> Iterable[re.Match[str]]:
    return re.finditer(r"\b[A-Za-z_][A-Za-z0-9_]*\b", value)


def type_reference(name: str) -> str | None:
    public_link = public_type_reference(name)
    if public_link is not None:
        return public_link

    internal_links = {
        "HeaderItems": "/en/dev/reference/request#type-headeritems",
        "RequestBody": "/en/dev/reference/request#type-requestbody",
        "RequestContext": "/en/dev/reference/request#call-context",
        "Headers": "/en/dev/reference/request#headers",
        "QueryParams": "/en/dev/reference/request#queryparams",
        "Cookies": "/en/dev/reference/request#cookies",
        "SecurityMode": "/en/dev/reference/application#type-securitymode",
        "MaxBodySize": "/en/dev/reference/application#type-maxbodysize",
        "Authenticate": "/en/dev/reference/auth#type-authenticate",
        "AuditHook": "/en/dev/reference/application#type-audithook",
        "BeforeMiddleware": "/en/dev/reference/application#type-beforemiddleware",
        "AfterMiddleware": "/en/dev/reference/application#type-aftermiddleware",
        "AroundMiddleware": "/en/dev/reference/application#type-aroundmiddleware",
        "ExceptionHandlerEntry": (
            "/en/dev/reference/application#type-exceptionhandlerentry"
        ),
        "ResourceMap": "/en/dev/reference/resources#type-resourcemap",
        "ResourceProvider": "/en/dev/reference/resources#type-resourceprovider",
        "ResourceScope": "/en/dev/reference/resources#type-resourcescope",
        "ResponseBody": "/en/dev/reference/responses#type-responsebody",
        "RequestContent": "/en/dev/reference/testing#type-requestcontent",
        "JSONRPCID": "/en/dev/reference/testing#type-jsonrpcid",
        "SecretValue": "/en/dev/reference/auth#type-secretvalue",
    }
    return internal_links.get(name)


def public_type_reference(name: str) -> str | None:
    for page in PAGES:
        if name in page.symbols and name != "__version__":
            return f"/en/dev/reference/{page.slug}#{symbol_anchor(name)}"
    return None


def type_anchor(name: str) -> str:
    return f"type-{slug(name)}"


def table_code(value: str) -> str:
    return value.replace("|", "\\|")


def table_text(value: str) -> str:
    return value.replace("|", "\\|")


def context_row(name: str, type_name: str, description: str) -> str:
    return f"| `{name}` | {type_cell(type_name)} | {table_text(description)} |"
