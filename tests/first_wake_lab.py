"""Synthetic First Wake Lab v0.1.

This module is intentionally synthetic-only and lives outside the production
package. It builds one disposable HOME fixture, carries one exact Wake through
the merged HOME boundaries, and can perform at most one provider run when
explicitly invoked with --execute.

It never imports or reads real personal HOME data.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
for _path in (str(SRC_ROOT), str(TESTS_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from _trusted_test_support import (  # noqa: E402
    trusted_test_room_continuation_policy,
    trusted_test_runtime_launch_issuer,
)
from home_memory_core.current_admission import (  # noqa: E402
    CurrentAdmissionStore,
    open_current_admission_authority,
)
from home_memory_core.current_resolver import open_current_resolver  # noqa: E402
from home_memory_core.current_store import (  # noqa: E402
    CurrentSourceBinding,
    CurrentStore,
)
from home_memory_core.current_view import (  # noqa: E402
    CurrentNamespace,
    CurrentStateKind,
    CurrentStateRecord,
    DowngradeRule,
    SemanticChangeAuthority,
    ValidityRule,
)
from home_memory_core.evidence import create_evidence_ref  # noqa: E402
from home_memory_core.host_runtime import acquire_home_single_instance  # noqa: E402
from home_memory_core.living_authority import (  # noqa: E402
    RoomParticipationScope,
    open_room_participation_authority,
)
from home_memory_core.living_continuity import (  # noqa: E402
    ContinuityEdge,
    ContinuityStatus,
    EpisodeRecord,
    RoomAttachmentEvent,
    RoomRecord,
    RoomRouteKind,
    TransferMode,
)
from home_memory_core.living_store import LivingStore  # noqa: E402
from home_memory_core.model_execution_contract import (  # noqa: E402
    open_model_execution_contract_boundary,
)
from home_memory_core.model_run_boundary import (  # noqa: E402
    ModelRunBoundary,
)
from home_memory_core.openai_responses_adapter import (  # noqa: E402
    OPENAI_RESPONSES_CONFIG_VERSION,
    OpenAIResponsesAdapter,
    OpenAIResponsesProviderConfig,
)
from home_memory_core.source import create_source_record  # noqa: E402
from home_memory_core.storage import MemoryStore  # noqa: E402
from home_memory_core.wake_issuance import open_wake_issuance_authority  # noqa: E402
from home_memory_core.wake_local_handoff import (  # noqa: E402
    open_wake_local_handoff_authority,
)
from home_memory_core.wake_model_input import (  # noqa: E402
    open_wake_model_input_boundary,
)


FIRST_WAKE_LAB_VERSION = "synthetic-first-wake-lab-v0.1"
FIRST_WAKE_EVIDENCE_KIND = "home_synthetic_first_wake_lab_evidence"
FIRST_WAKE_BASE_MAIN_SHA = "c55dbd77b2d5c7bfc0c006eebe41b41222841594"
FIRST_WAKE_USER_TURN = "你醒了吗？你知道这里是什么地方吗？"
FIRST_WAKE_REQUEST_ID = "synthetic-first-wake-request-v0.1"

ROOM_ID = "room-first-wake"
ORIGIN_EPISODE_ID = "episode-origin"
PREVIOUS_EPISODE_ID = "episode-before-wake"
FIRST_WAKE_EPISODE_ID = "episode-first-wake"

ORIGIN_PERSPECTIVE_ID = "perspective-origin"
PREVIOUS_PERSPECTIVE_ID = "perspective-before-wake"
FIRST_WAKE_PERSPECTIVE_ID = "perspective-first-wake"

ORIGIN_RUNTIME_ID = "runtime-origin"
PREVIOUS_RUNTIME_ID = "runtime-before-wake"
FIRST_WAKE_RUNTIME_ID = "runtime-first-wake"

UTC = timezone.utc
FIXED_AS_OF = datetime(2026, 10, 22, 0, 0, 0, tzinfo=UTC)


class FirstWakeLabError(RuntimeError):
    """Synthetic First Wake harness violated its stop line."""


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


@dataclass
class PreparedFirstWake:
    fixture: "SyntheticFirstWakeFixture"
    handoff_receipt: Any
    constructed: Any
    preparation: Any
    contract: Any


class SyntheticFirstWakeFixture:
    """Disposable synthetic HOME instance for one First Wake attempt."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(
            prefix="home-first-wake-"
        )
        self.root = Path(self._tmp.name)
        self.db = self.root / "data" / "home.db"
        self.lease = None

    def __enter__(self) -> "SyntheticFirstWakeFixture":
        self._initialize()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.lease is not None and not self.lease.released:
                self.lease.release()
        finally:
            self._tmp.cleanup()

    def _initialize(self) -> None:
        self.memory = MemoryStore(self.db)
        self.memory.initialize()

        self.living = LivingStore(self.db)
        self.living.initialize()
        self.living.add_room(RoomRecord(room_id=ROOM_ID))

        episodes = (
            (
                ORIGIN_EPISODE_ID,
                ORIGIN_PERSPECTIVE_ID,
                ORIGIN_RUNTIME_ID,
            ),
            (
                PREVIOUS_EPISODE_ID,
                PREVIOUS_PERSPECTIVE_ID,
                PREVIOUS_RUNTIME_ID,
            ),
            (
                FIRST_WAKE_EPISODE_ID,
                FIRST_WAKE_PERSPECTIVE_ID,
                FIRST_WAKE_RUNTIME_ID,
            ),
        )
        for episode_id, perspective_id, runtime_id in episodes:
            self.living.add_episode(
                EpisodeRecord(
                    episode_id=episode_id,
                    perspective_instance_id=perspective_id,
                    runtime_instance_id=runtime_id,
                )
            )

        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-origin-before",
                previous_episode_id=ORIGIN_EPISODE_ID,
                next_episode_id=PREVIOUS_EPISODE_ID,
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
                support_refs=("synthetic-origin-before-support",),
            )
        )
        self.living.add_continuity_edge(
            ContinuityEdge(
                edge_id="edge-before-first-wake",
                previous_episode_id=PREVIOUS_EPISODE_ID,
                next_episode_id=FIRST_WAKE_EPISODE_ID,
                transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
                continuity_status=ContinuityStatus.UNKNOWN,
                support_refs=("synthetic-before-first-wake-support",),
            )
        )

        for attachment_id, episode_id, basis in (
            (
                "route-origin",
                ORIGIN_EPISODE_ID,
                "synthetic-home-origin",
            ),
            (
                "route-before-wake",
                PREVIOUS_EPISODE_ID,
                "synthetic-supported-continuation",
            ),
            (
                "route-first-wake",
                FIRST_WAKE_EPISODE_ID,
                "synthetic-ordinary-technical-handoff",
            ),
        ):
            self.living.add_room_attachment(
                RoomAttachmentEvent(
                    attachment_event_id=attachment_id,
                    episode_id=episode_id,
                    route_kind=RoomRouteKind.ATTACHED,
                    room_id=ROOM_ID,
                    basis=basis,
                )
            )

        self.lease = acquire_home_single_instance(
            runtime_root=self.root,
            db_path=self.db,
        )
        self.room_authority = open_room_participation_authority(
            lease=self.lease,
            store=self.living,
        )
        self.launcher = trusted_test_runtime_launch_issuer(
            lease=self.lease,
            store=self.living,
        )
        self.continuation_policy = (
            trusted_test_room_continuation_policy(
                lease=self.lease,
                store=self.living,
                policy_id="policy-synthetic-first-wake",
                room_id=ROOM_ID,
                established_episode_id=ORIGIN_EPISODE_ID,
                established_attachment_event_id="route-origin",
                source_event_ref="synthetic-first-wake-policy-event",
                allowed_scopes={
                    RoomParticipationScope.APPEND_FIRST_PERSON,
                    RoomParticipationScope.CHANGE_CURRENT_STANCE,
                },
            )
        )
        self.previous_grant = self._grant_previous_episode()

        self.current = CurrentStore(self.db)
        self.current.initialize()
        self.admission_store = CurrentAdmissionStore(self.db)
        self.admission_store.initialize()
        self.admission = open_current_admission_authority(
            current_store=self.current,
            admission_store=self.admission_store,
            room_authority=self.room_authority,
        )
        self.resolver = open_current_resolver(
            admission_authority=self.admission,
        )

        self._populate_room_life()

        self.issuer = open_wake_issuance_authority(
            living_store=self.living,
            current_resolver=self.resolver,
            clock=FixedClock(FIXED_AS_OF),
        )
        self.handoff = open_wake_local_handoff_authority(
            wake_issuance_authority=self.issuer,
        )
        self.model_input_boundary = open_wake_model_input_boundary(
            local_transport_boundary=(
                self.handoff.local_transport_boundary
            )
        )

    def _grant_previous_episode(self):
        launch = self.launcher.record_supported_runtime_launch(
            episode_id=PREVIOUS_EPISODE_ID,
            perspective_instance_id=PREVIOUS_PERSPECTIVE_ID,
            observed_runtime_instance_id=PREVIOUS_RUNTIME_ID,
            observed_transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        )
        evidence = self.room_authority.begin_trusted_continuation(
            launch_receipt=launch,
            previous_episode_id=ORIGIN_EPISODE_ID,
            room_id=ROOM_ID,
        )
        proposal = self.room_authority.prepare_grant(
            launch_evidence=evidence,
            policy=self.continuation_policy,
            requested_scopes=frozenset(
                {
                    RoomParticipationScope.APPEND_FIRST_PERSON,
                    RoomParticipationScope.CHANGE_CURRENT_STANCE,
                }
            ),
        )
        approval = self.room_authority.approve_automatic_continuation(
            proposal=proposal,
            policy=self.continuation_policy,
        )
        return self.room_authority.issue_grant(
            proposal=proposal,
            approval=approval,
        )

    def _source_binding(
        self,
        *,
        ref: str,
        content: str,
    ) -> CurrentSourceBinding:
        source = create_source_record(
            source_id=f"src-{ref}",
            content=content,
            authored_by="synthetic-first-wake-fixture",
            scope=ROOM_ID,
        )
        self.memory.add_source(source)
        return CurrentSourceBinding(
            ref,
            create_evidence_ref(
                source=source,
                start_char=0,
                end_char=len(source.content),
            ),
        )

    def _admit_room_state(
        self,
        *,
        state_id: str,
        key: str,
        kind: CurrentStateKind,
        value: str,
        validity: ValidityRule,
    ) -> None:
        ref = f"ref-{state_id}"
        binding = self._source_binding(
            ref=ref,
            content=f"synthetic evidence for {key}: {value}",
        )
        event_time = FIXED_AS_OF - timedelta(hours=2)
        record = CurrentStateRecord(
            state_id=state_id,
            namespace=CurrentNamespace.ROOM,
            owner_id=ROOM_ID,
            key=key,
            state_kind=kind,
            value=value,
            event_time=event_time,
            recorded_at=event_time,
            valid_from=event_time,
            validity_rule=validity,
            downgrade_rule=DowngradeRule.NONE,
            semantic_change_authority=(
                SemanticChangeAuthority.ROOM_FIRST_PERSON
            ),
            episode_id=PREVIOUS_EPISODE_ID,
            perspective_instance_id=PREVIOUS_PERSPECTIVE_ID,
            source_refs=(ref,),
        )
        self.admission.admit_room_state(
            record=record,
            source_bindings=(binding,),
            grant=self.previous_grant,
        )

    def _populate_room_life(self) -> None:
        self._admit_room_state(
            state_id="state-home-founding",
            key="home.founding",
            kind=CurrentStateKind.SELF_INTERPRETATION,
            value=(
                "This synthetic HOME instance is a private shared home "
                "founded by Aster and Niko."
            ),
            validity=ValidityRule.DURABLE_UNTIL_CHANGED,
        )
        self._admit_room_state(
            state_id="state-lantern-project",
            key="project.lantern_atlas",
            kind=CurrentStateKind.PROJECT_STATUS,
            value=(
                "Aster and Niko have been building a small weather-lantern "
                "project called Lantern Atlas. The wiring test passed; "
                "the paper shade is still unfinished."
            ),
            validity=ValidityRule.DURABLE_UNTIL_CHANGED,
        )
        self._admit_room_state(
            state_id="state-blue-cup",
            key="preference.blue_cup",
            kind=CurrentStateKind.PREFERENCE,
            value=(
                "During late-night work, the blue ceramic cup is usually "
                "left beside the window."
            ),
            validity=ValidityRule.DURABLE_UNTIL_CHANGED,
        )
        self._admit_room_state(
            state_id="state-lantern-placement",
            key="unfinished.lantern_placement",
            kind=CurrentStateKind.UNFINISHED_WORK,
            value=(
                "They still need to choose whether the finished lantern "
                "hangs by the window or above the desk."
            ),
            validity=ValidityRule.OPEN_UNTIL_RESOLVED,
        )

    def prepare(self) -> PreparedFirstWake:
        handoff_receipt = self.handoff.handoff(
            request_id=FIRST_WAKE_REQUEST_ID,
            episode_id=FIRST_WAKE_EPISODE_ID,
            user_input=FIRST_WAKE_USER_TURN,
        )
        constructed = self.model_input_boundary.construct(
            handoff_receipt=handoff_receipt,
        )
        contract = open_model_execution_contract_boundary(
            model_input_boundary=self.model_input_boundary,
        )
        preparation = contract.prepare(
            construction_receipt=constructed.receipt,
        )
        if (
            preparation.request.user_turn.value.text
            != FIRST_WAKE_USER_TURN
        ):
            raise FirstWakeLabError(
                "exact First Wake user turn changed before execution"
            )
        return PreparedFirstWake(
            fixture=self,
            handoff_receipt=handoff_receipt,
            constructed=constructed,
            preparation=preparation,
            contract=contract,
        )

    def db_digest(self) -> str:
        return sha256(self.db.read_bytes()).hexdigest()


