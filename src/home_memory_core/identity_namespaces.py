from __future__ import annotations

from dataclasses import dataclass


class IdentityNamespaceError(ValueError):
    """An identifier crossed HOME's real-data identity namespace contract."""


def _validate_identifier(*, field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise IdentityNamespaceError(f"{field_name} cannot be empty")


@dataclass(frozen=True)
class SourceAuthorRef:
    """Asserted source author/utterer identity; never authentication proof."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="source_author_ref", value=self.value)


@dataclass(frozen=True)
class SubjectId:
    """Identity for something a source is about; never an ACL by itself."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="subject_id", value=self.value)


@dataclass(frozen=True)
class PerspectiveOwnerId:
    """Semantic perspective owner namespace; distinct from operation principal."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="perspective_owner_id", value=self.value)


@dataclass(frozen=True)
class PerspectiveInstanceId:
    """Concrete perspective-instance namespace for future real-data paths."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="perspective_instance_id", value=self.value)


@dataclass(frozen=True)
class DestinationId:
    """Security identity/class of a future disclosure destination."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="destination_id", value=self.value)


@dataclass(frozen=True)
class AccessDomainId:
    """Trusted authorization-domain identity; not derived from `scope`."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="access_domain_id", value=self.value)


@dataclass(frozen=True)
class RequestId:
    """One request/session binding identity, separate from operation identity."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="request_id", value=self.value)

@dataclass(frozen=True)
class OriginNamespaceId:
    """Trusted provider/account/domain namespace for source-origin identity."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="origin_namespace_id", value=self.value)


@dataclass(frozen=True)
class OriginId:
    """Opaque HOME identity for one canonical external event/object."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="origin_id", value=self.value)


@dataclass(frozen=True)
class SnapshotId:
    """Opaque HOME identity for one immutable state/version of an origin."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="snapshot_id", value=self.value)


@dataclass(frozen=True)
class CaptureEventId:
    """Opaque HOME identity for one trusted ingress/capture occurrence."""

    value: str

    def __post_init__(self) -> None:
        _validate_identifier(field_name="capture_event_id", value=self.value)
