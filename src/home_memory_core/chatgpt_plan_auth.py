from __future__ import annotations

import base64
from dataclasses import dataclass
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
import webbrowser


OIDC_DISCOVERY_URL = (
    "https://auth.openai.com/.well-known/"
    "openid-configuration"
)
RESOURCE = "https://api.openai.com/v1"
DYNAMIC_CLIENT_ID = "dynamic_agent_client"
AGENT_NAME = "HOME"
REQUIRED_SCOPES = (
    "openid",
    "profile",
    "email",
    "offline_access",
    "resource.invoke",
    "chatgpt.tokens.use.direct",
)
REQUIRED_PLAN_SCOPE = "chatgpt.tokens.use.direct"
DEFAULT_PROFILE_PATH = (
    Path.home()
    / ".config"
    / "home-memory-core"
    / "chatgpt-plan"
    / "profile.json"
)
DEFAULT_HOST_PATH = (
    Path.home()
    / ".config"
    / "home-memory-core"
    / "chatgpt-plan"
    / "host.json"
)


class ChatGPTPlanAuthError(RuntimeError):
    """Sign in with ChatGPT failed a HOME local-client check."""


@dataclass(frozen=True)
class ChatGPTPlanProfile:
    email: str | None
    issuer: str
    subject: str
    client_id: str
    ext_agent_host_id: str
    id_token: str
    access_token: str
    refresh_token: str | None
    token_type: str
    expires_in: int
    scopes: tuple[str, ...]
    saved_at_unix: int

    @property
    def plan_usage_enabled(self) -> bool:
        return REQUIRED_PLAN_SCOPE in self.scopes

    def access_token_is_fresh(
        self,
        *,
        now_unix: int | None = None,
        safety_seconds: int = 30,
    ) -> bool:
        if now_unix is None:
            now_unix = int(time.time())
        return (
            now_unix + safety_seconds
            < self.saved_at_unix + self.expires_in
        )


def load_or_create_host_id(
    *,
    path: Path = DEFAULT_HOST_PATH,
) -> str:
    if path.exists():
        data = _read_private_json(path)
        value = data.get("ext_agent_host_id")
        if (
            type(value) is not str
            or not value.startswith("urn:uuid:")
        ):
            raise ChatGPTPlanAuthError(
                "stored ext_agent_host_id is invalid"
            )
        return value

    value = f"urn:uuid:{uuid4()}"
    _atomic_private_json(
        path,
        {
            "ext_agent_host_id": value,
            "host_id_version": (
                "home-chatgpt-host-v0.1"
            ),
        },
    )
    return value


def load_profile(
    *,
    path: Path = DEFAULT_PROFILE_PATH,
    require_fresh_access_token: bool = True,
    require_plan_scope: bool = True,
) -> ChatGPTPlanProfile:
    data = _read_private_json(path)
    profile = _profile_from_json(data)
    if (
        require_fresh_access_token
        and not profile.access_token_is_fresh()
    ):
        raise ChatGPTPlanAuthError(
            "ChatGPT plan access token is expired "
            "or near expiry; run sign-in again"
        )
    if (
        require_plan_scope
        and not profile.plan_usage_enabled
    ):
        raise ChatGPTPlanAuthError(
            "ChatGPT plan usage scope is not granted"
        )
    return profile


