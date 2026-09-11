from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    content: str
    authored_by: str
    scope: str
    content_sha256: str


def create_source_record(
    *,
    source_id: str,
    content: str,
    authored_by: str,
    scope: str,
) -> SourceRecord:
    digest = sha256(content.encode("utf-8")).hexdigest()

    return SourceRecord(
        source_id=source_id,
        content=content,
        authored_by=authored_by,
        scope=scope,
        content_sha256=digest,
    )