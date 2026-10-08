"""JWT bearer-token verification (OAuth 2.1 resource-server model).

The MCP SDK calls `JWTVerifier.verify_token` for every HTTP request; tools read the verified claims via
`mcp.server.auth.middleware.auth_context.get_access_token()`. Tokens must carry `sub`, `role`, `exp`, and the
audience must equal this server's resource URL.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import jwt
from mcp.server.auth.provider import AccessToken


@dataclass
class Principal:
    subject: str
    role: str


class JWTVerifier:
    def __init__(self, key: str, audience: str, algorithms: tuple[str, ...] = ("HS256", "RS256"),
                 issuer: str | None = None):
        self.key, self.audience, self.algorithms, self.issuer = key, audience, list(algorithms), issuer

    def decode(self, token: str) -> dict:
        return jwt.decode(token, self.key, algorithms=self.algorithms, audience=self.audience,
                          issuer=self.issuer, options={"require": ["exp", "sub", "aud"]})

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = self.decode(token)
        except jwt.PyJWTError:
            return None
        if "role" not in claims:
            return None
        return AccessToken(token=token, client_id=claims["sub"], scopes=claims.get("scope", "").split(),
                           expires_at=int(claims["exp"]), resource=self.audience, subject=claims["sub"],
                           claims=claims)


def principal_from(access: AccessToken | None) -> Principal | None:
    if access is None or not access.claims:
        return None
    return Principal(access.claims["sub"], access.claims["role"])


def issue_dev_token(secret: str, sub: str, role: str, audience: str, ttl_s: int = 3600) -> str:
    """HS256 token for local development and tests. Production should use an IdP and RS256."""
    now = int(time.time())
    return jwt.encode({"sub": sub, "role": role, "aud": audience, "iat": now, "exp": now + ttl_s},
                      secret, algorithm="HS256")