def sign_in(
    *,
    profile_path: Path = DEFAULT_PROFILE_PATH,
    host_path: Path = DEFAULT_HOST_PATH,
    browser_open=webbrowser.open,
    timeout_seconds: int = 180,
) -> ChatGPTPlanProfile:
    if (
        type(timeout_seconds) is not int
        or timeout_seconds <= 0
        or timeout_seconds > 900
    ):
        raise ChatGPTPlanAuthError(
            "timeout_seconds must be exact int in 1..900"
        )

    discovery = _fetch_json(OIDC_DISCOVERY_URL)
    issuer = _required_text(discovery, "issuer")
    authorize_endpoint = _required_text(
        discovery,
        "authorization_endpoint",
    )
    token_endpoint = _required_text(
        discovery,
        "token_endpoint",
    )
    jwks_uri = _required_text(
        discovery,
        "jwks_uri",
    )

    host_id = load_or_create_host_id(
        path=host_path
    )
    existing = None
    if profile_path.exists():
        try:
            existing = load_profile(
                path=profile_path,
                require_fresh_access_token=False,
                require_plan_scope=False,
            )
        except ChatGPTPlanAuthError:
            existing = None

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(
        sha256(
            verifier.encode("ascii")
        ).digest()
    )

    callback = _CallbackReceiver()
    server = HTTPServer(
        ("127.0.0.1", 0),
        callback.handler_class,
    )
    callback.bind_server(server)
    server.timeout = timeout_seconds
    port = server.server_port
    redirect_uri = (
        f"http://127.0.0.1:{port}/auth/callback"
    )

    if existing is None:
        client_id = DYNAMIC_CLIENT_ID
        params: dict[str, str] = {
            "client_id": client_id,
            "agent_name_hint": AGENT_NAME,
            "ext_agent_host_id": host_id,
        }
    else:
        client_id = existing.client_id
        params = {
            "client_id": client_id,
            "ext_agent_host_id": host_id,
            "id_token_hint": existing.id_token,
        }
        if existing.email:
            params["login_hint"] = existing.email

    params.update(
        {
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(REQUIRED_SCOPES),
            "resource": RESOURCE,
            "state": state,
            "nonce": nonce,
            "code_challenge_method": "S256",
            "code_challenge": challenge,
        }
    )
    auth_url = (
        authorize_endpoint
        + "?"
        + urlencode(params)
    )

    opened = browser_open(auth_url)
    if opened is False:
        server.server_close()
        raise ChatGPTPlanAuthError(
            "system browser did not open authorization URL"
        )

    try:
        server.handle_request()
    finally:
        server.server_close()

    result = callback.result
    if result is None:
        raise ChatGPTPlanAuthError(
            "authorization callback timed out"
        )
    if result.get("state") != state:
        raise ChatGPTPlanAuthError(
            "authorization callback state mismatch"
        )
    if "error" in result:
        raise ChatGPTPlanAuthError(
            "authorization declined or failed: "
            + result["error"]
        )

    code = result.get("code")
    if type(code) is not str or not code:
        raise ChatGPTPlanAuthError(
            "authorization callback lacks code"
        )

    callback_client_id = result.get("client_id")
    if existing is None:
        if (
            type(callback_client_id) is not str
            or not callback_client_id
            or callback_client_id
            == DYNAMIC_CLIENT_ID
        ):
            raise ChatGPTPlanAuthError(
                "dynamic registration did not return "
                "an issued client_id"
            )
        issued_client_id = callback_client_id
    else:
        issued_client_id = existing.client_id
        if (
            callback_client_id is not None
            and callback_client_id
            != issued_client_id
        ):
            raise ChatGPTPlanAuthError(
                "reauthorization returned a "
                "different client_id"
            )

    token_data = _post_form_json(
        token_endpoint,
        {
            "grant_type": "authorization_code",
            "client_id": issued_client_id,
            "code": code,
            "code_verifier": verifier,
            "redirect_uri": redirect_uri,
            "resource": RESOURCE,
        },
    )

    id_token = _required_text(
        token_data,
        "id_token",
    )
    claims = verify_id_token(
        id_token=id_token,
        issuer=issuer,
        client_id=issued_client_id,
        nonce=nonce,
        jwks_uri=jwks_uri,
    )
    subject = _required_text(
        claims,
        "sub",
    )
    email_value = claims.get("email")
    if (
        email_value is not None
        and type(email_value) is not str
    ):
        raise ChatGPTPlanAuthError(
            "ID token email must be str or null"
        )

    if (
        existing is not None
        and subject != existing.subject
    ):
        raise ChatGPTPlanAuthError(
            "reauthorization identity changed"
        )

    access_token = _required_text(
        token_data,
        "access_token",
    )
    token_type = _required_text(
        token_data,
        "token_type",
    )
    if token_type.lower() != "bearer":
        raise ChatGPTPlanAuthError(
            "token_type is not Bearer"
        )
    expires_in = token_data.get("expires_in")
    if (
        type(expires_in) is not int
        or expires_in <= 0
    ):
        raise ChatGPTPlanAuthError(
            "expires_in is not positive exact int"
        )
    scope_text = _required_text(
        token_data,
        "scope",
    )
    scopes = tuple(
        sorted(
            {
                item
                for item in scope_text.split()
                if item
            }
        )
    )
    if REQUIRED_PLAN_SCOPE not in scopes:
        raise ChatGPTPlanAuthError(
            "ChatGPT plan usage was not granted"
        )

    refresh_value = token_data.get(
        "refresh_token"
    )
    if (
        refresh_value is not None
        and (
            type(refresh_value) is not str
            or not refresh_value
        )
    ):
        raise ChatGPTPlanAuthError(
            "refresh_token must be non-empty str or null"
        )

    profile = ChatGPTPlanProfile(
        email=email_value,
        issuer=issuer,
        subject=subject,
        client_id=issued_client_id,
        ext_agent_host_id=host_id,
        id_token=id_token,
        access_token=access_token,
        refresh_token=refresh_value,
        token_type=token_type,
        expires_in=expires_in,
        scopes=scopes,
        saved_at_unix=int(time.time()),
    )
    _atomic_private_json(
        profile_path,
        _profile_to_json(profile),
    )
    return profile


