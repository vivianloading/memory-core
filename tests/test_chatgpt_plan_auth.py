import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from home_memory_core import chatgpt_plan_auth as auth


def _segment(value):
    raw = json.dumps(
        value,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class ChatGPTPlanAuthTests(unittest.TestCase):
    def test_host_id_is_stable_and_private_file_is_reused(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "host.json"
            first = auth.load_or_create_host_id(path=path)
            second = auth.load_or_create_host_id(path=path)
            self.assertEqual(first, second)
            self.assertTrue(first.startswith("urn:uuid:"))
            if os.name == "posix":
                self.assertEqual(
                    path.stat().st_mode & 0o777,
                    0o600,
                )

    def test_profile_loader_requires_plan_scope_and_fresh_access_token(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            data = {
                "email": None,
                "issuer": "https://auth.openai.com",
                "subject": "subject-test",
                "client_id": "oaiapp_test",
                "ext_agent_host_id": "urn:uuid:test",
                "id_token": "header.payload.signature",
                "access_token": "access-test",
                "refresh_token": "refresh-test",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scopes": [
                    "openid",
                    "chatgpt.tokens.use.direct",
                ],
                "saved_at_unix": 2000,
            }
            auth._atomic_private_json(path, data)
            with patch.object(
                auth.time,
                "time",
                return_value=3000,
            ):
                profile = auth.load_profile(path=path)
            self.assertEqual(profile.access_token, "access-test")

            data["scopes"] = ["openid"]
            auth._atomic_private_json(path, data)
            with self.assertRaises(auth.ChatGPTPlanAuthError):
                auth.load_profile(
                    path=path,
                    require_fresh_access_token=False,
                )

            profile_without_plan = auth.load_profile(
                path=path,
                require_fresh_access_token=False,
                require_plan_scope=False,
            )
            self.assertFalse(
                profile_without_plan.plan_usage_enabled
            )

            data["scopes"] = [
                "openid",
                "chatgpt.tokens.use.direct",
            ]
            data["saved_at_unix"] = 1
            data["expires_in"] = 1
            auth._atomic_private_json(path, data)
            with patch.object(
                auth.time,
                "time",
                return_value=3000,
            ):
                with self.assertRaises(auth.ChatGPTPlanAuthError):
                    auth.load_profile(path=path)

    def test_id_token_claims_are_checked_after_signature_verification(
        self,
    ) -> None:
        header = {
            "alg": "RS256",
            "kid": "kid-test",
        }
        claims = {
            "iss": "https://auth.openai.com",
            "aud": "oaiapp_test",
            "sub": "subject-test",
            "nonce": "nonce-test",
            "exp": 5000,
            "iat": 1000,
            "email": "example@example.com",
        }
        token = (
            _segment(header)
            + "."
            + _segment(claims)
            + "."
            + base64.urlsafe_b64encode(
                b"signature"
            ).decode("ascii").rstrip("=")
        )
        with (
            patch.object(
                auth,
                "_fetch_json",
                return_value={
                    "keys": [
                        {
                            "kid": "kid-test",
                            "kty": "RSA",
                            "n": "AQ",
                            "e": "Aw",
                        }
                    ]
                },
            ),
            patch.object(
                auth,
                "_verify_rs256_signature",
            ) as verify,
        ):
            result = auth.verify_id_token(
                id_token=token,
                issuer="https://auth.openai.com",
                client_id="oaiapp_test",
                nonce="nonce-test",
                jwks_uri="https://example.invalid/jwks",
                now_unix=2000,
            )
        self.assertEqual(result["sub"], "subject-test")
        self.assertEqual(verify.call_count, 1)

        bad_claims = dict(claims)
        bad_claims["nonce"] = "wrong"
        bad_token = (
            _segment(header)
            + "."
            + _segment(bad_claims)
            + "."
            + base64.urlsafe_b64encode(
                b"signature"
            ).decode("ascii").rstrip("=")
        )
        with (
            patch.object(
                auth,
                "_fetch_json",
                return_value={
                    "keys": [
                        {
                            "kid": "kid-test",
                            "kty": "RSA",
                            "n": "AQ",
                            "e": "Aw",
                        }
                    ]
                },
            ),
            patch.object(
                auth,
                "_verify_rs256_signature",
            ),
        ):
            with self.assertRaises(auth.ChatGPTPlanAuthError):
                auth.verify_id_token(
                    id_token=bad_token,
                    issuer="https://auth.openai.com",
                    client_id="oaiapp_test",
                    nonce="nonce-test",
                    jwks_uri="https://example.invalid/jwks",
                    now_unix=2000,
                )

    def test_model_catalog_filters_to_list_visibility_without_exposing_token(
        self,
    ) -> None:
        profile = auth.ChatGPTPlanProfile(
            email=None,
            issuer="https://auth.openai.com",
            subject="subject-test",
            client_id="oaiapp_test",
            ext_agent_host_id="urn:uuid:test",
            id_token="id-test",
            access_token="ACCESS-TOKEN-SECRET",
            refresh_token=None,
            token_type="Bearer",
            expires_in=3600,
            scopes=("chatgpt.tokens.use.direct",),
            saved_at_unix=1000,
        )
        with (
            patch.object(
                auth.time,
                "time",
                return_value=2000,
            ),
            patch.object(
                auth,
                "_request_json",
                return_value={
                    "models": [
                        {
                            "slug": "gpt-visible",
                            "display_name": "GPT Visible",
                            "visibility": "list",
                        },
                        {
                            "slug": "gpt-hidden",
                            "display_name": "GPT Hidden",
                            "visibility": "hidden",
                        },
                    ]
                },
            ) as request,
        ):
            models = auth.list_models(profile=profile)
        self.assertEqual(
            models,
            (
                {
                    "slug": "gpt-visible",
                    "display_name": "GPT Visible",
                },
            ),
        )
        sent_request = request.call_args.args[0]
        self.assertIn(
            "Bearer ACCESS-TOKEN-SECRET",
            sent_request.headers["Authorization"],
        )


if __name__ == "__main__":
    unittest.main()
