from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
import json
from threading import Lock
from typing import Any
from uuid import uuid4

from home_memory_core.model_execution_contract import (
    DryRunExecutionPreparation,
    DryRunExecutionPreparationReceipt,
    ModelExecutionContractBoundary,
)
from home_memory_core.openai_responses_adapter import (
    OPENAI_RESPONSES_CONFIG_VERSION,
    OPENAI_RESPONSES_MAPPING_VERSION,
    OPENAI_RESPONSES_PROVIDER,
    OpenAIResponsesAdapter,
    OpenAIResponsesMappedRequest,
    OpenAIResponsesProviderConfig,
    ProviderRawResponse,
)
from home_memory_core.process_boundary import (
    current_home_process_instance_id,
)
from home_memory_core.wake_packet import (
    WakeAuthority,
    WakeUseBoundary,
)


MODEL_RUN_BOUNDARY_VERSION = "model-run-boundary-v0.1"
MODEL_OUTPUT_ARTIFACT_VERSION = "model-output-artifact-v0.1"

_RUN_RECEIPT_MARKER = object()
_OUTPUT_MARKER = object()

_DISPATCH_GUARD = Lock()
_DISPATCHED_PREPARATIONS: dict[
    str,
    DryRunExecutionPreparationReceipt,
] = {}


class ModelRunError(RuntimeError):
    """A model run violated the v0.1 run contract."""


class ModelRunAuthorizationError(ModelRunError):
    """Exact live one-shot model-run evidence is missing."""


class ModelRunIntegrityError(ModelRunError):
    """Mapped provider data or response violated the run contract."""


class ModelOutputStatus(StrEnum):
    COMPLETED_TEXT = "completed_text"
    REFUSAL = "refusal"
    INCOMPLETE = "incomplete"
    PROVIDER_FAILURE = "provider_failure"
    REJECTED_RESPONSE = "rejected_response"


@dataclass(frozen=True)
class ModelRunReceipt:
    run_boundary_version: str
    run_id: str
    home_process_instance_id: str
    execution_contract_boundary_id: str
    source_preparation_id: str
    source_prepared_request_semantic_digest: str
    provider: str
    mapping_version: str
    config_version: str
    configured_model_id: str
    provider_request_digest: str
    use_boundary: WakeUseBoundary
    _marker: object = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._marker is not _RUN_RECEIPT_MARKER:
            raise ModelRunAuthorizationError(
                "model run receipt must come from HOME"
            )
        if (
            self.run_boundary_version
            != MODEL_RUN_BOUNDARY_VERSION
        ):
            raise ModelRunIntegrityError(
                "run boundary version is invalid"
            )
        for name in (
            "run_id",
            "home_process_instance_id",
            "execution_contract_boundary_id",
            "source_preparation_id",
            "provider",
            "mapping_version",
            "config_version",
            "configured_model_id",
        ):
            _exact_nonempty_text(
                name,
                getattr(self, name),
            )
        for name in (
            "source_prepared_request_semantic_digest",
            "provider_request_digest",
        ):
            _digest(name, getattr(self, name))
        _require_none_boundary(self.use_boundary)