def list_models(
    *,
    profile: ChatGPTPlanProfile,
) -> tuple[dict[str, str], ...]:
    if not profile.access_token_is_fresh():
        raise ChatGPTPlanAuthError(
            "ChatGPT plan access token is expired"
        )
    request = Request(
        "https://api.openai.com/v1/models",
        method="GET",
        headers={
            "Authorization": (
                f"Bearer {profile.access_token}"
            ),
            "Accept": "application/json",
        },
    )
    data = _request_json(request)
    models = data.get("models")
    if not isinstance(models, list):
        raise ChatGPTPlanAuthError(
            "model catalog lacks models array"
        )
    result: list[dict[str, str]] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        if item.get("visibility") != "list":
            continue
        slug = item.get("slug")
        display_name = item.get(
            "display_name"
        )
        if (
            type(slug) is str
            and slug
            and type(display_name) is str
            and display_name
        ):
            result.append(
                {
                    "slug": slug,
                    "display_name": display_name,
                }
            )
    return tuple(result)


def verify_id_token(
    *,
    id_token: str,
    issuer: str,
    client_id: str,
    nonce: str,
    jwks_uri: str,
    now_unix: int | None = None,
) -> dict[str, Any]:
    parts = id_token.split(".")
    if len(parts) != 3:
        raise ChatGPTPlanAuthError(
            "ID token is not compact JWT"
        )
    header = _decode_json_segment(
        parts[0],
        "JWT header",
    )
    claims = _decode_json_segment(
        parts[1],
        "JWT claims",
    )
    if header.get("alg") != "RS256":
        raise ChatGPTPlanAuthError(
            "ID token alg is not RS256"
        )
    kid = _required_text(
        header,
        "kid",
    )

    jwks = _fetch_json(jwks_uri)
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise ChatGPTPlanAuthError(
            "JWKS lacks keys array"
        )
    matching = [
        item
        for item in keys
        if isinstance(item, dict)
        and item.get("kid") == kid
    ]
    if len(matching) != 1:
        raise ChatGPTPlanAuthError(
            "ID token signing key is not uniquely found"
        )
    _verify_rs256_signature(
        signing_input=(
            parts[0] + "." + parts[1]
        ).encode("ascii"),
        signature=_b64url_decode(parts[2]),
        jwk=matching[0],
    )

    if claims.get("iss") != issuer:
        raise ChatGPTPlanAuthError(
            "ID token issuer mismatch"
        )
    aud = claims.get("aud")
    if type(aud) is str:
        if aud != client_id:
            raise ChatGPTPlanAuthError(
                "ID token audience mismatch"
            )
    elif isinstance(aud, list):
        if (
            client_id not in aud
            or not all(
                type(item) is str
                for item in aud
            )
        ):
            raise ChatGPTPlanAuthError(
                "ID token audience mismatch"
            )
        if (
            len(aud) > 1
            and claims.get("azp") != client_id
        ):
            raise ChatGPTPlanAuthError(
                "ID token azp mismatch"
            )
    else:
        raise ChatGPTPlanAuthError(
            "ID token audience is invalid"
        )

    if claims.get("nonce") != nonce:
        raise ChatGPTPlanAuthError(
            "ID token nonce mismatch"
        )
    now = (
        int(time.time())
        if now_unix is None
        else now_unix
    )
    exp = claims.get("exp")
    if (
        type(exp) not in {int, float}
        or exp <= now
    ):
        raise ChatGPTPlanAuthError(
            "ID token is expired"
        )
    iat = claims.get("iat")
    if (
        iat is not None
        and (
            type(iat) not in {int, float}
            or iat > now + 300
        )
    ):
        raise ChatGPTPlanAuthError(
            "ID token issued-at is invalid"
        )
    _required_text(claims, "sub")
    return claims


