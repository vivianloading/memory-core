from __future__ import annotations

from dataclasses import dataclass

from home_memory_core.identity_namespaces import (
    AccessDomainId,
    PerspectiveInstanceId,
    PerspectiveOwnerId,
    SourceAuthorRef,
    SubjectId,
)


@dataclass(frozen=True)
class IngressIdentityMetadata:
    """Identity metadata for the future real-ingress path.

    This object deliberately contains no authenticated operator identity and no
    authorization decision. The operator comes from a trusted OperationContext;
    permission will come from the #06a write-policy boundary.

    `asserted_author` answers "who does the source claim spoke/authored this?".
    It is allowed to be unknown. `subjects` answers "who/what is this about?".
    Neither grants access and neither authenticates the current caller.
    """

    access_domain_id: AccessDomainId
    asserted_author: SourceAuthorRef | None = None
    subjects: tuple[SubjectId, ...] = ()
    perspective_owner: PerspectiveOwnerId | None = None
    perspective_instance: PerspectiveInstanceId | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.access_domain_id, AccessDomainId):
            raise TypeError("access_domain_id must use the AccessDomainId namespace")

        if self.asserted_author is not None and not isinstance(
            self.asserted_author,
            SourceAuthorRef,
        ):
            raise TypeError(
                "asserted_author must use the SourceAuthorRef namespace"
            )

        if not isinstance(self.subjects, tuple) or any(
            not isinstance(subject, SubjectId) for subject in self.subjects
        ):
            raise TypeError("subjects must be a tuple of SubjectId values")

        if len(set(self.subjects)) != len(self.subjects):
            raise ValueError("subjects cannot contain duplicate SubjectId values")

        owner_present = self.perspective_owner is not None
        instance_present = self.perspective_instance is not None
        if owner_present != instance_present:
            raise ValueError(
                "perspective_owner and perspective_instance must be present together"
            )

        if self.perspective_owner is not None and not isinstance(
            self.perspective_owner,
            PerspectiveOwnerId,
        ):
            raise TypeError(
                "perspective_owner must use the PerspectiveOwnerId namespace"
            )
        if self.perspective_instance is not None and not isinstance(
            self.perspective_instance,
            PerspectiveInstanceId,
        ):
            raise TypeError(
                "perspective_instance must use the PerspectiveInstanceId namespace"
            )
