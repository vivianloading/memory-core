import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

import home_memory_core.home_state_ordering as ordering_module

from home_memory_core.home_state_ordering import (
    HomeStateOrderingIntegrityError,
    HomeStateOrderingReentryError,
    home_state_coordinator_for_path,
)


class HomeStateOrderingCoordinatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "home.db"
        self.coordinator = home_state_coordinator_for_path(
            self.db
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_same_resolved_path_returns_same_coordinator(self) -> None:
        again = home_state_coordinator_for_path(
            self.root / "." / "home.db"
        )
        self.assertIs(again, self.coordinator)

    def test_successful_commit_increments_generation_once(self) -> None:
        before = self.coordinator.generation
        permit = self.coordinator.acquire_writer()
        try:
            after = permit.record_successful_commit()
            self.assertEqual(after, before + 1)
            self.assertEqual(
                self.coordinator.generation,
                before + 1,
            )
            with self.assertRaises(
                HomeStateOrderingIntegrityError
            ):
                permit.record_successful_commit()
        finally:
            permit.release()

        self.assertEqual(
            self.coordinator.generation,
            before + 1,
        )

    def test_released_uncommitted_writer_does_not_increment(self) -> None:
        before = self.coordinator.generation
        permit = self.coordinator.acquire_writer()
        permit.release()
        self.assertEqual(self.coordinator.generation, before)

    def test_same_thread_writer_inside_cut_fails_closed(self) -> None:
        cut = self.coordinator.acquire_cut()
        try:
            with self.assertRaises(
                HomeStateOrderingReentryError
            ):
                self.coordinator.acquire_writer()
        finally:
            self.coordinator.release_cut(cut=cut)

    def test_nested_cut_fails_closed(self) -> None:
        cut = self.coordinator.acquire_cut()
        try:
            with self.assertRaises(
                HomeStateOrderingReentryError
            ):
                self.coordinator.acquire_cut()
        finally:
            self.coordinator.release_cut(cut=cut)

    def test_cut_inside_writer_fails_closed(self) -> None:
        permit = self.coordinator.acquire_writer()
        try:
            with self.assertRaises(
                HomeStateOrderingReentryError
            ):
                self.coordinator.acquire_cut()
        finally:
            permit.release()

    def test_nested_writer_fails_closed(self) -> None:
        permit = self.coordinator.acquire_writer()
        try:
            with self.assertRaises(
                HomeStateOrderingReentryError
            ):
                self.coordinator.acquire_writer()
        finally:
            permit.release()

    def test_process_incarnation_change_fails_closed(self) -> None:
        with patch.object(
            ordering_module,
            "current_home_process_instance_id",
            return_value="process-other",
        ):
            with self.assertRaises(Exception):
                _ = self.coordinator.generation
            with self.assertRaises(Exception):
                self.coordinator.acquire_writer()
            with self.assertRaises(Exception):
                self.coordinator.acquire_cut()

        with patch.object(
            ordering_module,
            "current_home_process_instance_id",
            side_effect=RuntimeError("inherited-process-boundary"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "inherited-process-boundary",
            ):
                home_state_coordinator_for_path(self.db)

    def test_other_thread_writer_waits_behind_cut(self) -> None:
        cut = self.coordinator.acquire_cut()
        acquired = threading.Event()
        finished = threading.Event()
        errors = []

        def writer() -> None:
            try:
                permit = self.coordinator.acquire_writer()
                acquired.set()
                permit.record_successful_commit()
                permit.release()
                finished.set()
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=writer)
        thread.start()
        time.sleep(0.05)
        self.assertFalse(acquired.is_set())
        self.assertFalse(finished.is_set())

        self.coordinator.require_active_cut(cut=cut)
        self.coordinator.release_cut(cut=cut)

        thread.join(timeout=2)
        self.assertEqual(errors, [])
        self.assertTrue(acquired.is_set())
        self.assertTrue(finished.is_set())

    def test_other_thread_cut_waits_behind_writer(self) -> None:
        permit = self.coordinator.acquire_writer()
        acquired = threading.Event()
        finished = threading.Event()
        errors = []

        def cutter() -> None:
            try:
                cut = self.coordinator.acquire_cut()
                acquired.set()
                self.coordinator.require_active_cut(
                    cut=cut
                )
                self.coordinator.release_cut(cut=cut)
                finished.set()
            except BaseException as error:
                errors.append(error)

        thread = threading.Thread(target=cutter)
        thread.start()
        time.sleep(0.05)
        self.assertFalse(acquired.is_set())

        permit.record_successful_commit()
        permit.release()

        thread.join(timeout=2)
        self.assertEqual(errors, [])
        self.assertTrue(acquired.is_set())
        self.assertTrue(finished.is_set())


if __name__ == "__main__":
    unittest.main()