class _CallbackReceiver:
    def __init__(self) -> None:
        self.result: dict[str, str] | None = None
        self._server: HTTPServer | None = None
        parent = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path != "/auth/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                query = parse_qs(
                    parsed.query,
                    keep_blank_values=True,
                )
                flat = {
                    key: values[0]
                    for key, values in query.items()
                    if values
                }
                parent.result = flat
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "text/plain; charset=utf-8",
                )
                self.end_headers()
                self.wfile.write(
                    (
                        "HOME received the ChatGPT "
                        "authorization. You can return "
                        "to Terminal."
                    ).encode("utf-8")
                )

            def log_message(
                self,
                format: str,
                *args: Any,
            ) -> None:
                return

        self.handler_class = Handler

    def bind_server(
        self,
        server: HTTPServer,
    ) -> None:
        self._server = server


def _fetch_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        method="GET",
        headers={"Accept": "application/json"},
    )
    return _request_json(request)


def _post_form_json(
    url: str,
    values: dict[str, str],
) -> dict[str, Any]:
    encoded = urlencode(values).encode(
        "utf-8"
    )
    request = Request(
        url,
        method="POST",
        data=encoded,
        headers={
            "Content-Type": (
                "application/x-www-form-urlencoded"
            ),
            "Accept": "application/json",
        },
    )
    return _request_json(request)


def _request_json(
    request: Request,
) -> dict[str, Any]:
    try:
        with urlopen(
            request,
            timeout=30,
        ) as response:
            body = response.read().decode(
                "utf-8",
                errors="strict",
            )
    except HTTPError as exc:
        body = exc.read().decode(
            "utf-8",
            errors="replace",
        )
        raise ChatGPTPlanAuthError(
            f"OpenAI HTTP {exc.code}: "
            f"{_safe_diagnostic(body)}"
        ) from exc
    except OSError as exc:
        raise ChatGPTPlanAuthError(
            "OpenAI network request failed"
        ) from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ChatGPTPlanAuthError(
            "OpenAI response was not valid JSON"
        ) from exc
    if not isinstance(parsed, dict):
        raise ChatGPTPlanAuthError(
            "OpenAI JSON response root is not object"
        )
    return parsed


def _safe_diagnostic(body: str) -> str:
    if len(body) > 500:
        return body[:500] + "…"
    return body