@dataclass(frozen=True)
class ModelOutputArtifact:
    artifact_version: str
    status: ModelOutputStatus
    run_receipt: ModelRunReceipt
    provider_http_status: int | None
    provider_response_id: str | None
    provider_reported_model_id: str | None
    output_text: str | None
    refusal_text: str | None
    incomplete_reason: str | None
    provider_error: str | None
    raw_response_json: str | None
    raw_response_digest: str | None
    _marker: object = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._marker is not _OUTPUT_MARKER:
            raise ModelRunAuthorizationError(
                "model output artifact must come from HOME"
            )
        if (
            self.artifact_version
            != MODEL_OUTPUT_ARTIFACT_VERSION
        ):
            raise ModelRunIntegrityError(
                "output artifact version is invalid"
            )
        if not isinstance(
            self.status,
            ModelOutputStatus,
        ):
            raise ModelRunIntegrityError(
                "output status is invalid"
            )
        if not isinstance(
            self.run_receipt,
            ModelRunReceipt,
        ):
            raise ModelRunIntegrityError(
                "run receipt is invalid"
            )
        if (
            self.provider_http_status is not None
            and (
                type(self.provider_http_status) is not int
                or self.provider_http_status < 100
                or self.provider_http_status > 599
            )
        ):
            raise ModelRunIntegrityError(
                "provider HTTP status is invalid"
            )
        for name in (
            "provider_response_id",
            "provider_reported_model_id",
            "output_text",
            "refusal_text",
            "incomplete_reason",
            "provider_error",
            "raw_response_json",
        ):
            value = getattr(self, name)
            if (
                value is not None
                and type(value) is not str
            ):
                raise ModelRunIntegrityError(
                    f"{name} must remain exact str or None"
                )
        if self.raw_response_json is None:
            if self.raw_response_digest is not None:
                raise ModelRunIntegrityError(
                    "raw response digest exists without raw response"
                )
        else:
            if type(self.raw_response_json) is not str:
                raise ModelRunIntegrityError(
                    "raw_response_json must remain exact str"
                )
            if self.raw_response_digest is None:
                raise ModelRunIntegrityError(
                    "raw response digest is required"
                )
            _digest(
                "raw_response_digest",
                self.raw_response_digest,
            )
            if (
                _sha256_text(self.raw_response_json)
                != self.raw_response_digest
            ):
                raise ModelRunIntegrityError(
                    "raw response digest mismatch"
                )
        _validate_status_shape(self)


class ModelRunBoundary:
    """One-shot provider/model execution from one exact live preparation."""

    def __init__(
        self,
        *,
        execution_contract_boundary:
            ModelExecutionContractBoundary,
        adapter: OpenAIResponsesAdapter,
    ) -> None:
        if type(execution_contract_boundary) is not ModelExecutionContractBoundary:
            raise TypeError(
                "execution_contract_boundary must be exact "
                "ModelExecutionContractBoundary"
            )
        if type(adapter) is not OpenAIResponsesAdapter:
            raise TypeError(
                "adapter must be exact OpenAIResponsesAdapter"
            )
        self._execution_contract_boundary = (
            execution_contract_boundary
        )
        self._adapter = adapter
        self._origin = self
        self._home_process_instance_id = (
            current_home_process_instance_id()
        )
        self._boundary_id = (
            f"model-run-boundary-{uuid4().hex}"
        )

    @property
    def boundary_id(self) -> str:
        return self._boundary_id

    def run(
        self,
        *,
        preparation_receipt:
            DryRunExecutionPreparationReceipt,
    ) -> ModelOutputArtifact:
        self._assert_live_origin()
        if type(preparation_receipt) is not DryRunExecutionPreparationReceipt:
            raise TypeError(
                "preparation_receipt must be exact "
                "DryRunExecutionPreparationReceipt"
            )

        preparation = ModelExecutionContractBoundary.require_live_preparation(
            self._execution_contract_boundary,
            receipt=preparation_receipt,
        )
        if type(preparation) is not DryRunExecutionPreparation:
            raise ModelRunAuthorizationError(
                "live preparation must be exact DryRunExecutionPreparation"
            )
        if preparation.receipt is not preparation_receipt:
            raise ModelRunAuthorizationError(
                "live preparation receipt is not the exact run receipt"
            )
        _require_none_boundary(
            preparation.receipt.use_boundary
        )

        mapped = self._adapter.map_preparation(
            preparation=preparation
        )
        _require_exact_mapping_source(
            mapped=mapped,
            preparation=preparation,
        )

        run_receipt = ModelRunReceipt(
            run_boundary_version=(
                MODEL_RUN_BOUNDARY_VERSION
            ),
            run_id=f"model-run-{uuid4().hex}",
            home_process_instance_id=(
                self._home_process_instance_id
            ),
            execution_contract_boundary_id=(
                preparation.receipt
                .execution_contract_boundary_id
            ),
            source_preparation_id=(
                preparation.receipt.preparation_id
            ),
            source_prepared_request_semantic_digest=(
                preparation.receipt
                .prepared_request_semantic_digest
            ),
            provider=OPENAI_RESPONSES_PROVIDER,
            mapping_version=mapped.mapping_version,
            config_version=mapped.config_version,
            configured_model_id=mapped.model_id,
            provider_request_digest=(
                mapped.request_digest
            ),
            use_boundary=(
                preparation.receipt.use_boundary
            ),
            _marker=_RUN_RECEIPT_MARKER,
        )

        _claim_preparation_once(
            preparation_receipt
        )
        raw = self._adapter.send_once(
            mapped=mapped
        )
        return _provider_result_to_artifact(
            raw=raw,
            run_receipt=run_receipt,
        )

    def _assert_live_origin(self) -> None:
        if getattr(
            self,
            "_origin",
            None,
        ) is not self:
            raise ModelRunAuthorizationError(
                "model run boundary is not "
                "the originating object"
            )
        if (
            current_home_process_instance_id()
            != self._home_process_instance_id
        ):
            raise ModelRunAuthorizationError(
                "model run boundary belongs to "
                "another HOME process incarnation"
            )


