"""Focus restoration through the real GUI/controller, with a fake XA device.

Run with PySide6 installed. No vendor SDK, hardware, or user settings are used.
"""

import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Mission_Control_Center"))

from PySide6 import QtCore, QtWidgets
from filter_integration import FilterController, FilterPane, FilterRegisterDialog
from stage_integration import StageBridge, StagePanel, StageSettingsDialog
from stage_backends.stage_backend_base import IStageBackend
from stage_backends.Thorlabs_KDC101 import ThorlabsKDC101Backend
from stage_backends.internal import xa_shared

# MainWindow's filter orchestration does not use these hardware-facing panes.
# Stub only their imports; the stage, filter, and orchestration code is real.
with patch.dict(sys.modules, {
    "camera_integration": SimpleNamespace(CameraPane=object),
    "laser_integration": SimpleNamespace(LaserPane=object),
    "galvo_integration": SimpleNamespace(GalvoPane=object),
}):
    from main import MainWindow


class FakeCameraStage:
    def __init__(self, events):
        self.events = events
        self.fail_fast = False
        self.fail_move = False
        self.fail_restore = False
        self.on_move = lambda: None

    def get_position_counter(self, wait):
        self.events.append(("position", wait))
        return 1000

    def get_velocity_params(self, *args):
        raise AssertionError("Restoration must not read motion settings from hardware")

    def convert_from_physical_to_device(self, scale, unit, value):
        self.events.append(("convert", scale, unit, value))
        return value * 1000

    def convert_from_device_units_to_physical(self, scale, value):
        self.events.append(("display_position", scale, value))
        return SimpleNamespace(converted_value=value / 1000)

    def set_velocity_params(self, minimum, acceleration, velocity):
        self.events.append(("set", minimum, acceleration, velocity))
        fast = (acceleration, velocity) == (500, 1500)
        if (fast and self.fail_fast) or (not fast and self.fail_restore):
            raise RuntimeError("simulated setting failure")

    def move_relative(self, *args):
        self.events.append(("move", *args))
        self.on_move()
        if self.fail_move:
            raise RuntimeError("simulated movement failure")


class FocusMotionRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.settings_dir = tempfile.TemporaryDirectory()
        QtCore.QSettings.setDefaultFormat(QtCore.QSettings.IniFormat)
        for scope in (QtCore.QSettings.UserScope, QtCore.QSettings.SystemScope):
            QtCore.QSettings.setPath(QtCore.QSettings.IniFormat, scope, cls.settings_dir.name)

    @classmethod
    def tearDownClass(cls):
        cls.settings_dir.cleanup()

    def setUp(self):
        settings = QtCore.QSettings("LabSuite", "StageControl")
        settings.clear()
        settings.sync()
        with patch("stage_integration.scan_stage_backends", return_value={}):
            self.stage = StagePanel(StageBridge(), None)
        self.addCleanup(self.stage.deleteLater)
        self.events = []
        self.device = FakeCameraStage(self.events)
        # Use the real backend, without starting its unrelated motion worker.
        # The focus API is synchronous and must not queue work on this thread.
        with patch.object(QtCore.QThread, "start"):
            self.backend = ThorlabsKDC101Backend(None)
        self.addCleanup(self.backend.deleteLater)
        self.addCleanup(self.backend.shutdown)
        self.backend.device = self.device
        self.backend._connected = True
        # Deliberately different last manual settings: they must be ignored.
        self.backend._v_mm_s, self.backend._a_mm_s2 = 7.0, 9.0
        self.stage.backend_camera = self.backend
        self.stage._connected_camera = True
        self.focus = FilterController(self.backend)
        self.focus._positions_counts = {"A": 200, "B": 275}
        self.errors, self.statuses = [], []
        self.focus.sig_error.connect(self.errors.append)
        self.focus.sig_status.connect(self.statuses.append)

        # Only the backend's already-loaded SDK enums are substituted. No XA
        # SDK modules are installed, so integration cannot import them.
        self.sdk_patch = patch.multiple(
            xa_shared,
            TLMC_Wait=SimpleNamespace(TLMC_InfiniteWait=-1),
            TLMC_ScaleType=SimpleNamespace(
                TLMC_ScaleType_Velocity="velocity",
                TLMC_ScaleType_Acceleration="acceleration",
                TLMC_ScaleType_Distance="distance",
            ),
            TLMC_Unit=SimpleNamespace(TLMC_Unit_Millimetres="mm"),
            TLMC_MoveModes=SimpleNamespace(
                MoveMode_RelativeByProgrammed="programmed", MoveMode_Relative="relative"
            ),
        )
        self.sdk_patch.start()
        self.addCleanup(self.sdk_patch.stop)
        self.set_gui_profile("Move")

    def set_gui_profile(self, mode):
        dialog = StageSettingsDialog(self.stage.sample_state, self.stage.camera_state)
        acquisition = dialog._editors[("Camera", "Acq")]
        acquisition["mode"].setCurrentIndex(1 if mode == "Step" else 0)
        for key, value in {"v_move": 0.02, "acc_move": 0.8,
                           "v_step": 0.15, "acc_step": 0.6}.items():
            acquisition[key].setValue(value)
        control = dialog._editors[("Camera", "Ctl")]
        control["v_move"].setValue(0.7)
        control["acc_move"].setValue(4.0)
        dialog._on_accept()
        self.stage.sample_state, self.stage.camera_state = dialog.get_states()
        self.stage._save_prefs()
        dialog.deleteLater()

    def orchestrate(self, busy=False):
        def query_status():
            self.events.append(("filter_status",))
            return {"busy": busy}

        window = SimpleNamespace(
            stage_pane=self.stage,
            filter_pane=SimpleNamespace(
                backend=SimpleNamespace(query_status=query_status),
                _focus_controller=self.focus,
            ),
            _pending_filter_label="B", _last_filter_label="A",
            _filter_move_timer=Mock(),
        )
        MainWindow._check_filter_move_done(window)
        return window

    def test_move_gui_values_restore_with_original_device_order(self):
        window = self.orchestrate()
        self.assertEqual(self.events, [
            ("filter_status",), ("position", -1),
            ("convert", "velocity", "mm", 1.5),
            ("convert", "acceleration", "mm", 0.5),
            ("set", 0, 500, 1500), ("move", "programmed", 75, -1),
            ("display_position", "distance", 1075),
            ("display_position", "distance", 1000),
            ("convert", "velocity", "mm", 0.02),
            ("convert", "acceleration", "mm", 0.8),
            ("set", 0, 800, 20),
        ])
        self.assertEqual(self.errors, [])
        self.assertEqual(window._last_filter_label, "B")
        self.assertIsNone(window._pending_filter_label)
        window._filter_move_timer.stop.assert_called_once()

    def test_step_uses_recording_step_values(self):
        self.set_gui_profile("Step")
        self.orchestrate()
        self.assertEqual(self.events[-1], ("set", 0, 600, 150))

    def test_old_saved_values_do_not_override_gui(self):
        self.focus.settings.setValue("stage_v2_mm_s", 8.0)
        self.focus.settings.setValue("stage_a2_mm_s2", 10.0)
        self.orchestrate()
        self.assertEqual(self.events[-1], ("set", 0, 800, 20))

    def test_current_profile_wins_over_stale_saved_profile(self):
        self.stage.camera_state.acq_profile.v_move = 0.03
        self.stage.camera_state.acq_profile.acc_move = 0.9
        self.orchestrate()
        self.assertEqual(self.events[-1], ("set", 0, 900, 30))

    def test_profile_is_snapshotted_before_correction(self):
        def change_profile():
            self.stage.camera_state.acq_profile.v_move = 0.04
            self.stage.camera_state.acq_profile.acc_move = 1.2
        self.device.on_move = change_profile
        self.orchestrate()
        self.assertEqual(self.events[-1], ("set", 0, 800, 20))

    def test_busy_filter_waits_before_any_stage_operation(self):
        window = self.orchestrate(busy=True)
        self.assertEqual(self.events, [("filter_status",)])
        self.assertEqual(window._pending_filter_label, "B")
        window._filter_move_timer.stop.assert_not_called()

    def test_movement_failure_still_restores_recording_values(self):
        self.device.fail_move = True
        self.orchestrate()
        self.assertEqual(self.events[-1], ("set", 0, 800, 20))
        self.assertTrue(any("move_relative failed" in error for error in self.errors))

    def test_fast_setting_failure_preserves_existing_move_then_no_restore(self):
        self.device.fail_fast = True
        self.orchestrate()
        self.assertEqual([event for event in self.events if event[0] == "set"],
                         [("set", 0, 500, 1500)])
        self.assertTrue(any(event[0] == "move" for event in self.events))
        self.assertTrue(any("failed to set fast" in status for status in self.statuses))

    def test_restore_failure_keeps_existing_warning(self):
        self.device.fail_restore = True
        self.orchestrate()
        self.assertEqual(self.events[-1], ("set", 0, 800, 20))
        self.assertTrue(any("failed to restore filter speed" in status for status in self.statuses))

    def test_zero_delta_does_not_touch_stage(self):
        self.focus._positions_counts["B"] = 200
        self.orchestrate()
        self.assertEqual(self.events, [("filter_status",)])
        self.assertEqual(self.errors, [])

    def test_unregistered_filter_does_not_touch_stage(self):
        del self.focus._positions_counts["B"]
        self.orchestrate()
        self.assertEqual(self.events, [("filter_status",)])
        self.assertTrue(self.errors)

    def test_missing_restore_target_does_not_change_stage(self):
        self.focus.apply_delta_mm("A", "B")
        self.assertEqual(self.events, [])
        self.assertTrue(any("Acquisition settings unavailable" in error for error in self.errors))

    def test_focus_profile_and_gui_settings_remain_unchanged(self):
        self.focus._save_to_settings()
        before = {key: self.focus.settings.value(key) for key in self.focus.settings.allKeys()}
        self.orchestrate()
        after = {key: self.focus.settings.value(key) for key in self.focus.settings.allKeys()}
        self.assertEqual(after, before)
        self.assertEqual(self.focus.profile, "default")
        self.assertEqual(self.focus._settings_key("positions_json"), "Filters/default/positions_json")
        self.assertEqual(self.focus._positions_counts, {"A": 200, "B": 275})

    def test_backend_profiles_direction_and_settings_are_not_modified(self):
        config = copy.deepcopy(self.backend._config)
        cached = (self.backend._v_mm_s, self.backend._a_mm_s2,
                  self.backend._step_mm, self.backend._step_v_mm_s,
                  self.backend._step_a_mm_s2, self.backend._move_direction)
        with patch.object(self.backend, "_save_settings") as save:
            self.orchestrate()
        save.assert_not_called()
        self.assertEqual(self.backend._config, config)
        self.assertEqual(cached, (self.backend._v_mm_s, self.backend._a_mm_s2,
                                 self.backend._step_mm, self.backend._step_v_mm_s,
                                 self.backend._step_a_mm_s2, self.backend._move_direction))

    def test_relative_move_fallbacks_keep_order_and_restore_after_completion(self):
        attempts = [("programmed", 75, -1), ("relative", 75, -1),
                    (75,), (75, 0xFFFFFFFF)]
        for success_index in range(len(attempts)):
            with self.subTest(success_index=success_index):
                self.events.clear()
                self.errors.clear()
                calls = []
                def move(*args):
                    calls.append(args)
                    self.events.append(("move", *args))
                    if len(calls) <= success_index:
                        raise RuntimeError("try next signature")
                    self.events.append(("move_complete",))
                with patch.object(self.device, "move_relative", side_effect=move):
                    self.orchestrate()
                self.assertEqual(calls, attempts[:success_index + 1])
                self.assertEqual(self.errors, [])
                self.assertEqual(self.events[-1], ("set", 0, 800, 20))
                self.assertLess(self.events.index(("move_complete",)),
                                self.events.index(("convert", "velocity", "mm", 0.02)))

    def test_all_move_fallbacks_fail_then_restore(self):
        self.device.fail_move = True
        self.orchestrate()
        self.assertEqual([e for e in self.events if e[0] == "move"], [
            ("move", "programmed", 75, -1), ("move", "relative", 75, -1),
            ("move", 75), ("move", 75, 0xFFFFFFFF),
        ])
        self.assertEqual(self.events[-1], ("set", 0, 800, 20))
        self.assertEqual(len(self.errors), 1)

    def test_current_position_registration_and_integer_json_round_trip(self):
        self.focus.register_position_mm("C")
        self.assertEqual(self.focus._positions_counts["C"], 1000)
        raw = self.focus.settings.value("Filters/default/positions_json")
        self.assertEqual(json.loads(raw), {"A": 200, "B": 275, "C": 1000})
        reloaded = FilterController(self.backend)
        self.addCleanup(reloaded.deleteLater)
        self.assertEqual(reloaded._positions_counts, self.focus._positions_counts)
        self.assertEqual(reloaded.get_positions_mm(), {"A": 0.2, "B": 0.275, "C": 1.0})
        self.assertFalse(any(e[0] in ("set", "move") for e in self.events))

    def test_manual_mm_and_count_override_preserve_rounding(self):
        for label, mm, expected in [("C", 0.0125, 12), ("D", 0.0135, 14),
                                    ("E", -0.0125, -12)]:
            self.focus.register_position_mm(label, mm_override=mm)
            self.assertEqual(self.focus._positions_counts[label], expected)
        self.focus.register_position_mm("F", mm_override=999, count_override=-37)
        self.assertEqual(self.focus._positions_counts["F"], -37)
        self.assertFalse(any(e[0] in ("set", "move") for e in self.events))

    def test_registration_dialog_reads_counts_and_converts_manual_mm(self):
        dialog = FilterRegisterDialog(self.focus, "A")
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.lbl_current.text(), "Current counter: 1000")
        self.assertEqual(dialog.lbl_mm.text(), "Current (mm): 1.000000 mm")
        dialog.accept()
        self.assertEqual(dialog.get_result(), ("use_current", 1000))
        dialog.rb_manual_mm.setChecked(True)
        dialog.le_mm.setText("0.0135")
        self.assertEqual(dialog.get_result(), ("manual_mm", 14))

    def test_position_read_fallback_and_failure(self):
        with patch.object(self.device, "get_position_counter",
                          side_effect=[TypeError("signature"), 321]) as get:
            self.assertEqual(self.focus._get_current_count(), 321)
            self.assertEqual([c.args for c in get.call_args_list], [(-1,), ()])
        with patch.object(self.device, "get_position_counter",
                          side_effect=RuntimeError("read failed")):
            self.orchestrate()
        self.assertFalse(any(e[0] in ("set", "move") for e in self.events))
        self.assertTrue(any("unable to read counter" in e for e in self.errors))

    def test_count_to_mm_fallback_and_unavailable(self):
        with patch.object(self.device, "convert_from_device_units_to_physical",
                          side_effect=[TypeError("signature"), 0.275]) as convert:
            self.assertEqual(self.focus._count_to_mm(275), 0.275)
            self.assertEqual([c.args for c in convert.call_args_list],
                             [("distance", 275), (275,)])
        with patch.object(self.device, "convert_from_device_units_to_physical",
                          side_effect=RuntimeError("conversion failed")):
            self.assertIsNone(self.focus._count_to_mm(275))
            self.orchestrate()
        self.assertEqual(self.events[-1], ("set", 0, 800, 20))
        self.assertTrue(any("Moved camera by 75 counts [A→B]" == s for s in self.statuses))

    def test_mm_to_counts_fallback_and_failure_leave_registration_intact(self):
        with patch.object(self.device, "convert_from_physical_to_device",
                          side_effect=[TypeError("signature"), 13.5]) as convert:
            self.assertEqual(self.focus._mm_to_count(0.0135), 14)
            self.assertEqual([c.args for c in convert.call_args_list],
                             [("distance", "mm", 0.0135), (0.0135,)])
        with patch.object(self.device, "convert_from_physical_to_device",
                          side_effect=RuntimeError("conversion failed")):
            self.focus.register_position_mm("A", mm_override=123)
        self.assertEqual(self.focus._positions_counts["A"], 200)
        self.assertTrue(self.errors)

    def test_apply_registered_position_keeps_move_only_behavior(self):
        self.focus.apply_position_mm("B")
        self.assertEqual(self.events, [
            ("position", -1), ("move", "programmed", -725, -1),
            ("display_position", "distance", 275),
            ("display_position", "distance", 1000),
        ])
        self.assertEqual(self.errors, [])

    def test_backend_handoff_uses_camera_connection_and_clears_on_disconnect(self):
        with patch("filter_integration.scan_filter_backends", return_value={}):
            pane = FilterPane()
        self.addCleanup(pane.deleteLater)
        window = SimpleNamespace(stage_pane=self.stage, filter_pane=pane)
        MainWindow._on_stage_connected(window, True)
        self.assertIs(pane._focus_controller.camera_backend, self.backend)
        # Sample remains connected: its signal must not retain a stale Camera.
        self.stage._connected_sample = True
        self.stage._connected_camera = False
        MainWindow._on_stage_connected(window, True)
        self.assertIsNone(pane._focus_controller.camera_backend)
        pane._focus_controller.sig_error.connect(self.errors.append)
        pane._focus_controller.apply_delta_mm("A", "B", (0.02, 0.8))
        self.assertEqual(self.events, [])
        self.assertTrue(any("camera stage not set" in e for e in self.errors))

    def test_disconnected_backend_rejects_motion_before_any_sdk_call(self):
        self.backend._connected = False
        self.orchestrate()
        self.assertEqual(self.events, [("filter_status",)])
        self.assertTrue(any("not connected" in e for e in self.errors))

    def test_unsupported_backend_rejects_registration_and_correction(self):
        unsupported = IStageBackend()
        self.addCleanup(unsupported.deleteLater)
        self.focus.set_camera_backend(unsupported)
        self.focus.register_position_mm("A", count_override=123)
        self.focus.apply_position_mm("A")
        self.focus.apply_delta_mm("A", "B", (0.02, 0.8))
        self.assertEqual(self.focus._positions_counts["A"], 200)
        self.assertEqual(self.events, [])
        self.assertEqual(len(self.errors), 3)
        self.assertTrue(all("does not support focus correction" in e for e in self.errors))

    def test_generic_backend_needs_no_sdk_device_or_vendor_enums(self):
        class OtherStage(IStageBackend):
            def supports_focus_correction(self):
                return True
            def get_focus_position_counts(self):
                return 1000
            def focus_counts_to_mm(self, counts):
                return counts / 1000
            def focus_mm_to_counts(self, mm):
                return int(round(mm * 1000))
            def set_focus_motion_params(inner, v_mm_s, a_mm_s2):
                self.events.append(("motion", v_mm_s, a_mm_s2))
            def move_focus_relative_counts(inner, counts):
                self.events.append(("relative", counts))
        generic = OtherStage()
        self.addCleanup(generic.deleteLater)
        self.focus.set_camera_backend(generic)
        # Deliberately unavailable vendor modules: the common layer needs none.
        with patch.dict(sys.modules, {"xa_sdk": None,
                                     "xa_sdk.shared.tlmc_type_structures": None}):
            self.focus.apply_delta_mm("A", "B", (0.02, 0.8))
        self.assertEqual(self.events, [("motion", 1.5, 0.5), ("relative", 75),
                                       ("motion", 0.02, 0.8)])
        self.assertEqual(self.errors, [])


if __name__ == "__main__":
    unittest.main()
