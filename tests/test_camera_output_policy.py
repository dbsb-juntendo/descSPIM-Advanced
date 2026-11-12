"""Camera output policy through real Qt and application code, without hardware.

Run with PySide6, NumPy and tifffile installed. Settings and saved images are
isolated in temporary directories. Camera SDKs, stage and laser I/O are mocked.
"""

from collections import deque
import contextlib
import csv
import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Mission_Control_Center"))

import numpy as np
import tifffile
from PySide6 import QtCore, QtGui, QtWidgets

with patch.dict(sys.modules, {"win32con": SimpleNamespace(WM_APP=0x8000)}):
    import camera_integration as ci
    from camera_backends.camera_backend_base import ICameraBackend
    import camera_backends.Nikon_DS50M as nikon
    from camera_backends.Thorlabs_TLCamera import ThorlabsTLCameraBackend


class FakeSensor:
    def __init__(self, depth=12, shape=(7, 13)):
        self.depth = depth
        self.image_height_pixels, self.image_width_pixels = shape
        self.raw = np.linspace(0, (1 << depth) - 1, np.prod(shape), dtype=np.uint16).reshape(shape)
        self.binx_range = self.biny_range = SimpleNamespace(min=1, max=4)
        self.is_armed = True
        self.exposure_time_us = 1000
        self.pending = deque()
        self.events = []
        self.sequence = 0
        self.fail_depth = False

    @property
    def bit_depth(self):
        if self.fail_depth:
            raise RuntimeError("simulated SDK depth failure")
        return self.depth

    def queue_frame(self):
        self.sequence += 1
        self.pending.append(SimpleNamespace(image_buffer=self.raw, frame_count=self.sequence))

    def get_pending_frame_or_null(self):
        self.events.append("poll")
        return self.pending.popleft() if self.pending else None

    def arm(self, count):
        self.events.append(("arm", count))
        self.is_armed = True

    def disarm(self):
        self.events.append("disarm")
        self.is_armed = False

    def issue_software_trigger(self):
        self.events.append("trigger")
        self.queue_frame()


class Fixed16Backend(ICameraBackend):
    """An unrelated fixed-output backend must not be forced to 8-bit by the GUI."""

    def can_select_bit_depth(self):
        return False

    def populate_controls(self, pane):
        pane.ctrl_bit.setCurrentIndex(1)