def open_openai_model_run_boundary(
    *,
    execution_contract_boundary:
        ModelExecutionContractBoundary,
    api_key: str,
    model_id: str,
    timeout_seconds: int = 60,
) -> ModelRunBoundary:
    config = OpenAIResponsesProviderConfig(
        config_version=(
            OPENAI_RESPONSES_CONFIG_VERSION
        ),
        model_id=model_id,
        timeout_seconds=timeout_seconds,
    )
    adapter = OpenAIResponsesAdapter(
        api_key=api_key,
        config=config,
    )
    return ModelRunBoundary(
        execution_contract_boundary=(
            execution_contract_boundary
        ),
        adapter=adapter,
    )


def _claim_preparation_once(
    receipt: DryRunExecutionPreparationReceipt,
) -> None:
    with _DISPATCH_GUARD:
        if (
            receipt.preparation_id
            in _DISPATCHED_PREPARATIONS
        ):
            raise ModelRunAuthorizationError(
                "exact preparation has already "
                "been claimed for model dispatch"
            )
        _DISPATCHED_PREPARATIONS[
            receipt.preparation_id
        ] = receipt


def _require_exact_mapping_source(
    *,
    mapped: OpenAIResponsesMappedRequest,
    preparation: DryRunExecutionPreparation,
) -> None:
    if (
        mapped.source_preparation_id
        != preparation.receipt.preparation_id
    ):
        raise ModelRunIntegrityError(
            "mapped source preparation id differs"
        )
    if (
        mapped.source_prepared_request_semantic_digest
        != preparation.receipt
        .prepared_request_semantic_digest
    ):
        raise ModelRunIntegrityError(
            "mapped source semantic digest differs"
        )


def _provider_result_to_artifact(
    *,
    raw: ProviderRawResponse,
    run_receipt: ModelRunReceipt,
) -> ModelOutputArtifact:
    if raw.transport_error is not None:
        return _artifact(
            status=(
                ModelOutputStatus.PROVIDER_FAILURE
            ),
            run_receipt=run_receipt,
            provider_error=raw.transport_error,
        )

    assert raw.http_status is not None
    assert raw.body is not None

    if (
        raw.http_status < 200
        or raw.http_status >= 300
    ):
        return _artifact(
            status=(
                ModelOutputStatus.PROVIDER_FAILURE
            ),
            run_receipt=run_receipt,
            provider_http_status=(
                raw.http_status
            ),
            provider_error=(
                f"provider HTTP status "
                f"{raw.http_status}"
            ),
            raw_response_json=raw.body,
        )

    return _parse_provider_json(
        raw_body=raw.body,
        http_status=raw.http_status,
        run_receipt=run_receipt,
    )


