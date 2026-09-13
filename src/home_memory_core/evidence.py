from dataclasses import dataclass
from hashlib import sha256

from home_memory_core.source import SourceRecord


@dataclass(frozen=True)
class EvidenceRef:
    """Exact source span using zero-based half-open Python str indices.

    start_char and end_char count Unicode code points in the exact,
    unnormalized SourceRecord.content string used to create the reference.
    """

    source_id: str
    source_sha256: str
    start_char: int
    end_char: int


def create_evidence_ref(
    *,
    source: SourceRecord,
    start_char: int,
    end_char: int,
) -> EvidenceRef:
    if start_char < 0:
        raise ValueError("start_char cannot be negative")
    if end_char <= start_char:
        raise ValueError("end_char must be greater than start_char")
    if end_char > len(source.content):
        raise ValueError("evidence range exceeds source content")
    return EvidenceRef(
        source_id=source.source_id,
        source_sha256=source.content_sha256,
        start_char=start_char,
        end_char=end_char,
    )


def read_evidence(
    *,
    source: SourceRecord,
    evidence: EvidenceRef,
) -> str:
    if evidence.source_id != source.source_id:
        raise ValueError("evidence points to a different source")
    actual_hash = sha256(source.content.encode("utf-8")).hexdigest()
    if actual_hash != source.content_sha256:
        raise ValueError("source record content hash is internally inconsistent")
    if evidence.source_sha256 != source.content_sha256:
        raise ValueError("source content no longer matches evidence snapshot")
    if (
        not isinstance(evidence.start_char, int)
        or not isinstance(evidence.end_char, int)
        or evidence.start_char < 0
        or evidence.end_char <= evidence.start_char
        or evidence.end_char > len(source.content)
    ):
        raise ValueError("evidence range is invalid for source content")
    return source.content[evidence.start_char:evidence.end_char]