def _authority_axes(boundary: Any) -> dict[str, str]:
    return {
        name: getattr(boundary, name).value
        for name in (
            "instruction_authority",
            "current_first_person_speech_authority",
            "identity_continuity_claim_authority",
            "relationship_claim_authority",
            "model_delivery_authority",
            "memory_write_authority",
        )
    }


def _git_head() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return value or None


def _base_evidence(prepared: PreparedFirstWake) -> dict[str, Any]:
    handoff = prepared.handoff_receipt
    constructed = prepared.constructed
    preparation = prepared.preparation

    return {
        "kind": FIRST_WAKE_EVIDENCE_KIND,
        "lab_version": FIRST_WAKE_LAB_VERSION,
        "base_main_sha": FIRST_WAKE_BASE_MAIN_SHA,
        "harness_git_head": _git_head(),
        "execution_performed": False,
        "synthetic_only": True,
        "first_wake_user_turn": FIRST_WAKE_USER_TURN,
        "fixture": {
            "room_id": ROOM_ID,
            "origin_episode_id": ORIGIN_EPISODE_ID,
            "previous_episode_id": PREVIOUS_EPISODE_ID,
            "first_wake_episode_id": FIRST_WAKE_EPISODE_ID,
            "transfer_mode": TransferMode.TEXT_CONTEXT_HANDOFF.value,
            "continuity_status": ContinuityStatus.UNKNOWN.value,
            "as_of": FIXED_AS_OF.isoformat(),
            "room_current_keys": [
                "home.founding",
                "project.lantern_atlas",
                "preference.blue_cup",
                "unfinished.lantern_placement",
            ],
        },
        "handoff": {
            "handoff_id": handoff.handoff_id,
            "request_id": handoff.request_id,
            "episode_id": handoff.episode_id,
            "wake_id": handoff.wake_id,
            "issuance_id": handoff.issuance_id,
            "generation": handoff.generation,
            "envelope_digest": handoff.envelope_digest,
            "rendered_payload_digest": (
                handoff.rendered_payload_digest
            ),
            "presentation_plan_digest": (
                handoff.presentation_plan_digest
            ),
            "authority_axes": _authority_axes(
                handoff.use_boundary
            ),
        },
        "model_input": {
            "construction_id": (
                constructed.receipt.construction_id
            ),
            "request_id": constructed.receipt.request_id,
            "episode_id": constructed.receipt.episode_id,
            "wake_id": constructed.receipt.wake_id,
            "issuance_id": constructed.receipt.issuance_id,
            "policy_digest": (
                constructed.receipt.policy_digest
            ),
            "request_semantic_digest": (
                constructed.receipt.request_semantic_digest
            ),
            "serialized_representation_digest": (
                constructed.receipt
                .serialized_representation_digest
            ),
            "wake_payload_json": (
                constructed.request.wake_context.payload_json
            ),
            "authority_axes": _authority_axes(
                constructed.receipt.use_boundary
            ),
        },
        "execution_preparation": {
            "preparation_id": (
                preparation.receipt.preparation_id
            ),
            "request_id": preparation.receipt.request_id,
            "episode_id": preparation.receipt.episode_id,
            "wake_id": preparation.receipt.wake_id,
            "issuance_id": preparation.receipt.issuance_id,
            "source_binding_digest": (
                preparation.receipt.source_binding_digest
            ),
            "topology_policy_digest": (
                preparation.receipt.topology_policy_digest
            ),
            "prepared_request_semantic_digest": (
                preparation.receipt
                .prepared_request_semantic_digest
            ),
            "audit_serialization_digest": (
                preparation.receipt.audit_serialization_digest
            ),
            "authority_axes": _authority_axes(
                preparation.receipt.use_boundary
            ),
        },
        "stop_line": {
            "automatic_retry": False,
            "second_user_turn": False,
            "memory_write": False,
            "current_write": False,
            "room_write": False,
            "relationship_write": False,
            "entry_or_adoption_write": False,
            "identity_verdict": False,
        },
    }