class SelectableBackend(ICameraBackend):
    def __init__(self, bits):
        super().__init__()
        self.bits = bits
        self.requests = []
        self.queries = 0

    def query_params(self, requested_bits):
        self.queries += 1
        return (4, 3, self.bits, 4 * (self.bits // 8), 12 * (self.bits // 8))

    def capture_snapshot(self, bits):
        self.requests.append(bits)
        return {"bits": bits}


class FakeNikonSDK:
    NKCAM_OPTION_BITDEPTH = 1

    def __init__(self, bit_index):
        self.bit_index = bit_index

    def Nkcam_get_Option(self, handle, option, output):
        output._obj.value = self.bit_index
        return 0

    def Nkcam_get_ResolutionNumber(self, handle):
        return 0

    def __getattr__(self, name):
        if name.startswith("Nkcam_get_"):
            # Skip unrelated gain/exposure/resolution initialization.
            return lambda *args: -1
        raise AttributeError(name)


def qimage_pixels(image):
    dtype = np.uint8 if image.format() == QtGui.QImage.Format_Grayscale8 else np.uint16
    stride = image.bytesPerLine() // np.dtype(dtype).itemsize
    return np.frombuffer(image.constBits(), dtype).reshape(image.height(), stride)[:, :image.width()].copy()


class CameraOutputPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.settings = QtCore.QSettings(str(Path(self.folder.name) / "settings.ini"), QtCore.QSettings.IniFormat)
        for p in (
            patch.object(ci, "QSettings", return_value=self.settings),
            patch.object(ci, "scan_camera_backends", return_value={}),
        ):
            p.start()
            self.addCleanup(p.stop)
        self.log = io.StringIO()
        capture = contextlib.redirect_stdout(self.log)
        capture.__enter__()
        self.addCleanup(capture.__exit__, None, None, None)

    def pane(self):
        pane = ci.CameraPane(None)
        self.addCleanup(pane.deleteLater)
        self.addCleanup(pane.play_timer.stop)
        return pane

    def backend(self, pane=None, depth=12, shape=(7, 13)):
        backend = ThorlabsTLCameraBackend(pane)
        backend._cam = FakeSensor(depth, shape)
        backend._paused = False
        self.addCleanup(backend._timer.stop)
        if pane is not None:
            pane.backend = backend
            pane.hcam = 1
        return backend

    def pipeline(self, shape=(7, 13)):
        pane = self.pane()
        backend = self.backend(pane, shape=shape)
        worker = ci.CaptureWorker(1, bits=16, backend=backend)
        pane.worker = worker
        worker.main = SimpleNamespace(
            stage_bridge=SimpleNamespace(sig_stage_start=Mock(), sig_reset_dda=Mock()),
            window=lambda: SimpleNamespace(laser_pane=Mock()),
        )
        worker.sig_frame_ready.connect(pane.on_frame_ready)
        worker.sig_snapshot_ready.connect(pane.on_snapshot_ready)
        return pane, backend, worker

    def test_fixed_output_survives_bulk_enable_and_save_ui_disable(self):
        pane = self.pane()
        self.assertFalse(pane.ctrl_bit.isEnabled())
        backend = self.backend(pane)
        backend.populate_controls(pane)
        pane._set_cam_controls_visible_enabled(True, True)
        self.assertEqual(pane.ctrl_bit.currentText(), "8-bit")
        self.assertFalse(pane.ctrl_bit.isEnabled())
        self.assertIn("saved images", pane.ctrl_bit.toolTip())
        self.assertIn("8-bit", pane.ctrl_bit.toolTip())
        self.assertTrue(pane.ctrl_res.isEnabled())
        self.assertTrue(pane.btn_apply_rb.isEnabled())
        pane.setEnabled(False)
        pane.setEnabled(True)
        self.assertFalse(pane.ctrl_bit.isEnabled())
        pane.backend = None
        pane._set_cam_controls_visible_enabled(False, False)
        self.assertFalse(pane.ctrl_bit.isEnabled())

    def test_unknown_fixed_backend_keeps_its_own_depth(self):
        pane = self.pane()
        pane.backend = Fixed16Backend(pane)
        pane.backend.populate_controls(pane)
        pane._set_cam_controls_visible_enabled(True, True)
        self.assertEqual(pane.ctrl_bit.currentText(), "16-bit")
        self.assertFalse(pane.ctrl_bit.isEnabled())

    def test_nikon_inherits_selection_and_keeps_sdk_value(self):
        for index in (0, 1):
            with self.subTest(index=index):
                pane = self.pane()
                pane.hcam = 1
                with patch.object(nikon.NikonDS50MBackend, "ensure_filter_installed"), patch.object(nikon, "_ci", return_value=FakeNikonSDK(index)):
                    pane.backend = nikon.NikonDS50MBackend(pane)
                    pane.backend.populate_controls(pane)
                pane._set_cam_controls_visible_enabled(True, True)
                self.assertTrue(pane.ctrl_bit.isEnabled())
                self.assertEqual(pane.ctrl_bit.currentIndex(), index)
                self.assertEqual(pane.ctrl_bit.count(), 2)

    def test_live_and_snapshot_pixels_use_sdk_depth_and_owned_bytes(self):
        for depth in (8, 10, 12, 16):
            for requested in (8, 16):
                with self.subTest(depth=depth, requested=requested):
                    backend = self.backend(depth=depth)
                    sensor = backend._cam
                    expected = (sensor.raw >> max(0, depth - 8)).astype(np.uint8)
                    self.assertEqual(backend.get_current_bit_depth(), 8)
                    self.assertEqual(backend.query_params(requested), (13, 7, 8, 13, 91))
                    sensor.queue_frame()
                    buffer = bytearray(91)
                    live = backend.pull_frame_into_buffer(buffer, 91, requested)
                    snapshot = backend.capture_snapshot(requested)
                    sensor.raw[:] = 0
                    for frame in (live, snapshot):
                        self.assertEqual((frame["bits"], frame["bpl"], len(frame["data"])), (8, 13, 91))
                        np.testing.assert_array_equal(np.frombuffer(frame["data"], np.uint8).reshape(7, 13), expected)
                    self.assertEqual(bytes(buffer), live["data"])

    def test_snapshot_drain_arm_trigger_order_is_unchanged(self):
        backend = self.backend()
        sensor = backend._cam
        sensor.queue_frame()
        sensor.is_armed = False
        frame = backend.capture_snapshot(8)
        self.assertIsNotNone(frame)
        self.assertEqual(sensor.events, ["poll", "poll", ("arm", 2), "trigger", "poll"])

    def test_snapshot_depth_read_failure_keeps_existing_12_bit_fallback(self):
        backend = self.backend()
        expected = (backend._cam.raw >> 4).astype(np.uint8)
        backend._cam.fail_depth = True
        frame = backend.capture_snapshot(8)
        np.testing.assert_array_equal(np.frombuffer(frame["data"], np.uint8).reshape(7, 13), expected)

    def test_snapshot_without_frame_still_returns_none(self):
        backend = self.backend()
        with patch.object(backend._cam, "issue_software_trigger"):
            self.assertIsNone(backend.capture_snapshot(8))

    def test_binning_apply_still_runs_with_fixed_output(self):
        pane = self.pane()
        backend = self.backend(pane)
        pane.worker = Mock()
        backend.apply_res_bit({"binx": 2, "biny": 2}, 1)
        self.assertEqual((backend._cam.binx, backend._cam.biny), (2, 2))
        self.assertEqual(backend._cam.events, ["disarm", ("arm", 2), "trigger"])
        pane.worker.reconfigure.assert_called_once_with()
        self.assertEqual(backend.query_params(16)[2], 8)

    def test_common_snapshot_uses_cached_backend_format_in_both_paths(self):
        for bits in (8, 16):
            with self.subTest(bits=bits):
                backend = SelectableBackend(bits)
                worker = ci.CaptureWorker(1, bits=8, backend=backend)
                received = []
                worker.sig_snapshot_ready.connect(received.append)
                self.assertIsNone(worker.do_capture_snapshot())
                self.assertEqual(received[-1]["bits"], bits)
                worker._recording = True
                result = worker.do_capture_snapshot()
                self.assertEqual(result, received[-1])
                self.assertEqual(backend.requests, [bits, bits])
                self.assertEqual(backend.queries, 1)

    def test_snapshot_uses_reconfigured_output_format(self):
        backend = SelectableBackend(8)
        backend.set_paused = Mock()
        worker = ci.CaptureWorker(1, backend=backend)
        backend.bits = 16
        worker.reconfigure()
        worker.do_capture_snapshot()
        self.assertEqual(backend.requests, [16])

    def test_movie_step_review_and_bigtiff_preserve_pixels_and_metadata(self):
        for shape in ((7, 13), (64, 64)):
            for mode in ("movie", "continuous", "step"):
                with self.subTest(shape=shape, mode=mode):
                    pane, backend, worker = self.pipeline(shape)
                    expected = (backend._cam.raw >> 4).astype(np.uint8)
                    if mode == "step":
                        program = [{"laser": {"backend_name": "test", "connection_key": "test", "line_id": 1}}]
                        with patch.object(ci.QTimer, "singleShot"):
                            worker.start_recording_ram_step(program)
                            for _ in range(2):
                                worker._color_index = 0
                                worker._capture_current_color()
                        worker.main.stage_bridge.sig_reset_dda.emit.assert_called_once_with()
                    else:
                        if mode == "continuous":
                            worker.start_recording_continuous_mode()
                            worker.main.stage_bridge.sig_stage_start.emit.assert_called_once_with()
                        else:
                            worker.start_recording_ram()
                        for _ in range(2):
                            backend._cam.queue_frame()
                            worker.on_image_event(0, 0)
                    self.assertEqual(len(worker._ram_frames), 2)
                    self.assertEqual(worker._ram_bytes, expected.nbytes * 2)
                    worker.stop_recording_ram()
                    backend._cam.raw[:] = 0
                    for frame in worker._ram_frames:
                        np.testing.assert_array_equal(frame, expected)
                    np.testing.assert_array_equal(qimage_pixels(pane._last_img), expected)
                    path = str(Path(self.folder.name) / f"record-{shape[0]}-{mode}.tif")
                    with patch.object(ci.QFileDialog, "getSaveFileName", return_value=(path, "")), patch.object(backend, "set_paused", wraps=backend.set_paused) as pause:
                        pane.blocking_save_to_tiff()
                    self.assertEqual([call.args[0] for call in pause.call_args_list], [True, False])
                    self.assertFalse(backend._paused)
                    with tifffile.TiffFile(path) as saved:
                        self.assertTrue(saved.is_bigtiff)
                        self.assertTrue(all(page.bitspersample == 8 for page in saved.pages))
                        np.testing.assert_array_equal(saved.asarray(), np.stack([expected, expected]))
                    with open(Path(path).with_name(Path(path).stem + "_meta.csv"), newline="") as file:
                        rows = list(csv.reader(file))
                    self.assertEqual(rows[0], ["index", "seq", "camera_timestamp_us", "host_monotonic_ns", "host_wall_epoch_ns", "host_wall_iso8601_utc", "exposure_us"])
                    self.assertEqual(len(rows), 3)
                    self.assertEqual([int(row[1]) for row in rows[1:]], [meta[0] for meta in worker._meta])
                    pane.enter_review_mode_ram()
                    self.assertIs(pane._ram_view, worker._ram_frames)
                    pane.backend = None
                    pane._show_frame_index(1)
                    np.testing.assert_array_equal(qimage_pixels(pane._last_img), expected)

    def test_snapshot_and_rotated_review_tiff_png_keep_8_bit_pixels(self):
        pane, backend, worker = self.pipeline()
        expected = (backend._cam.raw >> 4).astype(np.uint8)
        worker.do_capture_snapshot()
        for rotation in (0, 90):
            if rotation:
                worker.start_recording_ram()
                backend._cam.queue_frame()
                worker.on_image_event(0, 0)
                worker.stop_recording_ram()
                pane.enter_review_mode_ram()
                pane._rot_deg = rotation
            expected_saved = expected if not rotation else np.rot90(expected, -1)
            for extension in ("tif", "png"):
                path = str(Path(self.folder.name) / f"snapshot-{rotation}.{extension}")
                with patch.object(ci.QFileDialog, "getSaveFileName", return_value=(path, "")):
                    pane.on_click_save()
                actual = tifffile.imread(path) if extension == "tif" else qimage_pixels(QtGui.QImage(path))
                np.testing.assert_array_equal(actual, expected_saved)

    def test_save_cancel_and_error_preserve_ram_and_pause(self):
        pane, backend, worker = self.pipeline()
        worker.start_recording_ram()
        backend._cam.queue_frame()
        worker.on_image_event(0, 0)
        worker.stop_recording_ram()
        original = worker._ram_frames[0]
        with patch.object(ci.QFileDialog, "getSaveFileName", return_value=("", "")), patch.object(backend, "set_paused") as pause:
            pane.blocking_save_to_tiff()
        pause.assert_not_called()
        for paused in (False, True):
            pane._paused = backend._paused = paused
            with patch.object(ci.QFileDialog, "getSaveFileName", return_value=(str(Path(self.folder.name) / "failed.tif"), "")), patch.object(ci.tifffile, "TiffWriter", side_effect=OSError("simulated write failure")), patch.object(backend, "set_paused", wraps=backend.set_paused) as pause:
                with self.assertRaises(OSError):
                    pane.blocking_save_to_tiff()
            self.assertEqual([call.args[0] for call in pause.call_args_list], [True, paused])
            self.assertEqual(backend._paused, paused)
            self.assertIs(worker._ram_frames[0], original)
            self.assertTrue(pane.isEnabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
