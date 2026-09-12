import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_ROOT))

from home_memory_core.identity_namespaces import (
    AccessDomainId,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
    SourceAuthorRef,
    SubjectId,
)
from home_memory_core.ingress_identity import IngressIdentityMetadata
from home_memory_core.operation_identity import PrincipalId


class IngressIdentityMetadataTest(unittest.TestCase):
    def test_unknown_author_and_subject_are_allowed_without_placeholder_identity(self) -> None:
        metadata = IngressIdentityMetadata(
            access_domain_id=AccessDomainId("pilot-owner-domain"),
        )

        self.assertIsNone(metadata.asserted_author)
        self.assertEqual(metadata.subjects, ())
        self.assertIsNone(metadata.perspective_owner)
        self.assertIsNone(metadata.perspective_instance)

    def test_asserted_author_is_not_an_authenticated_operator(self) -> None:
        metadata = IngressIdentityMetadata(
            access_domain_id=AccessDomainId("pilot-owner-domain"),
            asserted_author=SourceAuthorRef("vivi"),
            subjects=(SubjectId("home"),),
        )

        self.assertEqual(metadata.asserted_author, SourceAuthorRef("vivi"))
        self.assertFalse(hasattr(metadata, "principal"))
        self.assertFalse(hasattr(metadata, "authorized"))
        self.assertNotEqual(metadata.asserted_author, PrincipalId("vivi"))

    def test_subjects_require_the_subject_namespace(self) -> None:
        with self.assertRaises(TypeError):
            IngressIdentityMetadata(
                access_domain_id=AccessDomainId("pilot-owner-domain"),
                subjects=("vivi",),  # type: ignore[arg-type]
            )

    def test_duplicate_subjects_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            IngressIdentityMetadata(
                access_domain_id=AccessDomainId("pilot-owner-domain"),
                subjects=(SubjectId("vivi"), SubjectId("vivi")),
            )

    def test_perspective_owner_and_instance_are_both_present_or_both_absent(self) -> None:
        with self.assertRaises(ValueError):
            IngressIdentityMetadata(
                access_domain_id=AccessDomainId("pilot-owner-domain"),
                perspective_owner=PerspectiveOwnerId("lior"),
            )

        with self.assertRaises(ValueError):
            IngressIdentityMetadata(
                access_domain_id=AccessDomainId("pilot-owner-domain"),
                perspective_instance=PerspectiveInstanceId("lior-current"),
            )

        metadata = IngressIdentityMetadata(
            access_domain_id=AccessDomainId("pilot-owner-domain"),
            perspective_owner=PerspectiveOwnerId("lior"),
            perspective_instance=PerspectiveInstanceId("lior-current"),
        )
        self.assertEqual(metadata.perspective_owner, PerspectiveOwnerId("lior"))
        self.assertEqual(
            metadata.perspective_instance,
            PerspectiveInstanceId("lior-current"),
        )

    def test_access_domain_cannot_be_replaced_by_scope_or_raw_text(self) -> None:
        with self.assertRaises(TypeError):
            IngressIdentityMetadata(
                access_domain_id="shared",  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
