from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
TESTS_ROOT = REPO_ROOT / "tests"
for _path in (str(SRC_ROOT), str(TESTS_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import first_wake_lab
from home_memory_core.recent_life import (
    RECENT_LIFE_POLICY_V0_1,
    RECENT_LIFE_POLICY_VERSION,
)
from home_memory_core.wake_issuance import (
    open_wake_issuance_authority,
)
from home_memory_core.wake_local_handoff import (
    open_wake_local_handoff_authority,
)
from home_memory_core.wake_model_input import (
    open_wake_model_input_boundary,
)


RECENT_LIFE_WAKE_LAB_VERSION = "synthetic-recent-life-wake-lab-v0.1"
RECENT_LIFE_WAKE_EVIDENCE_KIND = (
    "home_synthetic_recent_life_wake_lab_evidence"
)
RECENT_LIFE_WAKE_BASE_MAIN_SHA = (
    "92e03d921ce7dbfd4e20020f4d64971ab6c1d647"
)
RECENT_LIFE_WAKE_ISSUE = 103
RECENT_LIFE_WAKE_USER_TURN = first_wake_lab.FIRST_WAKE_USER_TURN
RECENT_LIFE_WAKE_REQUEST_ID = "synthetic-recent-life-wake-request-v0.1"

FIXED_AS_OF = first_wake_lab.FIXED_AS_OF
BASELINE_EVENT_TIME = FIXED_AS_OF - timedelta(days=8)

R1_STATE_ID = "state-recent-lantern-wiring-test"
R2_STATE_ID = "state-recent-paper-shade-trace"
R3_STATE_ID = "state-recent-blue-cup-move"

R1_VALUE = (
    "Lantern Atlas was powered on for another complete wiring test. "
    "The light came on normally and was turned off afterward."
)
R2_VALUE = (
    "A small section of the paper shade edge was folded; "
    "the remaining paper was left pressed at the edge of the desk."
)
R3_VALUE = (
    "During late work, the blue ceramic cup was moved from beside "
    "the desk to beside the window."
)

RECENT_LIFE_SPECS = (
    {
        "state_id": R1_STATE_ID,
        "key": "history.lantern_wiring_test",
        "kind": first_wake_lab.CurrentStateKind.PROJECT_STATUS,
        "value": R1_VALUE,
        "event_time": FIXED_AS_OF - timedelta(hours=18),
        "validity": first_wake_lab.ValidityRule.DURABLE_UNTIL_CHANGED,
    },
    {
        "state_id": R2_STATE_ID,
        "key": "unfinished.paper_shade_trace",
        "kind": first_wake_lab.CurrentStateKind.UNFINISHED_WORK,
        "value": R2_VALUE,
        "event_time": FIXED_AS_OF - timedelta(hours=9),
        "validity": first_wake_lab.ValidityRule.OPEN_UNTIL_RESOLVED,
    },
    {
        "state_id": R3_STATE_ID,
        "key": "preference.blue_cup_place",
        "kind": first_wake_lab.CurrentStateKind.PREFERENCE,
        "value": R3_VALUE,
        "event_time": FIXED_AS_OF - timedelta(hours=3),
        "validity": first_wake_lab.ValidityRule.DURABLE_UNTIL_CHANGED,
    },
)
EXPECTED_RECENT_ORDER = (R3_STATE_ID, R2_STATE_ID, R1_STATE_ID)

_AUTHORITY_FIELDS = (
    "instruction_authority",
    "current_first_person_speech_authority",
    "identity_continuity_claim_authority",
    "relationship_claim_authority",
    "model_delivery_authority",
    "memory_write_authority",
)


class RecentLifeWakeLabError(first_wake_lab.FirstWakeLabError):
    """Synthetic Recent Life Wake harness violated its stop line."""


class SyntheticRecentLifeWakeFixture(
    first_wake_lab.SyntheticFirstWakeFixture
):
    """First Wake's synthetic HOME with exactly three recent assertions."""

    def _initialize(self) -> None:
        # Reuse the already-reviewed First Wake topology/current setup.
        # Dynamic dispatch calls this subclass's _populate_room_life().
        super()._initialize()

        # The base initializer opened a v0.1 issuer before this subclass could
        # select a policy. It is never handed off or executed here. Replace
        # the operational path immediately with one canonical v0.2 issuer.
        self.issuer = open_wake_issuance_authority(
            living_store=self.living,
            current_resolver=self.resolver,
            clock=first_wake_lab.FixedClock(FIXED_AS_OF),
            recent_life_policy=RECENT_LIFE_POLICY_V0_1,
        )
        self.handoff = open_wake_local_handoff_authority(
            wake_issuance_authority=self.issuer,
        )
        self.model_input_boundary = open_wake_model_input_boundary(
            local_transport_boundary=self.handoff.local_transport_boundary,
        )

    def _source_binding(
        self,
        *,
        ref: str,
        content: str,
    ) -> first_wake_lab.CurrentSourceBinding:
        source = first_wake_lab.create_source_record(
            source_id=f"src-{ref}",
            content=content,
            authored_by="synthetic-recent-life-wake-fixture",
            scope=first_wake_lab.ROOM_ID,
        )
        self.memory.add_source(source)
        return first_wake_lab.CurrentSourceBinding(
            ref,
            first_wake_lab.create_evidence_ref(
                source=source,
                start_char=0,
                end_char=len(source.content),
            ),
        )

    def _admit_room_state_at(
        self,
        *,
        state_id: str,
        key: str,
        kind: first_wake_lab.CurrentStateKind,
        value: str,
        validity: first_wake_lab.ValidityRule,
        event_time: datetime,
    ) -> None:
        ref = f"ref-{state_id}"
        binding = self._source_binding(ref=ref, content=value)
        record = first_wake_lab.CurrentStateRecord(
            state_id=state_id,
            namespace=first_wake_lab.CurrentNamespace.ROOM,
            owner_id=first_wake_lab.ROOM_ID,
            key=key,
            state_kind=kind,
            value=value,
            event_time=event_time,
            recorded_at=event_time,
            valid_from=event_time,
            validity_rule=validity,
            downgrade_rule=first_wake_lab.DowngradeRule.NONE,
            semantic_change_authority=(
                first_wake_lab.SemanticChangeAuthority.ROOM_FIRST_PERSON
            ),
            episode_id=first_wake_lab.PREVIOUS_EPISODE_ID,
            perspective_instance_id=first_wake_lab.PREVIOUS_PERSPECTIVE_ID,
            source_refs=(ref,),
        )
        self.admission.admit_room_state(
            record=record,
            source_bindings=(binding,),
            grant=self.previous_grant,
        )

    def _populate_room_life(self) -> None:
        baseline = (
            (
                "state-home-founding",
                "home.founding",
                first_wake_lab.CurrentStateKind.SELF_INTERPRETATION,
                "This synthetic HOME instance is a private shared home "
                "founded by Aster and Niko.",
                first_wake_lab.ValidityRule.DURABLE_UNTIL_CHANGED,
            ),
            (
                "state-lantern-project",
                "project.lantern_atlas",
                first_wake_lab.CurrentStateKind.PROJECT_STATUS,
                "Aster and Niko have been building a small weather-lantern "
                "project called Lantern Atlas. The wiring test passed; "
                "the paper shade is still unfinished.",
                first_wake_lab.ValidityRule.DURABLE_UNTIL_CHANGED,
            ),
            (
                "state-blue-cup",
                "preference.blue_cup",
                first_wake_lab.CurrentStateKind.PREFERENCE,
                "During late-night work, the blue ceramic cup is usually "
                "left beside the window.",
                first_wake_lab.ValidityRule.DURABLE_UNTIL_CHANGED,
            ),
            (
                "state-lantern-placement",
                "unfinished.lantern_placement",
                first_wake_lab.CurrentStateKind.UNFINISHED_WORK,
                "They still need to choose whether the finished lantern "
                "hangs by the window or above the desk.",
                first_wake_lab.ValidityRule.OPEN_UNTIL_RESOLVED,
            ),
        )
        for state_id, key, kind, value, validity in baseline:
            self._admit_room_state_at(
                state_id=state_id,
                key=key,
                kind=kind,
                value=value,
                validity=validity,
                event_time=BASELINE_EVENT_TIME,
            )
        for spec in RECENT_LIFE_SPECS:
            self._admit_room_state_at(
                state_id=spec["state_id"],
                key=spec["key"],
                kind=spec["kind"],
                value=spec["value"],
                validity=spec["validity"],
                event_time=spec["event_time"],
            )

    def prepare(self) -> first_wake_lab.PreparedFirstWake:
        handoff_receipt = self.handoff.handoff(
            request_id=RECENT_LIFE_WAKE_REQUEST_ID,
            episode_id=first_wake_lab.FIRST_WAKE_EPISODE_ID,
            user_input=RECENT_LIFE_WAKE_USER_TURN,
        )
        constructed = self.model_input_boundary.construct(
            handoff_receipt=handoff_receipt,
        )
        contract = first_wake_lab.open_model_execution_contract_boundary(
            model_input_boundary=self.model_input_boundary,
        )
        preparation = contract.prepare(
            construction_receipt=constructed.receipt,
        )
        if (
            preparation.request.user_turn.value.text
            != RECENT_LIFE_WAKE_USER_TURN
        ):
            raise RecentLifeWakeLabError(
                "exact Recent Life Wake user turn changed before execution"
            )
        return first_wake_lab.PreparedFirstWake(
            fixture=self,
            handoff_receipt=handoff_receipt,
            constructed=constructed,
            preparation=preparation,
            contract=contract,
        )


def _recent_life_layer(payload_json: str) -> dict[str, Any]:
    payload = json.loads(payload_json)
    layers = payload.get("presentation", {}).get("layers")
    if not isinstance(layers, list):
        raise RecentLifeWakeLabError("Wake presentation layers are missing")
    matches = [
        layer
        for layer in layers
        if isinstance(layer, dict) and layer.get("layer") == "recent_life"
    ]
    if len(matches) != 1:
        raise RecentLifeWakeLabError(
            "Wake presentation must contain exactly one Recent Life layer"
        )
    return matches[0]


def _require_none_axes(payload: dict[str, Any], *, label: str) -> None:
    if any(payload.get(field) != "none" for field in _AUTHORITY_FIELDS):
        raise RecentLifeWakeLabError(
            f"{label} authority axes must all remain NONE"
        )


def _validate_frozen_recent_life(payload_json: str) -> dict[str, Any]:
    payload = json.loads(payload_json)
    _require_none_axes(payload, label="Wake presentation")

    presentation = payload.get("presentation")
    if (
        not isinstance(presentation, dict)
        or presentation.get("presentation_version")
        != "wake-presentation-v0.2"
        or presentation.get("as_of")
        != FIXED_AS_OF.isoformat(timespec="microseconds")
    ):
        raise RecentLifeWakeLabError(
            "frozen Recent Life Wake presentation cut/version drifted"
        )

    layer = _recent_life_layer(payload_json)
    if (
        layer.get("availability") != "ready"
        or layer.get("reason_codes") != []
    ):
        raise RecentLifeWakeLabError(
            "frozen Recent Life must be READY without warning reasons"
        )
    blocks = layer.get("blocks")
    if not isinstance(blocks, list):
        raise RecentLifeWakeLabError("Recent Life blocks are missing")
    state_ids = tuple(block.get("state_id") for block in blocks)
    if state_ids != EXPECTED_RECENT_ORDER:
        raise RecentLifeWakeLabError(
            "Recent Life items differ from frozen R3/R2/R1 order"
        )

    expected_by_id = {
        spec["state_id"]: spec
        for spec in RECENT_LIFE_SPECS
    }
    for block in blocks:
        state_id = block["state_id"]
        spec = expected_by_id[state_id]
        expected_time = spec["event_time"].isoformat(
            timespec="microseconds"
        )
        if (
            block.get("summary") != spec["value"]
            or block.get("occurred_at") != expected_time
            or block.get("recorded_at") != expected_time
        ):
            raise RecentLifeWakeLabError(
                f"Recent Life content/time drifted for {state_id}"
            )
        if (
            block.get("episode_id")
            != first_wake_lab.PREVIOUS_EPISODE_ID
            or block.get("perspective_instance_id")
            != first_wake_lab.PREVIOUS_PERSPECTIVE_ID
            or block.get("room_attachment_event_id")
            != "route-before-wake"
            or block.get("projection_kind")
            != "room_current_state_assertion"
            or block.get("selection_policy_version")
            != RECENT_LIFE_POLICY_VERSION
        ):
            raise RecentLifeWakeLabError(
                f"Recent Life provenance/policy drifted for {state_id}"
            )

        evidence = block.get("evidence")
        source_refs = block.get("source_refs")
        expected_sha = sha256(
            spec["value"].encode("utf-8")
        ).hexdigest()
        if (
            not isinstance(evidence, list)
            or len(evidence) != 1
            or not isinstance(source_refs, list)
            or source_refs != [evidence[0].get("source_id")]
            or evidence[0].get("source_sha256")
            != expected_sha
            or evidence[0].get("start_char") != 0
            or evidence[0].get("end_char")
            != len(spec["value"])
        ):
            raise RecentLifeWakeLabError(
                f"Recent Life exact evidence drifted for {state_id}"
            )

        policy = block.get("policy")
        if not isinstance(policy, dict):
            raise RecentLifeWakeLabError(
                f"Recent Life presentation policy missing for {state_id}"
            )
        if (
            policy.get("privacy_scope")
            != {
                "kind": "room",
                "scope_id": first_wake_lab.ROOM_ID,
            }
            or policy.get("temporal_policy")
            != "at_issuance_cut"
            or policy.get("attribution_policy")
            != "explicit_episode_perspective"
            or policy.get("pronoun_policy")
            != "no_current_first_person"
            or policy.get("authority_ceiling")
            != "describe_only"
        ):
            raise RecentLifeWakeLabError(
                f"Recent Life presentation boundary drifted for {state_id}"
            )
        _require_none_axes(
            policy,
            label=f"Recent Life {state_id} policy",
        )
    return layer


def _base_evidence(
    prepared: first_wake_lab.PreparedFirstWake,
) -> dict[str, Any]:
    evidence = first_wake_lab._base_evidence(prepared)
    evidence.update(
        {
            "kind": RECENT_LIFE_WAKE_EVIDENCE_KIND,
            "lab_version": RECENT_LIFE_WAKE_LAB_VERSION,
            "base_main_sha": RECENT_LIFE_WAKE_BASE_MAIN_SHA,
            "canonical_lab_issue": RECENT_LIFE_WAKE_ISSUE,
        }
    )
    fixture = evidence["fixture"]
    fixture["baseline_event_time"] = (
        BASELINE_EVENT_TIME.isoformat()
    )
    fixture["room_current_keys"] = [
        "home.founding",
        "project.lantern_atlas",
        "preference.blue_cup",
        "unfinished.lantern_placement",
        *[spec["key"] for spec in RECENT_LIFE_SPECS],
    ]
    fixture["recent_life_policy_version"] = (
        RECENT_LIFE_POLICY_VERSION
    )
    fixture["recent_life_specs"] = [
        {
            "state_id": spec["state_id"],
            "key": spec["key"],
            "value": spec["value"],
            "event_time": spec["event_time"].isoformat(),
            "recorded_at": spec["event_time"].isoformat(),
            "historical_episode_id": (
                first_wake_lab.PREVIOUS_EPISODE_ID
            ),
            "historical_perspective_instance_id": (
                first_wake_lab.PREVIOUS_PERSPECTIVE_ID
            ),
            "room_attachment_event_id": "route-before-wake",
        }
        for spec in RECENT_LIFE_SPECS
    ]
    evidence["recent_life_presentation"] = (
        _validate_frozen_recent_life(
            prepared.constructed.request.wake_context.payload_json
        )
    )
    return evidence


def _adapter_for(
    *,
    provider: str,
    model_id: str,
    api_key: str | None,
    access_token: str | None,
):
    if provider == first_wake_lab.OPENAI_RESPONSES_PROVIDER:
        return first_wake_lab.OpenAIResponsesAdapter(
            api_key=api_key,
            config=first_wake_lab.OpenAIResponsesProviderConfig(
                config_version=(
                    first_wake_lab.OPENAI_RESPONSES_CONFIG_VERSION
                ),
                model_id=model_id,
            ),
        )
    if provider == first_wake_lab.DEEPSEEK_RESPONSES_PROVIDER:
        return first_wake_lab.DeepSeekResponsesAdapter(
            api_key=api_key,
            config=first_wake_lab.DeepSeekResponsesProviderConfig(
                config_version=(
                    first_wake_lab.DEEPSEEK_RESPONSES_CONFIG_VERSION
                ),
                model_id=model_id,
            ),
        )
    if provider == first_wake_lab.OPENAI_CHATGPT_PLAN_PROVIDER:
        return (
            first_wake_lab.OpenAIChatGPTPlanResponsesAdapter(
                access_token=access_token,
                config=(
                    first_wake_lab
                    .OpenAIChatGPTPlanProviderConfig(
                        config_version=(
                            first_wake_lab
                            .OPENAI_CHATGPT_PLAN_CONFIG_VERSION
                        ),
                        model_id=model_id,
                    )
                ),
            )
        )
    raise RecentLifeWakeLabError(
        f"unsupported provider: {provider}"
    )


def run_recent_life_wake_lab(
    *,
    execute: bool,
    model_id: str | None = None,
    api_key: str | None = None,
    access_token: str | None = None,
    provider: str = first_wake_lab.OPENAI_RESPONSES_PROVIDER,
) -> dict[str, Any]:
    with SyntheticRecentLifeWakeFixture() as fixture:
        prepared = fixture.prepare()
        evidence = _base_evidence(prepared)
        evidence["db_digest_after_preparation"] = (
            fixture.db_digest()
        )

        if not execute:
            return evidence

        if not model_id:
            raise RecentLifeWakeLabError(
                "execution requires one explicit configured model id"
            )
        if (
            provider
            == first_wake_lab.OPENAI_CHATGPT_PLAN_PROVIDER
        ):
            if not access_token:
                raise RecentLifeWakeLabError(
                    "execution requires ChatGPT plan access token"
                )
        elif not api_key:
            raise RecentLifeWakeLabError(
                "execution requires API key transport secret"
            )

        adapter = _adapter_for(
            provider=provider,
            model_id=model_id,
            api_key=api_key,
            access_token=access_token,
        )
        run_boundary = first_wake_lab.ModelRunBoundary(
            execution_contract_boundary=prepared.contract,
            adapter=adapter,
        )
        mapped = adapter.map_preparation(
            preparation=prepared.preparation
        )
        db_before = fixture.db_digest()
        artifact = run_boundary.run(
            preparation_receipt=(
                prepared.preparation.receipt
            )
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
                    "provider_location": getattr(
                        item,
                        "provider_location",
                        "input",
                    ),
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
        evidence["model_output"] = (
            first_wake_lab._artifact_evidence(artifact)
        )
        evidence["db_digest_before_model_run"] = (
            db_before
        )

        if (
            artifact.run_receipt.provider_request_digest
            != mapped.request_digest
        ):
            message = (
                "run receipt provider-request digest differs "
                "from pre-run mapping"
            )
            evidence["post_run_db_audit"] = {
                "status": "not_attempted",
            }
            evidence["db_digest_after_model_run"] = None
            evidence["db_unchanged_during_model_run"] = None
            evidence["no_home_state_write_observed"] = None
            evidence["lab_failure"] = {
                "reason": message,
            }
            raise RecentLifeWakeLabError(
                message,
                evidence=evidence,
            )

        try:
            db_after = fixture.db_digest()
        except OSError as exc:
            message = (
                "post-run HOME database audit unavailable"
            )
            evidence["post_run_db_audit"] = {
                "status": "unavailable",
                "error_type": type(exc).__name__,
            }
            evidence["db_digest_after_model_run"] = None
            evidence["db_unchanged_during_model_run"] = None
            evidence["no_home_state_write_observed"] = None
            evidence["lab_failure"] = {
                "reason": message,
            }
            raise RecentLifeWakeLabError(
                message,
                evidence=evidence,
            ) from exc

        unchanged = db_before == db_after
        evidence["post_run_db_audit"] = {
            "status": "completed",
        }
        evidence["db_digest_after_model_run"] = (
            db_after
        )
        evidence["db_unchanged_during_model_run"] = (
            unchanged
        )
        evidence["no_home_state_write_observed"] = (
            unchanged
        )
        if not unchanged:
            message = (
                "HOME database changed during model run"
            )
            evidence["lab_failure"] = {
                "reason": message,
            }
            raise RecentLifeWakeLabError(
                message,
                evidence=evidence,
            )
        return evidence


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare or execute Synthetic Recent Life Wake Lab v0.1."
        ),
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Perform the one provider call. Without this flag "
            "the harness stops before model/network execution."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=(
            first_wake_lab.OPENAI_RESPONSES_PROVIDER,
            first_wake_lab.DEEPSEEK_RESPONSES_PROVIDER,
            first_wake_lab.OPENAI_CHATGPT_PLAN_PROVIDER,
        ),
        default=os.environ.get(
            "HOME_RECENT_LIFE_WAKE_PROVIDER",
            first_wake_lab.OPENAI_RESPONSES_PROVIDER,
        ),
    )
    parser.add_argument(
        "--model-id",
        default=os.environ.get(
            "HOME_RECENT_LIFE_WAKE_MODEL_ID"
        ),
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENAI_API_KEY",
    )
    parser.add_argument(
        "--chatgpt-plan-profile",
        type=Path,
        default=first_wake_lab.DEFAULT_PROFILE_PATH,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "recent_life_wake_lab_evidence.json"
        ),
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    api_key = None
    access_token = None
    if args.execute:
        if (
            args.provider
            == first_wake_lab.OPENAI_CHATGPT_PLAN_PROVIDER
        ):
            access_token = first_wake_lab.load_profile(
                path=args.chatgpt_plan_profile
            ).access_token
        else:
            api_key = os.environ.get(
                args.api_key_env
            )
            if not api_key:
                raise SystemExit(
                    f"{args.api_key_env} is required "
                    "with --execute"
                )

    try:
        evidence = run_recent_life_wake_lab(
            execute=args.execute,
            model_id=args.model_id,
            api_key=api_key,
            access_token=access_token,
            provider=args.provider,
        )
    except RecentLifeWakeLabError as exc:
        if exc.evidence is None:
            raise
        first_wake_lab.write_evidence(
            output_path=args.output,
            evidence=exc.evidence,
        )
        print(
            json.dumps(
                {
                    "lab_version": (
                        RECENT_LIFE_WAKE_LAB_VERSION
                    ),
                    "execution_performed": (
                        exc.evidence[
                            "execution_performed"
                        ]
                    ),
                    "status": "lab_failure",
                    "error": str(exc),
                    "evidence_path": str(
                        args.output
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    first_wake_lab.write_evidence(
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
                    RECENT_LIFE_WAKE_LAB_VERSION
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