def _parse_provider_json(
    *,
    raw_body: str,
    http_status: int,
    run_receipt: ModelRunReceipt,
) -> ModelOutputArtifact:
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        return _rejected(
            reason=(
                f"invalid provider JSON: {exc}"
            ),
            raw_body=raw_body,
            http_status=http_status,
            run_receipt=run_receipt,
        )

    if not isinstance(parsed, dict):
        return _rejected(
            reason=(
                "provider response root "
                "is not an object"
            ),
            raw_body=raw_body,
            http_status=http_status,
            run_receipt=run_receipt,
        )

    response_status = parsed.get("status")
    if type(response_status) is not str:
        return _rejected(
            reason="provider response status is not exact str",
            raw_body=raw_body,
            http_status=http_status,
            run_receipt=run_receipt,
        )
    if response_status not in {
        "completed",
        "incomplete",
        "failed",
    }:
        return _rejected(
            reason=(
                "provider response status "
                "is not allowlisted"
            ),
            raw_body=raw_body,
            http_status=http_status,
            run_receipt=run_receipt,
        )

    response_id = parsed.get("id")
    if (
        type(response_id) is not str
        or not response_id
    ):
        return _rejected(
            reason="provider response id is not non-empty exact str",
            raw_body=raw_body,
            http_status=http_status,
            run_receipt=run_receipt,
        )

    reported_model = parsed.get("model")
    if (
        type(reported_model) is not str
        or not reported_model
    ):
        return _rejected(
            reason="provider model id is not non-empty exact str",
            raw_body=raw_body,
            http_status=http_status,
            run_receipt=run_receipt,
        )

    if response_status == "failed":
        return _artifact(
            status=(
                ModelOutputStatus.PROVIDER_FAILURE
            ),
            run_receipt=run_receipt,
            provider_http_status=http_status,
            provider_response_id=response_id,
            provider_reported_model_id=(
                reported_model
            ),
            provider_error=_safe_json_summary(
                parsed.get("error")
            ),
            raw_response_json=raw_body,
        )

    output = parsed.get("output")
    if not isinstance(output, list):
        return _rejected(
            reason=(
                "provider output is not an array"
            ),
            raw_body=raw_body,
            http_status=http_status,
            run_receipt=run_receipt,
        )

    text_parts: list[str] = []
    refusal_parts: list[str] = []

    for item in output:
        if not isinstance(item, dict):
            return _rejected(
                reason=(
                    "provider output item "
                    "is not an object"
                ),
                raw_body=raw_body,
                http_status=http_status,
                run_receipt=run_receipt,
            )

        item_type = item.get("type")
        if item_type == "reasoning":
            reason = _validate_reasoning_item(
                item=item,
                root_status=response_status,
            )
            if reason is not None:
                return _rejected(
                    reason=reason,
                    raw_body=raw_body,
                    http_status=http_status,
                    run_receipt=run_receipt,
                )
            continue

        if item_type != "message":
            return _rejected(
                reason=(
                    "provider output item type "
                    f"is not allowlisted: "
                    f"{item_type!r}"
                ),
                raw_body=raw_body,
                http_status=http_status,
                run_receipt=run_receipt,
            )

        message_id = item.get("id")
        if (
            type(message_id) is not str
            or not message_id
        ):
            return _rejected(
                reason="provider message id is not non-empty exact str",
                raw_body=raw_body,
                http_status=http_status,
                run_receipt=run_receipt,
            )

        if item.get("role") != "assistant":
            return _rejected(
                reason=(
                    "provider message output "
                    "role is not assistant"
                ),
                raw_body=raw_body,
                http_status=http_status,
                run_receipt=run_receipt,
            )

        message_status = item.get("status")
        if type(message_status) is not str:
            return _rejected(
                reason="provider message status is not exact str",
                raw_body=raw_body,
                http_status=http_status,
                run_receipt=run_receipt,
            )
        if message_status not in {
            "completed",
            "incomplete",
            "in_progress",
        }:
            return _rejected(
                reason="provider message status is not allowlisted",
                raw_body=raw_body,
                http_status=http_status,
                run_receipt=run_receipt,
            )
        if response_status == "completed" and message_status != "completed":
            return _rejected(
                reason=(
                    "completed provider response contains "
                    "non-completed message item"
                ),
                raw_body=raw_body,
                http_status=http_status,
                run_receipt=run_receipt,
            )
        if response_status == "incomplete" and message_status == "in_progress":
            return _rejected(
                reason=(
                    "terminal incomplete response contains "
                    "in-progress message item"
                ),
                raw_body=raw_body,
                http_status=http_status,
                run_receipt=run_receipt,
            )

        content = item.get("content")
        if not isinstance(content, list):
            return _rejected(
                reason=(
                    "provider message content "
                    "is not an array"
                ),
                raw_body=raw_body,
                http_status=http_status,
                run_receipt=run_receipt,
            )

        for content_item in content:
            if not isinstance(
                content_item,
                dict,
            ):
                return _rejected(
                    reason=(
                        "provider content item "
                        "is not an object"
                    ),
                    raw_body=raw_body,
                    http_status=http_status,
                    run_receipt=run_receipt,
                )

            content_type = (
                content_item.get("type")
            )
            if content_type == "output_text":
                annotations = content_item.get("annotations")
                if type(annotations) is not list:
                    return _rejected(
                        reason=(
                            "provider output_text annotations "
                            "is not an array"
                        ),
                        raw_body=raw_body,
                        http_status=http_status,
                        run_receipt=run_receipt,
                    )
                if annotations:
                    return _rejected(
                        reason=(
                            "provider output_text annotations "
                            "are outside v0.1 allowlist"
                        ),
                        raw_body=raw_body,
                        http_status=http_status,
                        run_receipt=run_receipt,
                    )
                logprobs = content_item.get("logprobs")
                if (
                    logprobs is not None
                    and type(logprobs) is not list
                ):
                    return _rejected(
                        reason=(
                            "provider output_text logprobs "
                            "is not an array or None"
                        ),
                        raw_body=raw_body,
                        http_status=http_status,
                        run_receipt=run_receipt,
                    )
                value = content_item.get("text")
                if type(value) is not str:
                    return _rejected(
                        reason=(
                            "provider output_text "
                            "is not exact str"
                        ),
                        raw_body=raw_body,
                        http_status=http_status,
                        run_receipt=run_receipt,
                    )
                text_parts.append(value)
            elif content_type == "refusal":
                value = content_item.get(
                    "refusal"
                )
                if type(value) is not str:
                    return _rejected(
                        reason=(
                            "provider refusal "
                            "is not exact str"
                        ),
                        raw_body=raw_body,
                        http_status=http_status,
                        run_receipt=run_receipt,
                    )
                refusal_parts.append(value)
            else:
                return _rejected(
                    reason=(
                        "provider content type "
                        f"is not allowlisted: "
                        f"{content_type!r}"
                    ),
                    raw_body=raw_body,
                    http_status=http_status,
                    run_receipt=run_receipt,
                )

    if text_parts and refusal_parts:
        return _rejected(
            reason=(
                "provider response mixes "
                "output text and refusal"
            ),
            raw_body=raw_body,
            http_status=http_status,
            run_receipt=run_receipt,
        )

    if response_status == "incomplete":
        return _artifact(
            status=ModelOutputStatus.INCOMPLETE,
            run_receipt=run_receipt,
            provider_http_status=http_status,
            provider_response_id=response_id,
            provider_reported_model_id=(
                reported_model
            ),
            incomplete_reason=_safe_json_summary(
                parsed.get(
                    "incomplete_details"
                )
            ),
            raw_response_json=raw_body,
        )

    if refusal_parts:
        return _artifact(
            status=ModelOutputStatus.REFUSAL,
            run_receipt=run_receipt,
            provider_http_status=http_status,
            provider_response_id=response_id,
            provider_reported_model_id=(
                reported_model
            ),
            refusal_text="".join(
                refusal_parts
            ),
            raw_response_json=raw_body,
        )

    if not text_parts:
        return _rejected(
            reason=(
                "completed provider response "
                "has no output text/refusal"
            ),
            raw_body=raw_body,
            http_status=http_status,
            run_receipt=run_receipt,
        )

    return _artifact(
        status=(
            ModelOutputStatus.COMPLETED_TEXT
        ),
        run_receipt=run_receipt,
        provider_http_status=http_status,
        provider_response_id=response_id,
        provider_reported_model_id=(
            reported_model
        ),
        output_text="".join(text_parts),
        raw_response_json=raw_body,
    )



