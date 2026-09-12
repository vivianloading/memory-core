import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.identity_namespaces import (
    AccessDomainId,
    DestinationId,
    IdentityNamespaceError,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
    RequestId,
    SourceAuthorRef,
    SubjectId,
)


class IdentityNamespaceTest(unittest.TestCase):
    def test_each_namespace_rejects_blank_text(self) -> None:
        for namespace in (
            SourceAuthorRef,
            SubjectId,
            PerspectiveOwnerId,
            PerspectiveInstanceId,
            DestinationId,
            AccessDomainId,
            RequestId,
        ):
            with self.subTest(namespace=namespace.__name__):
                with self.assertRaises(IdentityNamespaceError):
                    namespace("   ")

    def test_same_text_does_not_make_identity_namespaces_interchangeable(self) -> None:
        self.assertNotEqual(SourceAuthorRef("vivi"), SubjectId("vivi"))
        self.assertNotEqual(
            PerspectiveOwnerId("lior"),
            PerspectiveInstanceId("lior"),
        )
        self.assertNotEqual(DestinationId("home"), AccessDomainId("home"))


if __name__ == "__main__":
    unittest.main()
