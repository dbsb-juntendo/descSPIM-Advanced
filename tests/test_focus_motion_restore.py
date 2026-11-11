"""Focus restoration through the real GUI/controller, with a fake XA device.

Run with PySide6 installed. No vendor SDK, hardware, or user settings are used.
"""

import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Mission_Control_Center"))

from PySide6 import QtCore, QtWidgets
from filter_integration import FilterController
from stage_integration import StageBridge, StagePanel, StageSettingsDialog

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
        # Deliberately different last manual settings: they must be ignored.
        self.stage.backend_camera = SimpleNamespace(_v_mm_s=7.0, _a_mm_s2=9.0)
        self.focus = FilterController(self.device)
        self.focus._positions_counts = {"A": 200, "B": 275}
        self.errors, self.statuses = [], []
        self.focus.sig_error.connect(self.errors.append)
        self.focus.sig_status.connect(self.statuses.append)

        sdk = ModuleType("xa_sdk.shared.tlmc_type_structures")
        sdk.TLMC_Wait = SimpleNamespace(TLMC_InfiniteWait=-1)
        sdk.TLMC_ScaleType = SimpleNamespace(
            TLMC_ScaleType_Velocity="velocity",
            TLMC_ScaleType_Acceleration="acceleration",
            TLMC_ScaleType_Distance="distance",
        )
        sdk.TLMC_Unit = SimpleNamespace(TLMC_Unit_Millimetres="mm")
        sdk.TLMC_MoveModes = SimpleNamespace(
            MoveMode_RelativeByProgrammed="programmed", MoveMode_Relative="relative"
        )
        self.sdk_patch = patch.dict(sys.modules, {
            "xa_sdk": ModuleType("xa_sdk"),
            "xa_sdk.shared": ModuleType("xa_sdk.shared"),
            "xa_sdk.shared.tlmc_type_structures": sdk,
        })
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


if __name__ == "__main__":
    unittest.main()
