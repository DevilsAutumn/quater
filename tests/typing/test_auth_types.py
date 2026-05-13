from __future__ import annotations

from collections.abc import Mapping
from typing import assert_type

from quater import CORSConfig, ImproperlyConfigured, Quater, Request, SignedCookieSigner
from quater.typing import AuthContext, Authenticate, AuthRequest


async def authenticate(ctx: AuthRequest) -> AuthContext | None:
    assert_type(ctx.method, str)
    assert_type(ctx.path, str)
    assert_type(ctx.headers, Mapping[str, str])
    token = ctx.headers.get("authorization")
    if token is None:
        return None
    return AuthContext(subject=token, metadata={"kind": "token"})


cors = CORSConfig(allowed_origins=("https://app.example.com",))
authenticator: Authenticate = authenticate
app = Quater(
    cors=cors,
    content_security_policy="default-src 'self'",
)


@app.get("/me", auth=authenticator)
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


assert_type(authenticator, Authenticate)
assert_type(cors, CORSConfig)
assert_type(app.config.cors, CORSConfig | None)
assert_type(request.scheme, str)
assert_type(request.client, str | None)
assert_type(signer.sign("value"), str)
assert_type(signer.verify("value.signature"), str | None)
assert_type(setup_error, ImproperlyConfigured)
