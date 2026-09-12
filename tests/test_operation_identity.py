import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.identity_namespaces import DestinationId, RequestId
from home_memory_core.operation_identity import (
    AuthenticatedPrincipal,
    AuthenticationBoundaryError,
    OperationClass,
    OperationContext,
    PrincipalId,
    TrustedPrincipalIssuer,
    create_operation_context,
)
from _trusted_test_support import trusted_test_principal_issuer


class OperationIdentityBoundaryTest(unittest.TestCase):
    def test_principal_id_rejects_blank_value(self) -> None:
        with self.assertRaises(AuthenticationBoundaryError):
            PrincipalId("   ")

    def test_caller_cannot_directly_mint_authenticated_principal(self) -> None:
        with self.assertRaises(AuthenticationBoundaryError):
            AuthenticatedPrincipal(
                principal_id=PrincipalId("vivi"),
                principal_kind="local_owner",
                trust_source="caller-body",
                _authn_marker=object(),
            )

    def test_caller_cannot_directly_mint_trusted_issuer(self) -> None:
        with self.assertRaises(AuthenticationBoundaryError):
            TrustedPrincipalIssuer(
                trust_source="caller-body",
                _issuer_marker=object(),
            )

    def test_trusted_test_issuer_mints_principal_with_trust_source(self) -> None:
        issuer = trusted_test_principal_issuer(
            trust_source="synthetic-local-owner-test",
        )

        principal = issuer.issue(
            principal_id=PrincipalId("vivi"),
            principal_kind="local_owner",
        )

        self.assertEqual(principal.principal_id, PrincipalId("vivi"))
        self.assertEqual(principal.principal_kind, "local_owner")
        self.assertEqual(
            principal.trust_source,
            "synthetic-local-owner-test",
        )

    def test_operation_context_uses_system_generated_operation_identity(self) -> None:
        issuer = trusted_test_principal_issuer()
        principal = issuer.issue(
            principal_id=PrincipalId("vivi"),
            principal_kind="local_owner",
        )

        first = create_operation_context(
            principal=principal,
            operation_class=OperationClass.SOURCE_WRITE,
            request_id=RequestId("request-001"),
        )
        second = create_operation_context(
            principal=principal,
            operation_class=OperationClass.SOURCE_WRITE,
            request_id=RequestId("request-001"),
        )

        self.assertTrue(first.operation_id.startswith("operation-"))
        self.assertNotEqual(first.operation_id, second.operation_id)
        self.assertIs(first.principal, principal)
        self.assertEqual(first.request_id, RequestId("request-001"))

    def test_caller_cannot_directly_mint_operation_context(self) -> None:
        issuer = trusted_test_principal_issuer()
        principal = issuer.issue(
            principal_id=PrincipalId("vivi"),
            principal_kind="local_owner",
        )

        with self.assertRaises(AuthenticationBoundaryError):
            OperationContext(
                operation_id="caller-chosen-operation-id",
                principal=principal,
                operation_class=OperationClass.SOURCE_WRITE,
            )

    def test_operation_context_rejects_non_authenticated_principal(self) -> None:
        with self.assertRaises(AuthenticationBoundaryError):
            create_operation_context(
                principal="vivi",  # type: ignore[arg-type]
                operation_class=OperationClass.SOURCE_WRITE,
            )

    def test_operation_context_is_identity_not_authorization(self) -> None:
        issuer = trusted_test_principal_issuer()
        principal = issuer.issue(
            principal_id=PrincipalId("vivi"),
            principal_kind="local_owner",
        )
        context = create_operation_context(
            principal=principal,
            operation_class=OperationClass.DISCOVERY_READ,
        )

        self.assertFalse(hasattr(context, "authorized"))
        self.assertFalse(hasattr(context, "allow"))

    def test_operation_context_rejects_caller_supplied_raw_operation_string(self) -> None:
        issuer = trusted_test_principal_issuer()
        principal = issuer.issue(
            principal_id=PrincipalId("vivi"),
            principal_kind="local_owner",
        )

        with self.assertRaises(AuthenticationBoundaryError):
            create_operation_context(
                principal=principal,
                operation_class="source.write",  # type: ignore[arg-type]
            )

    def test_request_and_destination_use_separate_typed_namespaces(self) -> None:
        issuer = trusted_test_principal_issuer()
        principal = issuer.issue(
            principal_id=PrincipalId("vivi"),
            principal_kind="local_owner",
        )

        context = create_operation_context(
            principal=principal,
            operation_class=OperationClass.MEMORY_DELIVER,
            request_id=RequestId("request-001"),
            destination_id=DestinationId("local-chat-session-001"),
        )

        self.assertEqual(context.request_id, RequestId("request-001"))
        self.assertEqual(
            context.destination_id,
            DestinationId("local-chat-session-001"),
        )

        with self.assertRaises(AuthenticationBoundaryError):
            create_operation_context(
                principal=principal,
                operation_class=OperationClass.MEMORY_DELIVER,
                request_id="request-001",  # type: ignore[arg-type]
            )

        with self.assertRaises(AuthenticationBoundaryError):
            create_operation_context(
                principal=principal,
                operation_class=OperationClass.MEMORY_DELIVER,
                destination_id="local-chat-session-001",  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