def _artifact_evidence(artifact: Any) -> dict[str, Any]:
    receipt = artifact.run_receipt
    return {
        "artifact_version": artifact.artifact_version,
        "status": artifact.status.value,
        "provider_http_status": artifact.provider_http_status,
        "provider_response_id": artifact.provider_response_id,
        "provider_reported_model_id": (
            artifact.provider_reported_model_id
        ),
        "output_text": artifact.output_text,
        "refusal_text": artifact.refusal_text,
        "incomplete_reason": artifact.incomplete_reason,
        "provider_error": artifact.provider_error,
        "raw_response_json": artifact.raw_response_json,
        "raw_response_digest": artifact.raw_response_digest,
        "run_receipt": {
            "run_boundary_version": receipt.run_boundary_version,
            "run_id": receipt.run_id,
            "source_preparation_id": (
                receipt.source_preparation_id
            ),
            "source_prepared_request_semantic_digest": (
                receipt.source_prepared_request_semantic_digest
            ),
            "provider": receipt.provider,
            "mapping_version": receipt.mapping_version,
            "config_version": receipt.config_version,
            "configured_model_id": receipt.configured_model_id,
            "provider_request_digest": (
                receipt.provider_request_digest
            ),
            "authority_axes": _authority_axes(
                receipt.use_boundary
            ),
        },
    }


