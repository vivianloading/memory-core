from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from home_memory_core.host_migration import (  # noqa: E402
    HostMigrationError,
    create_closed_synthetic_backup,
    restore_closed_synthetic_backup,
    verify_restored_closed_synthetic_store,
)
from home_memory_core.host_verifier import HostVerificationError, verify_closed_mini_host  # noqa: E402
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
from home_memory_core.source import create_source_record  # noqa: E402
from home_memory_core.storage import MemoryStore  # noqa: E402
from home_memory_core.suppression import (  # noqa: E402
    SuppressedMemoryError,
    create_timed_suppression_record,
)


_CONFIG = """\
[home]
schema = "home-mini-host-v0.1"
runtime_root = "."
database = "data/home.db"
real_data_allowed = false

[secrets]
mode = "disabled"
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Closed synthetic-only HOME backup/restore and migration rehearsal."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="create a closed synthetic HOME backup")
    backup.add_argument("--config", required=True)
    backup.add_argument("--bundle", required=True)

    restore = sub.add_parser("restore", help="restore into an empty closed HOME runtime")
    restore.add_argument("--config", required=True)
    restore.add_argument("--bundle", required=True)

    verify = sub.add_parser("verify-restored", help="verify an already restored closed HOME store")
    verify.add_argument("--config", required=True)
    verify.add_argument("--bundle", required=True)

    sub.add_parser(
        "rehearse",
        help="run a disposable two-hop synthetic migration rehearsal on this machine",
    )
    return parser.parse_args()


def _path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _write_config(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "home-mini.toml"
    path.write_text(_CONFIG, encoding="utf-8")
    return path


def _seed_rehearsal_store(config_path: Path) -> tuple[object, object]:
    db_path = config_path.parent / "data" / "home.db"
    store = MemoryStore(db_path)
    store.initialize()
    active = create_source_record(
        source_id="mini-rehearsal-active",
        content="HOME synthetic migration rehearsal: active memory survives the move.",
        authored_by="rehearsal",
        scope="shared",
    )
    suppressed = create_source_record(
        source_id="mini-rehearsal-suppressed",
        content="HOME synthetic migration rehearsal: stop-use survives the move.",
        authored_by="rehearsal",
        scope="shared",
    )
    store.add_source(active)
    store.add_source(suppressed)
    store.suppress_source(
        create_timed_suppression_record(
            suppression_id="mini-rehearsal-stop-use",
            source_id=suppressed.source_id,
            requested_by="rehearsal",
            reason="prove that migration does not resurrect a suppressed source",
            effective_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            recorded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )

    living = LivingStore(db_path)
    living.initialize()
    room = RoomRecord(room_id="mini-rehearsal-room")
    first = EpisodeRecord(
        episode_id="mini-rehearsal-episode-a",
        perspective_instance_id="mini-rehearsal-perspective-a",
        runtime_instance_id="mini-rehearsal-runtime-a",
    )
    second = EpisodeRecord(
        episode_id="mini-rehearsal-episode-b",
        perspective_instance_id="mini-rehearsal-perspective-b",
        runtime_instance_id="mini-rehearsal-runtime-b",
    )
    edge = ContinuityEdge(
        edge_id="mini-rehearsal-edge",
        previous_episode_id=first.episode_id,
        next_episode_id=second.episode_id,
        transfer_mode=TransferMode.TEXT_CONTEXT_HANDOFF,
        continuity_status=ContinuityStatus.UNKNOWN,
        support_refs=("mini-rehearsal-handoff-receipt",),
    )
    route = RoomAttachmentEvent(
        attachment_event_id="mini-rehearsal-route",
        episode_id=second.episode_id,
        route_kind=RoomRouteKind.ATTACHED,
        room_id=room.room_id,
        basis="ordinary_handoff",
        support_refs=(edge.edge_id,),
    )
    living.add_room(room)
    living.add_episode(first)
    living.add_episode(second)
    living.add_continuity_edge(edge)
    living.add_room_attachment(route)

    return active, suppressed


def _assert_rehearsal_state(config_path: Path, active: object, suppressed: object) -> None:
    db_path = config_path.parent / "data" / "home.db"
    store = MemoryStore(db_path)
    if store.get_source(active.source_id) != active:
        raise HostMigrationError("rehearsal active source did not survive migration")
    if store.is_source_usable(suppressed.source_id):
        raise HostMigrationError("rehearsal suppression state was resurrected")
    try:
        store.get_source(suppressed.source_id)
    except SuppressedMemoryError:
        pass
    else:
        raise HostMigrationError("rehearsal suppressed source became normally readable")
    if store.get_source_for_audit(suppressed.source_id) != suppressed:
        raise HostMigrationError("rehearsal suppressed history did not survive migration")

    living = LivingStore(db_path)
    route = living.resolve_room_attachment(
        episode_id="mini-rehearsal-episode-b"
    )
    if route.decision != "attached" or route.room_id != "mini-rehearsal-room":
        raise HostMigrationError(
            "rehearsal Living Layer room route did not survive migration"
        )
    edges = living.list_continuity_edges()
    if len(edges) != 1:
        raise HostMigrationError(
            "rehearsal Living Layer continuity edge did not survive migration"
        )
    if edges[0].continuity_status is not ContinuityStatus.UNKNOWN:
        raise HostMigrationError(
            "rehearsal migration rewrote unknown continuity semantics"
        )


def _run_rehearsal() -> None:
    with tempfile.TemporaryDirectory(prefix="home-mini-migration-rehearsal-") as tmp:
        root = Path(tmp)
        source_config = _write_config(root / "source")
        active, suppressed = _seed_rehearsal_store(source_config)

        first_bundle = root / "first.homebackup.zip"
        create_closed_synthetic_backup(
            config_path=source_config,
            bundle_path=first_bundle,
        )
        first_target_config = _write_config(root / "target-one")
        restore_closed_synthetic_backup(
            bundle_path=first_bundle,
            target_config_path=first_target_config,
        )
        _assert_rehearsal_state(first_target_config, active, suppressed)
        verify_restored_closed_synthetic_store(
            bundle_path=first_bundle,
            target_config_path=first_target_config,
        )

        second_bundle = root / "second.homebackup.zip"
        create_closed_synthetic_backup(
            config_path=first_target_config,
            bundle_path=second_bundle,
        )
        second_target_config = _write_config(root / "target-two")
        restore_closed_synthetic_backup(
            bundle_path=second_bundle,
            target_config_path=second_target_config,
        )
        _assert_rehearsal_state(second_target_config, active, suppressed)
        verify_restored_closed_synthetic_store(
            bundle_path=second_bundle,
            target_config_path=second_target_config,
        )
        verify_closed_mini_host(second_target_config, src_dir=SRC_DIR)

    print("[HOME migrate] two-hop synthetic migration rehearsal: GREEN", flush=True)
    print("[HOME migrate] real personal data remains CLOSED", flush=True)


def main() -> int:
    args = _parse_args()
    try:
        if args.command == "backup":
            result = create_closed_synthetic_backup(
                config_path=_path(args.config),
                bundle_path=_path(args.bundle),
            )
            print(f"[HOME migrate] backup: OK -> {result.bundle_path}", flush=True)
        elif args.command == "restore":
            result = restore_closed_synthetic_backup(
                bundle_path=_path(args.bundle),
                target_config_path=_path(args.config),
            )
            print(f"[HOME migrate] restore: OK -> {result.config.db_path}", flush=True)
        elif args.command == "verify-restored":
            verify_restored_closed_synthetic_store(
                bundle_path=_path(args.bundle),
                target_config_path=_path(args.config),
            )
            print("[HOME migrate] restored store: OK", flush=True)
        elif args.command == "rehearse":
            _run_rehearsal()
        else:
            raise HostMigrationError("unsupported migration command")
    except (HostMigrationError, HostVerificationError, OSError) as exc:
        print(f"[HOME migrate] FAIL: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
