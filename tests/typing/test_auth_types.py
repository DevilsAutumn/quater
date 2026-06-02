from __future__ import annotations

from typing import Annotated, assert_type

from quater import (
    AuthConfig,
    CORSConfig,
    ImproperlyConfigured,
    Quater,
    Request,
    Resource,
    SignedCookieSigner,
)
from quater.datastructures import Headers
from quater.typing import AuthContext, Authenticator


async def authenticate(ctx: Request) -> AuthContext | None:
    assert_type(ctx.method, str)
    assert_type(ctx.path, str)
    assert_type(ctx.headers, Headers)
    token = ctx.headers.get("authorization")
    if token is None:
        return None
    return AuthContext(subject=token, metadata={"kind": "token"})


class Session:
    pass


async def open_session() -> Session:
    return Session()


session_resource = Resource(open_session)
SessionDep = Annotated[Session, session_resource]


async def authenticate_with_resource(ctx: Request) -> AuthContext | None:
    session = await ctx.resolve(session_resource)
    assert_type(session, Session)
    alias_session = await ctx.resolve(SessionDep)
    assert_type(alias_session, object)
    return AuthContext(subject="typed")


cors = CORSConfig(allowed_origins=("https://app.example.com",))
authenticator: Authenticator = authenticate
resource_authenticator: Authenticator = authenticate_with_resource
app = Quater(
    cors=cors,
    content_security_policy="default-src 'self'",
    auth=[AuthConfig(authenticate, surfaces=["api"])],
)


@app.get("/me")
async def me(request: Request) -> dict[str, str]:
    assert request.auth is not None
    return {"subject": request.auth.subject}


request = Request(
    method="GET",
    path="/me",
    scheme="https",
    headers={"host": "api.example.com"},
    client="127.0.0.1",
)
signer = SignedCookieSigner("secret")
setup_error = ImproperlyConfigured("bad setup")


assert_type(authenticator, Authenticator)
assert_type(cors, CORSConfig)
assert_type(app.config.cors, CORSConfig | None)
assert_type(request.scheme, str)
assert_type(request.client, str | None)
assert_type(signer.sign("value"), str)
assert_type(signer.verify("value.signature"), str | None)
assert_type(setup_error, ImproperlyConfigured)
assert_type(resource_authenticator, Authenticator)