def _profile_from_json(
    data: dict[str, Any],
) -> ChatGPTPlanProfile:
    email = data.get("email")
    if (
        email is not None
        and type(email) is not str
    ):
        raise ChatGPTPlanAuthError(
            "profile email is invalid"
        )
    refresh_token = data.get(
        "refresh_token"
    )
    if (
        refresh_token is not None
        and (
            type(refresh_token) is not str
            or not refresh_token
        )
    ):
        raise ChatGPTPlanAuthError(
            "profile refresh_token is invalid"
        )
    scopes = data.get("scopes")
    if (
        not isinstance(scopes, list)
        or not all(
            type(item) is str
            and item
            for item in scopes
        )
    ):
        raise ChatGPTPlanAuthError(
            "profile scopes are invalid"
        )
    expires_in = data.get("expires_in")
    saved_at_unix = data.get(
        "saved_at_unix"
    )
    if (
        type(expires_in) is not int
        or expires_in <= 0
        or type(saved_at_unix) is not int
        or saved_at_unix <= 0
    ):
        raise ChatGPTPlanAuthError(
            "profile expiry metadata is invalid"
        )
    return ChatGPTPlanProfile(
        email=email,
        issuer=_required_text(
            data,
            "issuer",
        ),
        subject=_required_text(
            data,
            "subject",
        ),
        client_id=_required_text(
            data,
            "client_id",
        ),
        ext_agent_host_id=_required_text(
            data,
            "ext_agent_host_id",
        ),
        id_token=_required_text(
            data,
            "id_token",
        ),
        access_token=_required_text(
            data,
            "access_token",
        ),
        refresh_token=refresh_token,
        token_type=_required_text(
            data,
            "token_type",
        ),
        expires_in=expires_in,
        scopes=tuple(scopes),
        saved_at_unix=saved_at_unix,
    )


def _profile_to_json(
    profile: ChatGPTPlanProfile,
) -> dict[str, Any]:
    return {
        "profile_version": (
            "home-chatgpt-plan-profile-v0.1"
        ),
        "email": profile.email,
        "issuer": profile.issuer,
        "subject": profile.subject,
        "client_id": profile.client_id,
        "ext_agent_host_id": (
            profile.ext_agent_host_id
        ),
        "id_token": profile.id_token,
        "access_token": (
            profile.access_token
        ),
        "refresh_token": (
            profile.refresh_token
        ),
        "token_type": profile.token_type,
        "expires_in": profile.expires_in,
        "scopes": list(profile.scopes),
        "saved_at_unix": (
            profile.saved_at_unix
        ),
    }


