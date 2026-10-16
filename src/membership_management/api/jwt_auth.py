from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError

from membership_management.api.config import api_settings

# Registers a Bearer-token security scheme in the OpenAPI schema, which is what makes /docs show
# an "Authorize" button (and a lock icon per protected route) instead of offering no way to
# attach a token at all -- raw request.headers reads are invisible to OpenAPI generation.
# auto_error=True (the default) means it already 401s with a WWW-Authenticate: Bearer header on a
# missing/malformed/wrong-scheme header, matching what this module would otherwise hand-roll.
_bearer_scheme = HTTPBearer()

_JWKS_URL = f"{api_settings.auth_server_url}/api/auth/.well-known/jwks.json"

# Fetches/caches auth-server's public signing keys. cache_jwk_set (default True) caches the whole
# JWKS document for `lifespan` seconds instead of refetching per request; cache_keys additionally
# caches each key object PyJWT builds from a JWK, keyed by kid, so repeat verifications with the
# same kid skip re-parsing the key material too.
_jwks_client = jwt.PyJWKClient(_JWKS_URL, cache_keys=True, lifespan=300)


class AuthClaims(BaseModel):
    sub: str
    # Display only (`GET /me`). Nothing checks it: routes check `perms`.
    role: str
    # auth-server's computed permissions for `role` (`permissionsFor` in statements.ts), as
    # resource -> actions. Missing (a token minted before auth-server shipped `perms`) means no
    # permissions at all: fail closed. Routes check these, never `role`.
    perms: dict[str, list[str]] = {}


def has_permission(claims: AuthClaims, resource: str, action: str) -> bool:
    return action in claims.perms.get(resource, ())


def get_current_claims(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> AuthClaims:
    token = credentials.credentials
    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        decoded = jwt.decode(
            token,
            signing_key.key,
            algorithms=["EdDSA"],
            issuer=api_settings.jwt_issuer,
            audience=api_settings.jwt_audience,
            leeway=10,
        )
        return AuthClaims.model_validate(decoded)

    except (jwt.PyJWTError, ValidationError) as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


CurrentClaimsDep = Annotated[AuthClaims, Depends(get_current_claims)]


def require_permission(resource: str, *actions: str) -> Callable[[AuthClaims], AuthClaims]:
    """Dependency factory: returns the claims if `perms[resource]` has every one of `actions`, else 403.

    All-of, like staff-app's `can(...)`: `require_permission("members", "view", "all")` needs both.
    """

    def dependency(claims: CurrentClaimsDep) -> AuthClaims:
        if not all(has_permission(claims, resource, action) for action in actions):
            raise HTTPException(status_code=403, detail="You don't have permission to do this.")
        return claims

    return dependency