def _validate_reasoning_item(
    *,
    item: dict[str, Any],
    root_status: str,
) -> str | None:
    reasoning_id = item.get("id")
    if (
        type(reasoning_id) is not str
        or not reasoning_id
    ):
        return "provider reasoning id is not non-empty exact str"

    reasoning_status = item.get("status")
    if type(reasoning_status) is not str:
        return "provider reasoning status is not exact str"
    if reasoning_status not in {
        "completed",
        "incomplete",
        "in_progress",
    }:
        return "provider reasoning status is not allowlisted"
    if root_status == "completed" and reasoning_status != "completed":
        return (
            "completed provider response contains "
            "non-completed reasoning item"
        )
    if root_status == "incomplete" and reasoning_status == "in_progress":
        return (
            "terminal incomplete response contains "
            "in-progress reasoning item"
        )

    summary = item.get("summary")
    if type(summary) is not list:
        return "provider reasoning summary is not an array"
    for summary_item in summary:
        if type(summary_item) is not dict:
            return "provider reasoning summary item is not an object"
        if summary_item.get("type") != "summary_text":
            return (
                "provider reasoning summary type "
                "is not summary_text"
            )
        summary_text = summary_item.get("text")
        if type(summary_text) is not str:
            return (
                "provider reasoning summary text "
                "is not exact str"
            )

    content = item.get("content")
    if content is not None:
        if type(content) is not list:
            return "provider reasoning content is not an array"
        for content_item in content:
            if type(content_item) is not dict:
                return "provider reasoning content item is not an object"
            if content_item.get("type") != "reasoning_text":
                return (
                    "provider reasoning content type "
                    "is not reasoning_text"
                )
            reasoning_text = content_item.get("text")
            if type(reasoning_text) is not str:
                return (
                    "provider reasoning content text "
                    "is not exact str"
                )

    encrypted_content = item.get("encrypted_content")
    if (
        encrypted_content is not None
        and type(encrypted_content) is not str
    ):
        return "provider reasoning encrypted_content is not exact str or None"

    return None