def _read_private_json(
    path: Path,
) -> dict[str, Any]:
    try:
        raw = path.read_text(
            encoding="utf-8"
        )
    except FileNotFoundError as exc:
        raise ChatGPTPlanAuthError(
            f"credential file not found: {path}"
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ChatGPTPlanAuthError(
            f"credential file is invalid JSON: {path}"
        ) from exc
    if not isinstance(data, dict):
        raise ChatGPTPlanAuthError(
            "credential JSON root is not object"
        )
    return data


def _atomic_private_json(
    path: Path,
    value: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
        mode=0o700,
    )
    try:
        os.chmod(
            path.parent,
            0o700,
        )
    except OSError:
        pass

    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    fd, temp_name = tempfile.mkstemp(
        prefix=path.name + ".",
        dir=path.parent,
        text=True,
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(
            fd,
            "w",
            encoding="utf-8",
        ) as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(
                handle.fileno()
            )
        os.replace(
            temp_name,
            path,
        )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def _decode_json_segment(
    segment: str,
    name: str,
) -> dict[str, Any]:
    try:
        raw = _b64url_decode(
            segment
        ).decode("utf-8")
        value = json.loads(raw)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        raise ChatGPTPlanAuthError(
            f"{name} is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise ChatGPTPlanAuthError(
            f"{name} root is not object"
        )
    return value


def _verify_rs256_signature(
    *,
    signing_input: bytes,
    signature: bytes,
    jwk: dict[str, Any],
) -> None:
    if (
        jwk.get("kty") != "RSA"
        or jwk.get("alg") not in {None, "RS256"}
    ):
        raise ChatGPTPlanAuthError(
            "JWKS key is not RSA/RS256"
        )
    n_text = _required_text(jwk, "n")
    e_text = _required_text(jwk, "e")
    n = int.from_bytes(
        _b64url_decode(n_text),
        "big",
    )
    e = int.from_bytes(
        _b64url_decode(e_text),
        "big",
    )
    public_pem = _rsa_public_key_pem(
        n,
        e,
    )

    openssl = shutil.which(
        "openssl"
    )
    if openssl is None:
        raise ChatGPTPlanAuthError(
            "openssl is required for local ID-token "
            "signature verification"
        )

    with tempfile.TemporaryDirectory(
        prefix="home-siwc-verify-"
    ) as tmp:
        root = Path(tmp)
        pub_path = root / "public.pem"
        data_path = root / "data.bin"
        sig_path = root / "signature.bin"
        pub_path.write_bytes(public_pem)
        data_path.write_bytes(
            signing_input
        )
        sig_path.write_bytes(signature)
        result = subprocess.run(
            [
                openssl,
                "dgst",
                "-sha256",
                "-verify",
                str(pub_path),
                "-signature",
                str(sig_path),
                str(data_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ChatGPTPlanAuthError(
                "ID token signature verification failed"
            )


def _rsa_public_key_pem(
    n: int,
    e: int,
) -> bytes:
    rsa_key = _der_seq(
        _der_int(n)
        + _der_int(e)
    )
    algorithm = _der_seq(
        _der_oid(
            (1, 2, 840, 113549, 1, 1, 1)
        )
        + b"\x05\x00"
    )
    spki = _der_seq(
        algorithm
        + _der_bit_string(rsa_key)
    )
    encoded = base64.b64encode(
        spki
    ).decode("ascii")
    lines = [
        encoded[index:index + 64]
        for index in range(
            0,
            len(encoded),
            64,
        )
    ]
    return (
        "-----BEGIN PUBLIC KEY-----\n"
        + "\n".join(lines)
        + "\n-----END PUBLIC KEY-----\n"
    ).encode("ascii")


def _der_len(length: int) -> bytes:
    if length < 0:
        raise ValueError(
            "negative DER length"
        )
    if length < 128:
        return bytes([length])
    raw = length.to_bytes(
        (length.bit_length() + 7) // 8,
        "big",
    )
    return bytes(
        [0x80 | len(raw)]
    ) + raw


def _der_seq(content: bytes) -> bytes:
    return (
        b"\x30"
        + _der_len(len(content))
        + content
    )


def _der_int(value: int) -> bytes:
    if value < 0:
        raise ValueError(
            "negative DER integer"
        )
    raw = (
        value.to_bytes(
            max(
                1,
                (value.bit_length() + 7) // 8,
            ),
            "big",
        )
    )
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return (
        b"\x02"
        + _der_len(len(raw))
        + raw
    )


def _der_bit_string(
    content: bytes,
) -> bytes:
    raw = b"\x00" + content
    return (
        b"\x03"
        + _der_len(len(raw))
        + raw
    )


def _der_oid(
    arcs: tuple[int, ...],
) -> bytes:
    if (
        len(arcs) < 2
        or arcs[0] not in {0, 1, 2}
        or arcs[1] < 0
        or (
            arcs[0] < 2
            and arcs[1] >= 40
        )
    ):
        raise ValueError("invalid OID")
    body = bytearray(
        [40 * arcs[0] + arcs[1]]
    )
    for arc in arcs[2:]:
        if arc < 0:
            raise ValueError(
                "negative OID arc"
            )
        chunks = [arc & 0x7F]
        arc >>= 7
        while arc:
            chunks.append(
                0x80 | (arc & 0x7F)
            )
            arc >>= 7
        body.extend(
            reversed(chunks)
        )
    raw = bytes(body)
    return (
        b"\x06"
        + _der_len(len(raw))
        + raw
    )


def _b64url(
    value: bytes,
) -> str:
    return base64.urlsafe_b64encode(
        value
    ).decode("ascii").rstrip("=")


def _b64url_decode(
    value: str,
) -> bytes:
    if type(value) is not str:
        raise ValueError(
            "base64url input must be str"
        )
    padding = "=" * (
        (-len(value)) % 4
    )
    return base64.urlsafe_b64decode(
        value + padding
    )


def _required_text(
    mapping: dict[str, Any],
    key: str,
) -> str:
    value = mapping.get(key)
    if type(value) is not str or not value:
        raise ChatGPTPlanAuthError(
            f"{key} must be non-empty exact str"
        )
    return value
