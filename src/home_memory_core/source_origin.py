from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from home_memory_core.identity_namespaces import OriginNamespaceId


_TRUSTED_SOURCE_ORIGIN_PROVENANCE_MARKER = object()


class SourceOriginBoundaryError(ValueError):
    """Source-origin provenance was not produced by a trusted ingress adapter."""


class SnapshotKind(StrEnum):
    IMMUTABLE_ORIGIN = "immutable_origin"
    EXTERNAL_REVISION = "external_revision"
    MANUAL_EVENT = "manual_event"


class ReplayDisposition(StrEnum):
    NEW_ORIGIN = "new_origin"
    NEW_SNAPSHOT_EXISTING_ORIGIN = "new_snapshot_existing_origin"
    EXACT_REPLAY_EXISTING_SNAPSHOT = "exact_replay_existing_snapshot"
    BLOCKED_SUPPRESSED_SNAPSHOT_REPLAY = "blocked_suppressed_snapshot_replay"
    BLOCKED_POST_SUPPRESSION_NEW_SNAPSHOT = "blocked_post_suppression_new_snapshot"
    PROVENANCE_CONFLICT = "provenance_conflict"
    UNSUPPORTED_ORIGIN_PROVENANCE = "unsupported_origin_provenance"
    AMBIGUOUS_CROSS_CONNECTOR_PROVENANCE = "ambiguous_cross_connector_provenance"


@dataclass(frozen=True)
class TrustedSourceOriginProvenance:
    """Canonical provenance output of a trusted ingress adapter/policy boundary.

    Ordinary request data may assert provider identifiers, but it may not mint
    this object.  `origin_namespace_id` denotes a configured provider/account /
    domain identity contract; adapter/channel metadata remains audit metadata and
    does not itself make an external event new.
    """

    origin_namespace_id: OriginNamespaceId
    external_object_key: str
    object_kind: str
    origin_key_version: str
    snapshot_kind: SnapshotKind
    external_snapshot_key: str
    ingress_adapter_id: str
    adapter_version: str
    capture_locator: str | None = None
    _marker: object = field(repr=False, compare=False, default=None)

    def __post_init__(self) -> None:
        if self._marker is not _TRUSTED_SOURCE_ORIGIN_PROVENANCE_MARKER:
            raise SourceOriginBoundaryError(
                "source-origin provenance cannot be caller-minted"
            )
        if not isinstance(self.origin_namespace_id, OriginNamespaceId):
            raise SourceOriginBoundaryError(
                "origin_namespace_id must use OriginNamespaceId"
            )
        for name in (
            "external_object_key",
            "object_kind",
            "origin_key_version",
            "external_snapshot_key",
            "ingress_adapter_id",
            "adapter_version",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise SourceOriginBoundaryError(f"{name} cannot be empty")
        if not isinstance(self.snapshot_kind, SnapshotKind):
            raise SourceOriginBoundaryError("snapshot_kind must use SnapshotKind")
        if self.capture_locator is not None:
            if not isinstance(self.capture_locator, str) or not self.capture_locator.strip():
                raise SourceOriginBoundaryError(
                    "capture_locator must be non-empty when present"
                )