def _artifact(
    *,
    status: ModelOutputStatus,
    run_receipt: ModelRunReceipt,
    provider_http_status: int | None = None,
    provider_response_id: str | None = None,
    provider_reported_model_id:
        str | None = None,
    output_text: str | None = None,
    refusal_text: str | None = None,
    incomplete_reason: str | None = None,
    provider_error: str | None = None,
    raw_response_json: str | None = None,
) -> ModelOutputArtifact:
    return ModelOutputArtifact(
        artifact_version=(
            MODEL_OUTPUT_ARTIFACT_VERSION
        ),
        status=status,
        run_receipt=run_receipt,
        provider_http_status=(
            provider_http_status
        ),
        provider_response_id=(
            provider_response_id
        ),
        provider_reported_model_id=(
            provider_reported_model_id
        ),
        output_text=output_text,
        refusal_text=refusal_text,
        incomplete_reason=incomplete_reason,
        provider_error=provider_error,
        raw_response_json=raw_response_json,
        raw_response_digest=(
            _sha256_text(raw_response_json)
            if raw_response_json is not None
            else None
        ),
        _marker=_OUTPUT_MARKER,
    )


def _rejected(
    *,
    reason: str,
    raw_body: str,
    http_status: int,
    run_receipt: ModelRunReceipt,
) -> ModelOutputArtifact:
    return _artifact(
        status=(
            ModelOutputStatus.REJECTED_RESPONSE
        ),
        run_receipt=run_receipt,
        provider_http_status=http_status,
        provider_error=reason,
        raw_response_json=raw_body,
    )