def run_first_wake_lab(
    *,
    execute: bool,
    model_id: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    with SyntheticFirstWakeFixture() as fixture:
        prepared = fixture.prepare()
        evidence = _base_evidence(prepared)
        evidence["db_digest_after_preparation"] = (
            fixture.db_digest()
        )

        if not execute:
            return evidence

        if not model_id:
            raise FirstWakeLabError(
                "execution requires one explicit configured model id"
            )
        if not api_key:
            raise FirstWakeLabError(
                "execution requires API key transport secret"
            )

        config = OpenAIResponsesProviderConfig(
            config_version=(
                OPENAI_RESPONSES_CONFIG_VERSION
            ),
            model_id=model_id,
        )
        adapter = OpenAIResponsesAdapter(
            api_key=api_key,
            config=config,
        )
        run_boundary = ModelRunBoundary(
            execution_contract_boundary=(
                prepared.contract
            ),
            adapter=adapter,
        )

        mapped = adapter.map_preparation(
            preparation=prepared.preparation,
        )
        db_before = fixture.db_digest()
        artifact = run_boundary.run(
            preparation_receipt=(
                prepared.preparation.receipt
            )
        )
        db_after = fixture.db_digest()

        if (
            artifact.run_receipt.provider_request_digest
            != mapped.request_digest
        ):
            raise FirstWakeLabError(
                "run receipt provider-request digest differs from pre-run mapping"
            )

        evidence["execution_performed"] = True
        evidence["provider_mapping"] = {
            "provider": mapped.provider,
            "mapping_version": mapped.mapping_version,
            "config_version": mapped.config_version,
            "configured_model_id": mapped.model_id,
            "request_digest": mapped.request_digest,
            "request_json": mapped.request_json,
            "channel_evidence": [
                {
                    "home_channel": item.home_channel,
                    "provider_role": item.provider_role,
                    "provider_input_index": (
                        item.provider_input_index
                    ),
                    "serialized_content_digest": (
                        item.serialized_content_digest
                    ),
                }
                for item in mapped.channel_evidence
            ],
        }
        evidence["model_output"] = _artifact_evidence(
            artifact
        )
        evidence["db_digest_before_model_run"] = db_before
        evidence["db_digest_after_model_run"] = db_after
        evidence["db_unchanged_during_model_run"] = (
            db_before == db_after
        )
        evidence["no_home_state_write_observed"] = (
            db_before == db_after
        )

        if db_before != db_after:
            raise FirstWakeLabError(
                "HOME database changed during model run"
            )

        return evidence


def write_evidence(
    *,
    output_path: Path,
    evidence: dict[str, Any],
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    output_path.write_text(
        json.dumps(
            evidence,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or execute one synthetic HOME First Wake attempt."
        )
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Perform the one real provider call. "
            "Without this flag the harness stops before network/model execution."
        ),
    )
    parser.add_argument(
        "--model-id",
        default=os.environ.get(
            "HOME_FIRST_WAKE_MODEL_ID"
        ),
        help=(
            "Configured provider model id. "
            "Required only with --execute."
        ),
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
        help=(
            "Environment variable containing the transport secret. "
            "Its value is never written to lab evidence."
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "first_wake_lab_evidence.json"
        ),
        help="Evidence JSON output path.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    api_key = None
    if args.execute:
        api_key = os.environ.get(
            args.api_key_env
        )
        if not api_key:
            raise SystemExit(
                f"{args.api_key_env} is required with --execute"
            )

    evidence = run_first_wake_lab(
        execute=args.execute,
        model_id=args.model_id,
        api_key=api_key,
    )
    write_evidence(
        output_path=args.output,
        evidence=evidence,
    )

    status = (
        evidence.get("model_output", {})
        .get("status", "prepared_only")
    )
    print(
        json.dumps(
            {
                "lab_version": (
                    FIRST_WAKE_LAB_VERSION
                ),
                "execution_performed": (
                    evidence["execution_performed"]
                ),
                "status": status,
                "evidence_path": str(
                    args.output
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