def _validate_status_shape(
    artifact: ModelOutputArtifact,
) -> None:
    if (
        artifact.status
        is ModelOutputStatus.COMPLETED_TEXT
    ):
        if (
            artifact.output_text is None
            or artifact.refusal_text is not None
            or artifact.incomplete_reason
                is not None
            or artifact.provider_error
                is not None
        ):
            raise ModelRunIntegrityError(
                "completed output shape is invalid"
            )
        return

    if (
        artifact.status
        is ModelOutputStatus.REFUSAL
    ):
        if (
            artifact.refusal_text is None
            or artifact.output_text is not None
            or artifact.incomplete_reason
                is not None
            or artifact.provider_error
                is not None
        ):
            raise ModelRunIntegrityError(
                "refusal output shape is invalid"
            )
        return

    if (
        artifact.status
        is ModelOutputStatus.INCOMPLETE
    ):
        if (
            artifact.output_text is not None
            or artifact.refusal_text is not None
        ):
            raise ModelRunIntegrityError(
                "incomplete output cannot be "
                "normal text/refusal"
            )
        return

    if artifact.status in {
        ModelOutputStatus.PROVIDER_FAILURE,
        ModelOutputStatus.REJECTED_RESPONSE,
    }:
        if (
            artifact.provider_error is None
            or artifact.output_text is not None
            or artifact.refusal_text is not None
        ):
            raise ModelRunIntegrityError(
                "failure/rejected output "
                "shape is invalid"
            )



def _safe_json_summary(
    value: Any,
) -> str:
    if value is None:
        return "unspecified"
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        return repr(value)


def _require_none_boundary(
    boundary: WakeUseBoundary,
) -> None:
    if not isinstance(
        boundary,
        WakeUseBoundary,
    ):
        raise ModelRunIntegrityError(
            "Wake use boundary is invalid"
        )
    for name in (
        "instruction_authority",
        "current_first_person_speech_authority",
        "identity_continuity_claim_authority",
        "relationship_claim_authority",
        "model_delivery_authority",
        "memory_write_authority",
    ):
        if (
            getattr(boundary, name)
            is not WakeAuthority.NONE
        ):
            raise ModelRunIntegrityError(
                f"Wake authority axis {name} "
                "must remain NONE"
            )


def _sha256_text(
    value: str,
) -> str:
    if type(value) is not str:
        raise ModelRunIntegrityError(
            "digest input must remain exact str"
        )
    return sha256(
        value.encode("utf-8")
    ).hexdigest()


def _digest(
    name: str,
    value: str,
) -> None:
    if (
        type(value) is not str
        or len(value) != 64
        or any(
            character
            not in "0123456789abcdef"
            for character in value
        )
    ):
        raise ModelRunIntegrityError(
            f"{name} is not a sha256 hex digest"
        )


def _exact_nonempty_text(
    name: str,
    value: str,
) -> None:
    if (
        type(value) is not str
        or not value
    ):
        raise ModelRunIntegrityError(
            f"{name} must be non-empty exact str"
        )
