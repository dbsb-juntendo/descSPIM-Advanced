# camera_integration

# TODO: Move_continuou を Movei modeに改名

import ctypes
from ctypes import (
    c_int, c_uint, c_ushort, c_ubyte, c_short, c_uint64, c_float,
    c_char, c_char_p, c_wchar, c_wchar_p, c_void_p,
    Structure, POINTER, byref, cast, wintypes
)
from enum import IntEnum
import time

#from camera_backend_base import ICameraBackend  # ← これを追加
#from .camera_backend_base import ICameraBackend
from camera_backends.camera_backend_base import ICameraBackend

#from nikon_sdk import *
#from nikon_sdk import NkcamEvent
#from camera_backend_nikon import NikonDS50MBackend

# camera_integration.py
from PySide6.QtCore import Qt, QObject, Signal, Slot, QThread, QTimer,  QAbstractNativeEventFilter,QRectF, QPointF, QCoreApplication, QSettings, QEvent
from PySide6.QtGui import QImage, QPixmap, QGuiApplication, QTransform, QPen, QBrush, QColor, QPainter
import ctypes, time, os, csv, win32con
from datetime import datetime, timezone
from collections import deque
import numpy as np
from PySide6.QtWidgets import (
    QWidget, QFormLayout, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSlider, QSizePolicy,
    QSpinBox, QDoubleSpinBox, QComboBox, QCheckBox, QProgressDialog, QFileDialog,
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsPixmapItem, QGridLayout, QApplication, QGroupBox, QDialog, QLineEdit
)
import tifffile
from ctypes import c_int, c_uint, c_ushort, c_void_p, byref, wintypes


import importlib
import pkgutil
import pathlib

import json

BACKEND_MODULE_DIR = pathlib.Path(__file__).parent / "camera_backends"

def scan_camera_backends():
    backends = {}  # key → dict(name, module_name, class)
    pkg_name = "camera_backends"

    for module_info in pkgutil.iter_modules([str(BACKEND_MODULE_DIR)]):
        mod_name = module_info.name                       # 例: Nikon_DS50M
        full_mod = f"{pkg_name}.{mod_name}"               # camera_backends.Nikon_DS50M

        try:
            mod = importlib.import_module(full_mod)
            if hasattr(mod, "get_backend_class"):
                cls = mod.get_backend_class()
                # 表示名（例: Nikon_DS50M）
                backends[mod_name] = {
                    "label": mod_name.replace("_", " "),
                    "module": full_mod,
                    "class": cls
                }
        except Exception as e:
            print(f"[scan] failed importing {full_mod}: {e}")


    return backends


class StageLinkMode(IntEnum):
    STAGE_OFF       = 0
    MOVE_CONTINUOUS = 1
    STEP            = 2
    # 将来: MULTI_POSITION = 2 などを追加していく
    # TODO: OFF のときは Auto-return を強制 OFF + 無効化 にするようにコードを編集すること

class StageStopMode(IntEnum):
    STOP_ONLY = 0         # 止めるだけ
    STOP_AND_RETURN = 1   # Home/Return 付き
    #RETURN_ONLY = 2

# --- ROIビュークラス ---
class RoiView(QGraphicsView):
    sig_roi_changed = Signal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)

        self.roi_item = QGraphicsRectItem()
        self.roi_item.setPen(QPen(QColor(255, 0, 0), 2, Qt.DashLine))
        self.roi_item.setBrush(QBrush(QColor(255, 0, 0, 50)))
        self.roi_item.setVisible(False)
        self.scene.addItem(self.roi_item)

        # ROI 編集関連
        self._dragging = False
        self._resizing = False
        self._roi_start = QPointF()
        self._roi_rect = QRectF()
        self._resize_margin = 6
        self._edit_enabled = False

        # 表示操作（ズーム・パン）関連
        self._panning = False
        self._pan_start = QPointF()
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setMouseTracking(True)

        # 重要: ズームをマウス位置中心で行うため NoAnchor
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)

        # 最小/最大 スケールを任意で制限する（必要なら調整）
        self._min_scale = 0.1
        self._max_scale = 10.0

    def set_image(self, qimg: QImage):
        pix = QPixmap.fromImage(qimg)
        self.pixmap_item.setPixmap(pix)
        self.scene.setSceneRect(pix.rect())
        
        #self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

        # 初回だけ fill で合わせる
        if not hasattr(self, "_fitted_once"):
            self._fit_to_pixmap_fill()
            self._fitted_once = True

        # 初回だけfitInView
        #if not hasattr(self, "_fitted_once"):
        #    self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        #    self._fitted_once = True

    def _fit_to_pixmap_fill(self):
        # 回転後のpixmapがシーン上で占める矩形
        rect = self.pixmap_item.mapRectToScene(self.pixmap_item.boundingRect())
        if rect.isNull():
            return

        vp = self.viewport().rect()
        if vp.isEmpty():
            return

        # 画面を埋める（長軸が画面いっぱいになる）スケール
        scale_x = vp.width() / rect.width()
        scale_y = vp.height() / rect.height()
        scale = max(scale_x, scale_y)

        # Transform をリセットして適用
        t = QTransform()
        t.scale(scale, scale)
        self.setTransform(t)

        # 中心を合わせる
        self.centerOn(rect.center())



    def enable_edit(self, enable: bool):
        self._edit_enabled = enable
        if enable:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def get_roi(self):
        r = self.roi_item.rect()
        return int(r.x()), int(r.y()), int(r.width()), int(r.height())

    def set_roi(self, x, y, w, h):
        self._roi_rect = QRectF(x, y, w, h)
        self.roi_item.setRect(self._roi_rect)
        self.roi_item.setVisible(True)

    # -------------------------
    # パン操作（編集モード外で左ドラッグ）
    # -------------------------
    def mousePressEvent(self, e):
        if self._edit_enabled and e.button() == Qt.LeftButton:
            # 既存の ROI 編集フロー
            pos = self.mapToScene(e.pos())
            if self.roi_item.isVisible() and self._roi_rect.contains(pos):
                self._dragging = True
                self._drag_offset = pos - self._roi_rect.topLeft()
            else:
                self._roi_start = pos
                self._roi_rect = QRectF(pos, pos)
                self.roi_item.setRect(self._roi_rect)
                self.roi_item.setVisible(True)
            return
        # 編集モードでない場合はパン開始（左ボタン）
        if not self._edit_enabled and e.button() == Qt.LeftButton:
            self._panning = True
            self._pan_start = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._edit_enabled:
            # ROI 編集フロー
            pos = self.mapToScene(e.pos())
            if self._dragging:
                new_top_left = pos - self._drag_offset
                self._roi_rect.moveTo(new_top_left)
                self.roi_item.setRect(self._roi_rect)
            elif e.buttons() & Qt.LeftButton:
                self._roi_rect = QRectF(self._roi_start, pos).normalized()
                self.roi_item.setRect(self._roi_rect)
            self._emit_roi_changed()
            return

        # パン中
        if self._panning and (e.buttons() & Qt.LeftButton):
            delta = e.pos() - self._pan_start
            hbar = self.horizontalScrollBar()
            vbar = self.verticalScrollBar()
            # ドラッグの向きとスクロールの関係を調整（直感的に動くように）
            hbar.setValue(hbar.value() - int(delta.x()))
            vbar.setValue(vbar.value() - int(delta.y()))
            self._pan_start = e.pos()
            e.accept()
            return

        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._edit_enabled and e.button() == Qt.LeftButton:
            self._dragging = False
            super().mouseReleaseEvent(e)
            self._emit_roi_changed()
            return
        if self._panning and e.button() == Qt.LeftButton:
            self._panning = False
            self.setCursor(Qt.OpenHandCursor if not self._edit_enabled else Qt.CrossCursor)
            e.accept()
            return
        super().mouseReleaseEvent(e)

    # -------------------------
    # ホイールズーム（マウス位置を中心に拡大縮小）
    # -------------------------
    def wheelEvent(self, event):
        # get wheel delta (support both angleDelta() and pixelDelta() for touchpads)
        angle = event.angleDelta().y()
        if angle == 0:
            # pixelDelta is usually smaller units for smooth touchpad scroll; use a scale factor
            angle = event.pixelDelta().y()

        if angle == 0:
            # 全く変化が無ければ既定処理に任せる（または無視）
            event.ignore()
            return

        steps = angle / 120.0  # 1 step = 120 (typical)
        factor = 1.25 ** steps

        # マウス位置のシーン座標（ズーム前）
        old_pos = self.mapToScene(event.position().toPoint())

        # 現在のスケール取得（x成分で代表）
        current_scale = self.transform().m11()
        requested_new_scale = current_scale * factor

        # clamp to min/max
        if requested_new_scale < self._min_scale:
            factor = self._min_scale / current_scale
            requested_new_scale = self._min_scale
        elif requested_new_scale > self._max_scale:
            factor = self._max_scale / current_scale
            requested_new_scale = self._max_scale

        # もしスケールが変わらない（上限/下限でクランプされ、現在と同じ）なら
        if abs(requested_new_scale - current_scale) < 1e-12:
            # イベントを消化してスクロールバーに渡さない
            event.accept()
            return

        # 実際にズーム
        self.scale(factor, factor)

        # ズーム後にマウス位置が同じシーン座標を指すようにセンタ調整
        new_pos = self.mapToScene(event.position().toPoint())
        delta = new_pos - old_pos
        center = self.mapToScene(self.viewport().rect().center())
        self.centerOn(center - delta)

        event.accept()


    def _emit_roi_changed(self):
        x, y, w, h = self.get_roi()
        self.sig_roi_changed.emit(x, y, w, h)

    def clear_roi(self):
        """ROI矩形を消す"""
        self.roi_item.setVisible(False)
        self._roi_rect = QRectF()
        self.scene.update()


# ===== ワーカー =====
class CaptureWorker(QObject):
    sig_frame_ready = Signal(object)
    sig_record_status = Signal(str)
    sig_autostop = Signal(str)   # ← 自動停止通知
    sig_recording_stopped = Signal()
    #sig_on_snapshot_ready = Signal()
    sig_snapshot_ready = Signal(object)

    def __init__(self, hcam, bits=8, backend: ICameraBackend | None = None):
        super().__init__()
        self._paused = False
        self._hcam = hcam
        self._bits = int(bits)            # 8 or 16
        self.backend = backend
        self._stage_link_enabled = True  # ★ 追加: ステージ連動フラグ
        self._auto_return_enabled = False

        # Step-scan 用
        self._step_scan_enabled = False
        self._step_interval_s = 0.2  # まずはハードコード

        # --- step recording sync ---
        self._step_waiting = False     # stepを出して完了待ち中か
        self._step_inflight = False    # 多重発行防止

        self._w = self._h = self._bpl = self._size = 0
        self._buf = None

        if self._hcam and self.backend is not None:
            try:
                params = self.backend.query_params(self._bits)
            except Exception as e:
                print(f"[CaptureWorker] initial query_params error: {e}")
                params = None

            if params is not None:
                self._w, self._h, self._bits, self._bpl, self._size = params
                self._buf = (ctypes.c_ubyte * self._size)()

        self._record_armed = False
        self._recording = False
        self._ram_frames = deque()
        self._ram_bytes = 0
        self._ram_limit = 70 * (1024**3)
        self._dtype = np.uint8 if self._bits == 8 else np.uint16

        self._auto_stop_enabled = False
        self._auto_stop_frames = 0

        self._meta = deque()     # (seq:int, ts_us:int, host_ns:int, exposure_us:int) を入れる
        self._last_seq = None    # 直前フレームの連番

        self._t0_wall_ns = None   # 録画開始時の壁時計(エポック)ns
        self._t0_mono_ns = None   # 録画開始時の単調時計ns

        # ★ 追加: ステージ連動フラグ（デフォルト ON）
        self._link_stage = True

        # STEP多色用
        self._step_program: list[dict] = []
        self._color_index: int = 0
        self._completed_steps: int = 0

        #self._ram_frames_by_color: dict[str, list[np.ndarray]] = {}
        #self._meta_by_color: dict[str, list[dict]] = {}

    #----------------
    # 1. 前提：状態フラグをセットするメソッド群
    #----------------

    #@Slot(bool)
    #def set_stage_link_enabled(self, enabled: bool):
    #    print("[CaptureWorker] set_stage_link_enabled:", enabled)
    #    """カメラ録画とステージを連動させるかどうかを切り替える"""
    #    self._stage_link_enabled = bool(enabled)
    #    print(f"[CaptureWorker] stage link enabled = {self._stage_link_enabled}")

    # ★ 追加: Auto-return の ON/OFF
    @Slot(bool)
    def set_auto_return_enabled(self, enabled: bool):
        self._auto_return_enabled = bool(enabled)
        print(f"[CaptureWorker] auto-return enabled = {self._auto_return_enabled}")


    @Slot(bool, int)
    def set_auto_stop(self, enabled: bool, nframes: int):
        self._auto_stop_enabled = bool(enabled)
        self._auto_stop_frames = max(0, int(nframes))
        if enabled and self._auto_stop_frames > 0:
            self.sig_record_status.emit(f"Auto-stop at {self._auto_stop_frames} frames")
        else:
            self.sig_record_status.emit("Auto-stop disabled")
    """
    def _io_set_output(self, on: bool):
        try:
            io_set_outputmode(self._hcam, on)
        except Exception as e:
            print(f"[IO] set_output error: {e}")
    """

    @Slot(bool, float)
    def set_step_scan_params(self, enabled: bool, interval_s: float):
        self._step_scan_enabled = bool(enabled)
        self._step_interval_s = max(0.0, float(interval_s))
        print(f"[CaptureWorker] step-scan enabled={self._step_scan_enabled}, "
              f"interval={self._step_interval_s} s")

    @Slot(bool)
    def set_paused(self, v: bool):
        if self._paused == v:
            return
        self._paused = v

        backend = getattr(self, "backend", None)
        if backend is None:
            print("[CaptureWorker] set_paused called but backend is None")
            return

        try:
            backend.set_paused(v)
        except Exception as e:
            print(f"[CaptureWorker] backend.set_paused({v}) error: {e}")

    # -----
    # 2. 録画の開始・停止とステージ連動
    # -----
    @Slot()
    def do_capture_snapshot(self):
        # ここで backend から「生フレーム」を 1 枚もらう
        if not hasattr(self, "backend") or self.backend is None:
            self.sig_record_status.emit("No backend.")
            return
        
        if not self._recording:
            try:    # 保存用ビット深度（8 or 16）は UI のポリシーで決める
                bits = 8  # 例：とりあえず 8bit でスナップ
                snapshot = self.backend.capture_snapshot(bits=bits)
                self.sig_snapshot_ready.emit(snapshot)
                return

            except:
                snapshot = None
                self.sig_snapshot_ready.emit(snapshot)    #いる？ return = None
                print("[CaptureWorker]Capture was failed")
                return

        else:
            bits = 8 #self._bits  # TODOカメラのbitdepthに合わせて変えるようにする
            snapshot = self.backend.capture_snapshot(bits=bits)
            self.sig_snapshot_ready.emit(snapshot)
            return snapshot

    @Slot()
    def start_recording_ram(self):
        print(f"[CaptureWorker] start_recording_ram")   # デバッグ用
        if self._recording:
            return
        self._dtype = np.uint8 if self._bits == 8 else np.uint16
        self._ram_frames.clear()
        self._meta.clear()
        self._ram_bytes = 0
        self._last_seq = None
        self._t0_wall_ns = time.time_ns()
        self._t0_mono_ns = time.perf_counter_ns()
        self._recording = True
        #self.sig_record_status.emit("Recording to RAM...")

    @Slot()
    def start_recording_continuous_mode(self):
        print(f"[CaptureWorker] start_recording_continuous_mode")   # デバッグ用
        # MOVE_CONTINUOUSの時だけここに来るようにする？
        if self._recording:
            return
        self._dtype = np.uint8 if self._bits == 8 else np.uint16
        self._ram_frames.clear()
        self._meta.clear()
        self._ram_bytes = 0
        self._last_seq = None
        self._t0_wall_ns = time.time_ns()
        self._t0_mono_ns = time.perf_counter_ns()
        try:
            self._recording = True
            self.main.stage_bridge.sig_stage_start.emit()   # ステージ開始（同時スタート・ジッタ最小）
            print("[CaptureWorker] emit stage_start") # ★ ステージ連動フラグを見てから start
            self.sig_record_status.emit("Recording to RAM...")
        except Exception:
            print("[CaptureWorker] stage_start SKIPPED (link_enabled=False)")   # デバッグ用
        #try:
        #    self.main._timing_logger.log_event("CAM_IO_ON")
        #except Exception:
        #    pass

    # STEPモードの開始は、ステッププログラムを引数で受け取るようにする
    @Slot()
    def stop_recording_ram(self):
        total_frames = len(self._ram_frames)

        print(
            f"[CaptureWorker] stop_recording_ram: "
            f"recording={self._recording}, n_frames={total_frames}"
        )

        if not self._recording:
            return

        self._recording = False
        self._step_waiting = False
        self._step_inflight = False

        try:
            self._laser_all_off()
        except Exception:
            pass

        gb = self._ram_bytes / (1024**3)
        self.sig_record_status.emit(
            f"Stopped. RAM buffered: {total_frames} frames, {gb:.2f} GB"
        )
        self.sig_recording_stopped.emit()


    """
    @Slot()
    def start_recording_ram_step(self):
        print(f"[CaptureWorker] start_recording_step_mode")   # デバッグ用
        if self._recording:
            return
        self._dtype = np.uint8 if self._bits == 8 else np.uint16
        self._ram_frames.clear()
        self._meta.clear()
        self._ram_bytes = 0
        self._last_seq = None
        self._t0_wall_ns = time.time_ns()
        self._t0_mono_ns = time.perf_counter_ns()
        self._recording = True
        self.main.stage_bridge.sig_reset_dda.emit()

        # step同期フラグ初期化
        self._step_waiting = False
        self._step_inflight = False

        self.sig_record_status.emit("Recording to RAM...")

        # ★最初のstepを出す（以後は step_done → 100ms → capture → next step）
        self._emit_step_once()


    def _do_one_step(self):
        try:
            # ここで do_capture_snapshot() の戻り値を受け取る
            snapshot = self.do_capture_snapshot()
            if snapshot is None:
                print("snapshot was None")
                return

            data  = snapshot["data"]
            seq   = snapshot["seq"]
            ts_us = snapshot["ts_us"]
            exp_us = snapshot["exp_us"]

            # このフレームをホスト側で受け取った時刻（高分解能）
            host_ns = time.perf_counter_ns()

            # ステージを 1 step 動かす

            self.main.stage_bridge.sig_step_once.emit()
            print("[CaptureWorker] emit stage_start")

            arr = np.frombuffer(data, dtype=self._dtype).reshape(self._h, self._w).copy()
            self._ram_frames.append(arr)
            print(f"[CaptureWorker] append frame #{len(self._ram_frames)}")
            self._ram_bytes += arr.nbytes

            if self._t0_wall_ns is not None and self._t0_mono_ns is not None:
                wall_ns = self._t0_wall_ns + (host_ns - self._t0_mono_ns)
            else:
                wall_ns = time.time_ns()

            self._meta.append((seq, ts_us, host_ns, wall_ns, exp_us))

            # ドロップ検出
            if self._last_seq is not None and seq != self._last_seq + 1:
                gap = seq - (self._last_seq + 1)
                self.sig_record_status.emit(
                    f"Frame drop detected: missed {gap} frame(s) (seq {self._last_seq} -> {seq})"
                )
            self._last_seq = seq

            # RAM上限チェック
            if self._ram_bytes > self._ram_limit:
                msg = f"RAM limit reached ({self._ram_bytes/(1024**3):.2f} GB). Auto-stopped."
                self.sig_record_status.emit(msg)
                self.sig_autostop.emit(msg)
                self.stop_recording_ram()
                return

            # フレーム数による自動停止
            if self._auto_stop_enabled and self._auto_stop_frames > 0:
                if len(self._ram_frames) >= self._auto_stop_frames:
                    msg = f"Reached {self._auto_stop_frames} frames. Auto-stopped."
                    self.sig_record_status.emit(msg)
                    self.sig_autostop.emit(msg)
                    self.stop_recording_ram()
                    return

        except Exception as e:
            print(f"[ERROR] snapshot was missed: {e}")

    def _step_loop(self):
        #1回分の step 取得＋ステージ移動を実行し、次回も自分をスケジュールする
        if not self._recording:
            return  # 停止したら終了
        self._do_one_step()  # ← 1 フレーム + 1 ステップの関数
        QTimer.singleShot(0, self._step_loop)        # 次の step を Qt のイベントループにスケジュール


    @Slot()
    def on_stage_step_done(self):
        # step録画中でなければ無視
        if not self._recording or not self._step_waiting:
            return

        self._step_waiting = False

        # 完了後 100ms 待ってから撮影
        QTimer.singleShot(100, self._capture_after_step_done)


    def _capture_after_step_done(self):
        if not self._recording:
            return

        try:
            snapshot = self.do_capture_snapshot()
            if snapshot is None:
                print("[CaptureWorker] snapshot was None after step_done")
                # 次のstepは出す（止めたいならここでstopにしてもよい）
                self._schedule_next_step()
                return

            data  = snapshot["data"]
            seq   = snapshot["seq"]
            ts_us = snapshot["ts_us"]
            exp_us = snapshot["exp_us"]

            host_ns = time.perf_counter_ns()

            arr = np.frombuffer(data, dtype=self._dtype).reshape(self._h, self._w).copy()
            self._ram_frames.append(arr)
            print(f"[CaptureWorker] append frame #{len(self._ram_frames)}")
            self._ram_bytes += arr.nbytes

            if self._t0_wall_ns is not None and self._t0_mono_ns is not None:
                wall_ns = self._t0_wall_ns + (host_ns - self._t0_mono_ns)
            else:
                wall_ns = time.time_ns()

            self._meta.append((seq, ts_us, host_ns, wall_ns, exp_us))

            # ドロップ検出
            #if self._last_seq is not None and seq != self._last_seq + 1:
            #    gap = seq - (self._last_seq + 1)
            #    self.sig_record_status.emit(
            #        f"Frame drop detected: missed {gap} frame(s) (seq {self._last_seq} -> {seq})"
            #    )
            #self._last_seq = seq

            # RAM上限
            if self._ram_bytes > self._ram_limit:
                msg = f"RAM limit reached ({self._ram_bytes/(1024**3):.2f} GB). Auto-stopped."
                self.sig_record_status.emit(msg)
                self.sig_autostop.emit(msg)
                self.stop_recording_ram()
                return

            # フレーム数による自動停止
            if self._auto_stop_enabled and self._auto_stop_frames > 0:
                if len(self._ram_frames) >= self._auto_stop_frames:
                    msg = f"Reached {self._auto_stop_frames} frames. Auto-stopped."
                    self.sig_record_status.emit(msg)
                    self.sig_autostop.emit(msg)
                    self.stop_recording_ram()
                    return

        except Exception as e:
            print(f"[CaptureWorker] capture_after_step_done error: {e}")

        self._schedule_next_step()

    """

    @Slot(object)
    def start_recording_ram_step(self, step_program):
        print("[CaptureWorker] start_recording_step_mode")
        if self._recording:
            return

        if not step_program:
            self.sig_record_status.emit("STEP program is empty.")
            return

        self._dtype = np.uint8 if self._bits == 8 else np.uint16
        self._step_program = list(step_program)
        self._color_index = 0
        self._completed_steps = 0

        self._ram_frames.clear()
        self._meta.clear()
        self._ram_bytes = 0
        self._last_seq = None
        self._t0_wall_ns = time.time_ns()
        self._t0_mono_ns = time.perf_counter_ns()
        self._recording = True

        self.main.stage_bridge.sig_reset_dda.emit()
        self._step_waiting = False
        self._step_inflight = False

        self.sig_record_status.emit("Recording to RAM...")
        #self._emit_step_once() 
        self._step_waiting = False
        self._step_inflight = False
        self._color_index = 0

        self._laser_all_off()

        QTimer.singleShot(0, self._run_next_color_in_step)

    # ステップ完了のシグナルを受け取ったときの処理。ステップ録画モードでなければ無視。完了後 100ms 待ってから撮影を行う。
    @Slot()
    def on_stage_step_done(self):
        if not self._recording or not self._step_waiting:
            return

        self._step_waiting = False
        self._color_index = 0

        QTimer.singleShot(100, self._run_next_color_in_step)

    def _run_next_color_in_step(self):
        if not self._recording:
            return

        if self._color_index >= len(self._step_program):
            self._completed_steps += 1

            if self._auto_stop_enabled and self._auto_stop_frames > 0:
                if self._completed_steps >= self._auto_stop_frames:
                    msg = f"Reached {self._auto_stop_frames} steps. Auto-stopped."
                    self.sig_record_status.emit(msg)
                    self.sig_autostop.emit(msg)
                    self.stop_recording_ram()
                    return

            self._schedule_next_step()
            return

        cfg = self._step_program[self._color_index]

        try:
            self._apply_filter_and_laser(cfg)
            delay_ms = int(cfg.get("switch_delay_ms", 50))
            QTimer.singleShot(delay_ms, self._capture_current_color)
        except Exception as e:
            print(f"[CaptureWorker] _run_next_color_in_step error: {e}")
            self.stop_recording_ram()

    def _capture_current_color(self):
        if not self._recording:
            return

        cfg = self._step_program[self._color_index]
        laser = cfg["laser"]
        #color_name = cfg["name"]   # 未使用？

        try:
            snapshot = self.do_capture_snapshot()
            #self._laser_all_off()

            if snapshot is None:
                print("[CaptureWorker] snapshot was None")
                self._laser_all_off()
                self._color_index += 1
                QTimer.singleShot(0, self._run_next_color_in_step)
                return

            data   = snapshot["data"]
            seq    = snapshot["seq"]
            ts_us  = snapshot["ts_us"]
            exp_us = snapshot["exp_us"]
            host_ns = time.perf_counter_ns()

            arr = np.frombuffer(data, dtype=self._dtype).reshape(self._h, self._w).copy()

            self._ram_frames.append(arr)
            self._ram_bytes += arr.nbytes

            if self._t0_wall_ns is not None and self._t0_mono_ns is not None:
                wall_ns = self._t0_wall_ns + (host_ns - self._t0_mono_ns)
            else:
                wall_ns = time.time_ns()

            self._meta.append((seq, ts_us, host_ns, wall_ns, exp_us))

            """
            self._ram_frames_by_color[color_name].append(arr)
            self._ram_bytes += arr.nbytes

            if self._t0_wall_ns is not None and self._t0_mono_ns is not None:
                wall_ns = self._t0_wall_ns + (host_ns - self._t0_mono_ns)
            else:
                wall_ns = time.time_ns()

            self._meta_by_color[color_name].append({
                "seq": seq,
                "ts_us": ts_us,
                "host_ns": host_ns,
                "wall_ns": wall_ns,
                "exp_us": exp_us,
                "step_index": self._completed_steps,
                "color_index": self._color_index,
                "color_name": color_name,
                "laser": cfg["laser"],
                "filter": cfg["filter"],
            })
            """

            if self._ram_bytes > self._ram_limit:
                msg = f"RAM limit reached ({self._ram_bytes/(1024**3):.2f} GB). Auto-stopped."
                self.sig_record_status.emit(msg)
                self.sig_autostop.emit(msg)
                self.stop_recording_ram()
                return

        except Exception as e:
            try:
                self._laser_all_off()
            except Exception:
                pass
            print(f"[CaptureWorker] _capture_current_color error: {e}")
            self.stop_recording_ram()
            return

        #self._laser_all_off()

        main = self.main.window()
        main.laser_pane.turn_off_line(
            backend_name=laser["backend_name"],
            connection_key=laser["connection_key"],
            line_id=laser["line_id"],
        )

        self._color_index += 1
        QTimer.singleShot(0, self._run_next_color_in_step)


    # STEP多色モードで、現在のステップの次の色に切り替えるときに呼ぶ。main の pane helper を呼び出してフィルターとレーザーを切り替える。
    def _apply_filter_and_laser(self, cfg: dict):
        pane = getattr(self, "main", None)
        if pane is None:
            raise RuntimeError("main is not set")

        main = pane.window()
        if main is None:
            raise RuntimeError("MainWindow not found")

        #self._laser_all_off()  # 二重になってるのでここはやめる

        if not hasattr(main.laser_pane, "turn_on_line"):
            raise RuntimeError("laser_pane.turn_on_line() is not implemented yet")
        laser = cfg["laser"]
        main.laser_pane.turn_on_line(
            backend_name=laser["backend_name"],
            connection_key=laser["connection_key"],
            line_id=laser["line_id"],
        )

        if not hasattr(main.filter_pane, "set_filter_by_label"):
            raise RuntimeError("filter_pane.set_filter_by_label() is not implemented yet")
        main.filter_pane.set_filter_by_label(cfg["filter"])


    def _laser_all_off(self):
        pane = getattr(self, "main", None)
        if pane is None:
            return

        main = pane.window()
        if main is None:
            return

        if hasattr(main.laser_pane, "turn_off_all_lines"):
            main.laser_pane.turn_off_all_lines()




    def _schedule_next_step(self):
        if not self._recording:
            return
        QTimer.singleShot(0, self._emit_step_once)

    def _emit_step_once(self):
        if not self._recording:
            return
        if self._step_inflight:
            return

        self._step_inflight = True
        self._step_waiting = True

        try:
            self.main.stage_bridge.sig_step_once.emit()
        finally:
            # stage側で永遠に完了しない場合の保険を入れるならここでタイムアウトを仕込む
            self._step_inflight = False

    """
    @Slot()
    def stop_recording_ram(self):
        print(f"[CaptureWorker] stop_recording_ram: recording={self._recording}, n_frames={len(self._ram_frames)}")    #デバッグ用
        
        #print(      #ステージstep完了フラグのデバッグ用
        #    "[WORKER_STOP]",
        #    "recording=", self._recording,
        #    "step_waiting=", getattr(self, "_step_waiting", None),
        #    "step_inflight=", getattr(self, "_step_inflight", None),
        #    "n_frames=", len(self._ram_frames),
        #)

        if not self._recording:
            return

        self._recording = False
        n = len(self._ram_frames)
        gb = self._ram_bytes / (1024**3)
        self.sig_record_status.emit(f"Stopped. RAM buffered: {n} frames, {gb:.2f} GB")
        self.sig_recording_stopped.emit()
        #self._io_set_output(False)  # 録画終了=外部出力OFF


    # multi color step recordingに対応した stop_recording_ram
    @Slot()
    def stop_recording_ram(self):
        total_frames = len(self._ram_frames)

        print(
            f"[CaptureWorker] stop_recording_ram: "
            f"recording={self._recording}, n_frames={total_frames}"
        )

        if not self._recording:
            return

        self._recording = False
        self._step_waiting = False
        self._step_inflight = False

        try:
            self._laser_all_off()
        except Exception:
            pass

        gb = self._ram_bytes / (1024**3)
        self.sig_record_status.emit(
            f"Stopped. RAM buffered: {total_frames} frames, {gb:.2f} GB"
        )
        self.sig_recording_stopped.emit()
        """


    # -----
    #3. フレーム受信処理 on_image_event() と録画・自動停止・ステップ走査
    # -----

    @Slot(int, int)
    def on_image_event(self, wparam: int, lparam: int):
        #print(f"[CaptureWorker] on_image_event: paused={self._paused}, hcam={self._hcam}, buf_is_none={self._buf is None}") #デバッグ用
        if self._paused or not self._hcam or self._buf is None:
            return

        frame = self.backend.pull_frame_into_buffer(self._buf, self._size, self._bits)
        if frame is None:
            #print("[CaptureWorker] frame is None (no new frame)")   #デバッグ用
            return
        
        # frame を取得した直後に追加
        seq = frame["seq"]
        ts_us = frame["ts_us"]
        exp_us = frame["exp_us"]

        # このフレームをホスト側で受け取った時刻（高分解能）
        host_ns = time.perf_counter_ns()        

        data = frame["data"]
        # seq, ts_us, exp_us なども frame から読む
        self.sig_frame_ready.emit(frame)

        #if len(self._ram_frames) % 10 == 0:
            #print(f"[CaptureWorker] RAM frames = {len(self._ram_frames)}")  #デバッグ用

        if self._recording:
            print(f"[CaptureWorker] append frame #{len(self._ram_frames)}")
            # 独立コピーでRAMに確保（元バッファと切る）
            arr = np.frombuffer(data, dtype=self._dtype).reshape(self._h, self._w).copy()
            self._ram_frames.append(arr)
            print(f"[CaptureWorker] append frame #{len(self._ram_frames)}") #デバッグ用
            self._ram_bytes += arr.nbytes       # フレーム本体をRAMへ

            # 録画開始時の基準から人間時間(UTC)のエポックnsを推定
            if self._t0_wall_ns is not None and self._t0_mono_ns is not None:
                wall_ns = self._t0_wall_ns + (host_ns - self._t0_mono_ns)
            else:
                # 念のためフォールバック
                wall_ns = time.time_ns()

            self._meta.append((seq, ts_us, host_ns, wall_ns, exp_us))


            # ドロップ検出（連番抜け）
            if self._last_seq is not None and seq != self._last_seq + 1:
                gap = seq - (self._last_seq + 1)
                self.sig_record_status.emit(f"Frame drop detected: missed {gap} frame(s) (seq {self._last_seq} -> {seq})")
            self._last_seq = seq

            if self._ram_bytes > self._ram_limit:
                msg = f"RAM limit reached ({self._ram_bytes/(1024**3):.2f} GB). Auto-stopped."
                self.sig_record_status.emit(msg)
                self.sig_autostop.emit(msg)
                # ★ カメラ録画停止＋ステージ Home/Return をここで実行
                self.stop_recording_ram()
                return

            # 追加: フレーム数による自動停止
            if self._auto_stop_enabled and self._auto_stop_frames > 0:
                if len(self._ram_frames) >= self._auto_stop_frames:
                    msg = f"Reached {self._auto_stop_frames} frames. Auto-stopped."
                    self.sig_record_status.emit(msg)
                    self.sig_autostop.emit(msg)
                    # ★ カメラ録画停止＋ステージ Home/Return をここで実行
                    self.stop_recording_ram()
                    return

    # -----
    # 4. reconfigure() の位置付け
    # -----

    def reconfigure(self):
        if not self._hcam:
            return
        backend = getattr(self, "backend", None)
        if backend is None:
            print("[CaptureWorker] reconfigure called but backend is None")
            return
        # ---- 一時停止 ----
        try:
            backend.set_paused(True)
        except Exception as e:
            print(f"[CaptureWorker] backend.set_paused(True) error in reconfigure: {e}")
        # ---- サイズ問い合わせ ----
        try:
            params = None
            try:
                params = backend.query_params(self._bits)
            except Exception as e:
                print(f"[CaptureWorker] query_params error in reconfigure: {e}")
                params = None
            if params is not None:
                self._w, self._h, self._bits, self._bpl, self._size = params
            else:
                print("[CaptureWorker] reconfigure: query_params returned None")
                return
            # ---- バッファ再確保 ----
            self._buf = (ctypes.c_ubyte * self._size)()
        finally:
            # ---- 再開 ----
            try:
                backend.set_paused(False)
            except Exception as e:
                print(f"[CaptureWorker] backend.set_paused(False) error in reconfigure: {e}")

#==== STEP-scan 関連のダイアログ =====
class StepColorCountDialog(QDialog):
    def __init__(self, max_colors: int, parent=None, initial_value: int = 1):
        super().__init__(parent)
        self.setWindowTitle("STEP multicolor setup")

        self.spin = QSpinBox(self)
        self.spin.setRange(1, max(1, max_colors))
        #self.spin.setValue(1)
        self.spin.setValue(max(1, min(int(initial_value), max_colors)))

        btn_ok = QPushButton("OK", self)
        btn_cancel = QPushButton("Cancel", self)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("How many colors do you want to capture per step?"))
        lay.addWidget(self.spin)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        lay.addLayout(row)

        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

    def get_value(self) -> int | None:
        if self.exec() != QDialog.Accepted:
            return None
        return int(self.spin.value())

#==== STEP-scan 関連のダイアログ =====
class StepColorProgramDialog(QDialog):
    def __init__(self, n_colors: int, laser_choices: list[dict], filter_choices: list[str], parent=None, initial_program: list[dict] | None = None):
        super().__init__(parent)
        self.setWindowTitle("STEP multicolor program")

        self._rows = []
        initial_program = initial_program or []

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Select laser / filter for each color."))

        grid = QGridLayout()
        grid.addWidget(QLabel("Name"), 0, 0)
        grid.addWidget(QLabel("Laser"), 0, 1)
        grid.addWidget(QLabel("Filter"), 0, 2)
        grid.addWidget(QLabel("Delay (ms)"), 0, 3)


        for i in range(n_colors):
            init = initial_program[i] if i < len(initial_program) else {}

            cmb_laser = QComboBox(self)
            laser_index = 0
            for j, choice in enumerate(laser_choices):
                cmb_laser.addItem(choice["label"], choice)
                init_laser = init.get("laser", {})
                if (
                    choice.get("backend_name") == init_laser.get("backend_name")
                    and choice.get("connection_key") == init_laser.get("connection_key")
                    and choice.get("line_id") == init_laser.get("line_id")
                ):
                    laser_index = j
            cmb_laser.setCurrentIndex(laser_index)

            cmb_filter = QComboBox(self)
            filter_index = 0
            for j, name in enumerate(filter_choices):
                cmb_filter.addItem(name, name)
                if name == init.get("filter"):
                    filter_index = j
            cmb_filter.setCurrentIndex(filter_index)

            #cmb_name = QComboBox(self)
            #cmb_name.setEditable(True)
            #cmb_name.addItem(init.get("name", f"Color{i+1}"))
            #cmb_name.setCurrentText(init.get("name", f"Color{i+1}"))

            name_edit = QLineEdit(self)
            name_edit.setText(init.get("name", f"Color{i+1}"))

            spin_delay = QSpinBox(self)
            spin_delay.setRange(0, 5000)
            spin_delay.setValue(int(init.get("switch_delay_ms", 50)))

            #grid.addWidget(cmb_name, i + 1, 0)
            grid.addWidget(name_edit, i + 1, 0)
            grid.addWidget(cmb_laser, i + 1, 1)
            grid.addWidget(cmb_filter, i + 1, 2)
            grid.addWidget(spin_delay, i + 1, 3)

            #self._rows.append((cmb_name, cmb_laser, cmb_filter, spin_delay))
            self._rows.append((name_edit, cmb_laser, cmb_filter, spin_delay))

        lay.addLayout(grid)

        btn_ok = QPushButton("OK", self)
        btn_cancel = QPushButton("Cancel", self)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(btn_ok)
        row.addWidget(btn_cancel)
        lay.addLayout(row)

        btn_ok.clicked.connect(self.accept)
        btn_cancel.clicked.connect(self.reject)

    def get_program(self) -> list[dict] | None:
        if self.exec() != QDialog.Accepted:
            return None

        out = []
        seen = set()

        #for cmb_name, cmb_laser, cmb_filter, spin_delay in self._rows:
        #    color_name = cmb_name.currentText().strip() or "Color"
        for name_edit, cmb_laser, cmb_filter, spin_delay in self._rows:
            color_name = name_edit.text().strip() or "Color"
            laser_choice = cmb_laser.currentData()
            filter_name = cmb_filter.currentData()
            delay_ms = int(spin_delay.value())

            key = (laser_choice["backend_name"], laser_choice["connection_key"], laser_choice["line_id"], filter_name)
            if key in seen:
                raise ValueError(f"Duplicated laser/filter pair: {laser_choice['label']} + {filter_name}")
            seen.add(key)

            out.append({
                "name": color_name,
                "laser": laser_choice,
                "filter": filter_name,
                "switch_delay_ms": delay_ms,
            })

        return out


class CameraPane(QWidget):
    """カメラUI＋処理を完結させる注入用ウィジェット"""

    # ==== CameraPane → CaptureWorker の制御シグナル ====
    req_pause = Signal(bool)
    req_record_arm = Signal(bool)
    req_record_start_ram = Signal()
    req_record_start_ram_continuous = Signal()

    #req_record_start_ram_step = Signal()
    req_record_start_ram_step = Signal(object)

    req_record_stop_ram = Signal()
    req_set_autostop = Signal(bool, int)
    req_capture_snapshot = Signal()
    # ステージ連動フラグ
    #req_set_stage_link = Signal(bool)
    # Auto-return フラグ
    req_set_auto_return = Signal(bool)


    def __init__(
        self,
        hcam,
        timing_logger=None,
        stage_bridge=None,
        backend: ICameraBackend | None = None,
        parent=None,
    ):
        super().__init__(parent)

        # --------------------------------------------------
        # 1) コア参照・内部状態
        # --------------------------------------------------
        self.hcam = hcam
        self._timing_logger = timing_logger
        self.stage_bridge = None                 # set_stage_bridge() でセット
        self.backend: ICameraBackend | None = backend
        self._current_camera_key: str | None = None
        #self.worker.sig_recording_stopped.connect(self._on_recording_stopped)

        self._settings = QSettings("LabSuite", "Camera")
        self.setWindowTitle("NKCAM Dispatcher (pause/resume)")

        # RAM レビュー用
        self._ram_view = None
        self._ram_meta = None
        self._times_ms = None
        self._stack = None

        # 表示用画像・回転
        self._last_img = None
        self._rot_deg = 0   # 0, 90, 180, 270

        # ROI 状態
        self._current_roi = None  # 現在の ROI (x, y, w, h) or None

        # 再生・録画状態
        self._paused = False
        self._is_recording = False
        self._recording_active = False  # 録画中 LiveView スタイル用

        # ボタンスタイル
        self._style_running_red = (
            "QPushButton { border: 1px solid red; padding: 4px 8px; "
            "background-color: red; color: white; font-family: Arial black; "
            "font-weight: 900;}"
        )
        self._style_recording_green = (
            "QPushButton { border: 2px solid #b7f3b0; padding: 2px 8px; "
            "background-color: #b7f3b0; }"
        )

        # --------------------------------------------------
        # 2) ウィンドウサイズ制御
        # --------------------------------------------------
        self.resize(1200, 1000)
        #self.setMinimumSize(600, 600)
        #screen = QGuiApplication.primaryScreen().geometry()
        #self.setMaximumSize(screen.width(), screen.height())

        # --------------------------------------------------
        # 3) 左パネル（画像表示＋回転＋再生 UI）
        # --------------------------------------------------

        # ROI 表示ラベル
        self.roi_label = QLabel("ROI: FULL")
        self.roi_label.setObjectName("roiLabel")
        self.roi_label.setStyleSheet("#roiLabel { color: #444; }")

        # 回転ボタン
        self.btn_rot_l = QPushButton("⟲ -90°")
        self.btn_rot_r = QPushButton("⟳ +90°")
        self.btn_rot_l.clicked.connect(self._rotate_left)
        self.btn_rot_r.clicked.connect(self._rotate_right)

        # ROI + 回転 行
        rot_row = QWidget()
        rot_layout = QHBoxLayout(rot_row)
        rot_layout.setContentsMargins(0, 0, 0, 0)
        rot_layout.addWidget(self.roi_label, 0)
        rot_layout.addStretch(1)
        rot_layout.addWidget(self.btn_rot_l, 0)
        rot_layout.addWidget(self.btn_rot_r, 0)

        # 画像ビュー
        self.label = RoiView(self)
        self.label.setMinimumSize(320, 240)
        self.label.enable_edit(False)
        self.label.sig_roi_changed.connect(self.on_roi_changed)

        # 再生 UI
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)

        self.btn_play = QPushButton("Play")
        self.btn_play.setEnabled(False)

        self.lbl_time = QLabel("0 / 0 frames")
        self.lbl_time.setFixedWidth(120)
        self.lbl_time.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.play_timer = QTimer(self)
        self.play_timer.setInterval(int(1000 / 30))
        self.play_timer.timeout.connect(self._on_play_tick)

        ctl_play = QWidget()
        _ph = QHBoxLayout(ctl_play)
        _ph.setContentsMargins(4, 4, 4, 4)
        _ph.addWidget(self.btn_play, 0)
        _ph.addWidget(self.slider, 1)
        _ph.addWidget(self.lbl_time, 0)

        # 左パネルまとめ
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(rot_row, 0)
        lv.addWidget(self.label, 1)
        lv.addWidget(ctl_play, 0)

        # --------------------------------------------------
        # 4) 右パネル：Camera コントロール UI
        # --------------------------------------------------
        self.form = QFormLayout()

        # ---- Camera backend 選択 + Connect/Disconnect ----
        self.backends = scan_camera_backends()
        self.cmb_camera = QComboBox()
        for key, info in self.backends.items():
            self.cmb_camera.addItem(info["label"], key)

        # 前回選択 backend を復元
        last_key = self._settings.value("last_camera_backend", "", type=str)
        if last_key:
            idx = self.cmb_camera.findData(last_key)
            if idx >= 0:
                self.cmb_camera.setCurrentIndex(idx)

        self.btn_connect = QPushButton("Connect Camera")
        self.btn_connect.clicked.connect(self._on_connect_clicked)

        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setEnabled(False)
        self.btn_disconnect.setVisible(False)
        self.btn_disconnect.clicked.connect(self._on_disconnect_clicked)

        row_cam = QHBoxLayout()
        row_cam.addWidget(QLabel("Camera:"))
        row_cam.addWidget(self.cmb_camera)
        row_cam.addWidget(self.btn_connect)
        row_cam.addWidget(self.btn_disconnect)
        row_cam.addStretch(1)

        # ---- Gain / Exposure ----
        self.ctrl_gain = QSpinBox()
        self.ctrl_gain.setRange(0, 10000)
        self.ctrl_gain.setSingleStep(10)

        self.ctrl_expo = QDoubleSpinBox()
        self.ctrl_expo.setDecimals(0)
        self.ctrl_expo.setRange(0.001, 10_000.000)
        self.ctrl_expo.setSingleStep(0.1)
        self.ctrl_expo.setSuffix(" ms")

        # Enter キーで apply_gain_expo を実行
        self.ctrl_gain.installEventFilter(self)
        self.ctrl_expo.installEventFilter(self)

        self.btn_apply_ae = QPushButton(" Apply Gain / Exposure ")

        form_gainexpo = QHBoxLayout()
        form_gainexpo.addWidget(QLabel("Gain:"))
        form_gainexpo.addWidget(self.ctrl_gain)
        form_gainexpo.addWidget(QLabel("Exposure:"))
        form_gainexpo.addWidget(self.ctrl_expo)
        form_gainexpo.addWidget(self.btn_apply_ae)

        # ---- Resolution / Bit Depth ----
        self.ctrl_res = QComboBox()
        self.ctrl_bit = QComboBox()
        self.ctrl_bit.addItems(["8-bit", "16-bit"])
        self.btn_apply_rb = QPushButton(" Apply Resolution / Bit  ")

        form_resbit = QHBoxLayout()
        form_resbit.addWidget(QLabel("Resolution:"))
        form_resbit.addWidget(self.ctrl_res)
        form_resbit.addWidget(QLabel("Bit Depth:"))
        form_resbit.addWidget(self.ctrl_bit)
        form_resbit.addWidget(self.btn_apply_rb)

        # ---- Live / Capture / Save ----
        self.btn_toggle = QPushButton("Live view")
        self.btn_capture = QPushButton("Capture")
        self.btn_save = QPushButton("Save")

        live_layout = QHBoxLayout()
        live_layout.addWidget(self.btn_toggle)
        live_layout.addWidget(self.btn_capture)
        live_layout.addWidget(self.btn_save)

        # ---- Record / Auto-stop ----
        #self.chk_record_arm = QCheckBox("Link stage")
        #self.chk_record_arm.setChecked(False)

        self.btn_record = QPushButton("Start Recording")
        self.btn_record.setEnabled(False)

        fm = self.btn_record.fontMetrics()
        w = fm.horizontalAdvance("Stop Recording") + 24
        self.btn_record.setMinimumWidth(w)
        self.btn_record.setMaximumWidth(w)

        self.chk_autostop = QCheckBox("Auto-stop at")
        self.spin_autostop = QSpinBox()
        self.spin_autostop.setRange(1, 10_000_000)
        self.spin_autostop.setValue(1000)
        self.spin_autostop.setEnabled(False)

        lbl_frames = QLabel("frames")

        record_autostop_layout = QHBoxLayout()
        #record_autostop_layout.addWidget(self.chk_record_arm)
        record_autostop_layout.addWidget(self.btn_record)
        record_autostop_layout.addSpacing(8)
        record_autostop_layout.addWidget(self.chk_autostop)
        record_autostop_layout.addWidget(self.spin_autostop)
        record_autostop_layout.addWidget(lbl_frames)

        # ---- Stage mode / Auto-return ----
        self.chk_auto_return = QCheckBox("Auto-return to registered start position")
        self.chk_auto_return.setEnabled(False)  # Link stage ON 時のみ有効

        self.cmb_stage_mode = QComboBox()
        self.cmb_stage_mode.addItem("OFF",               StageLinkMode.STAGE_OFF)
        self.cmb_stage_mode.addItem("MOVIE-scan",        StageLinkMode.MOVE_CONTINUOUS)
        self.cmb_stage_mode.addItem("STEP-scan",              StageLinkMode.STEP)
        self._stage_link_mode = StageLinkMode.STAGE_OFF

        row_stage_mode = QHBoxLayout()
        row_stage_mode.addWidget(QLabel("Stage mode:"))
        row_stage_mode.addWidget(self.cmb_stage_mode)
        row_stage_mode.addSpacing(8)
        row_stage_mode.addWidget(self.chk_auto_return)
        row_stage_mode.addStretch(1)

        # ---- ROI ボタン ----
        self.btn_roi_set = QPushButton("set ROI")
        self.btn_roi_apply = QPushButton("apply ROI")
        self.btn_roi_reset = QPushButton("clear ROI")

        roi_layout = QHBoxLayout()
        roi_layout.addWidget(self.btn_roi_set)
        roi_layout.addWidget(self.btn_roi_apply)
        roi_layout.addWidget(self.btn_roi_reset)

        # ---- ステータス ----
        self.status_label = QLabel("Waiting...", self)
        self.status_label.setStyleSheet("QLabel { font-weight: bold; }")

        # ---- Camera グループまとめ ----
        cam_form = QFormLayout()
        cam_form.addRow(row_cam)
        cam_form.addRow(form_gainexpo)
        cam_form.addRow(form_resbit)
        cam_form.addRow(live_layout)
        cam_form.addRow(record_autostop_layout)
        cam_form.addRow(row_stage_mode)
        cam_form.addRow(roi_layout)
        cam_form.addRow(self.status_label)

        self.grp_cam = QGroupBox("Camera")
        self.grp_cam.setLayout(cam_form)

        self.form.addRow(self.grp_cam)

        # 右パネル（form を包む）
        panel = QWidget()
        panel.setLayout(self.form)
        self.form.setAlignment(Qt.AlignTop)
        #panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # --------------------------------------------------
        # 5) ルートレイアウト
        # --------------------------------------------------
        root = QHBoxLayout(self)
        root.addWidget(left, 1)
        root.addWidget(panel, 0, Qt.AlignTop)

        # --------------------------------------------------
        # 6) 初期状態
        # --------------------------------------------------
        self._set_status("Not connected")
        self._set_cam_controls_visible_enabled(False, False)

        # Stage mode の変更通知
        self.cmb_stage_mode.currentIndexChanged.connect(self.on_stage_mode_changed)

        # --------------------------------------------------
        # 7) StageBridge セット（あれば）
        # --------------------------------------------------
        if stage_bridge is not None:
            self.set_stage_bridge(stage_bridge)


    # ==============================
    # 基本ヘルパー / 状態表示
    # ==============================
    def _set_status(self, text: str):
        self.status_label.setText(text)

    def _set_cam_controls_visible_enabled(self, visible: bool, enabled: bool):
        """カメラコントロールを一括で表示・非表示＋有効・無効を切り替える"""
        widgets = [
            self.ctrl_gain, self.ctrl_expo, self.ctrl_res, self.ctrl_bit,
            self.btn_apply_ae, self.btn_apply_rb, self.btn_toggle, self.btn_record,
            #self.chk_record_arm, 
            self.chk_autostop, self.spin_autostop,
            self.btn_roi_set, self.btn_roi_apply, self.btn_roi_reset,
            self.btn_capture, self.btn_save, self.chk_auto_return, self.cmb_stage_mode
        ]
        for w in widgets:
            w.setVisible(visible)
            if w is self.spin_autostop:
                # Auto-stop のスピンボックスはチェック状態も見る
                w.setEnabled(enabled and self.chk_autostop.isChecked())
            else:
                w.setEnabled(enabled)

    # ==============================
    # 接続 / 切断 / ライフサイクル
    # ==============================
    @Slot()
    def _on_connect_clicked(self):
        # コンボボックスから key を取得（例: "Nikon_DS50M"）
        key = self.cmb_camera.currentData()
        if not key:
            self._set_status("No camera backend selected.")
            return

        # 共通の connect ヘルパーを呼ぶ
        self._connect_camera_for_key(key)

    @Slot()
    def _on_disconnect_clicked(self):
        """Disconnect ボタンから呼ばれるラッパ"""
        self._disconnect_camera()

    def _connect_camera_for_key(self, key: str) -> bool:
        """
        Camera backend key (例: 'Nikon_DS50M') を受け取り、
        既存接続をクリーンに切ってから新しく接続する。
        """
        info = self.backends.get(key)
        if info is None:
            self._set_status(f"Unknown camera backend: {key}")
            return False

        # すでに何かしら接続済みなら一旦クリーンに落とす（機種切り替え対応）
        if getattr(self, "backend", None) is not None or getattr(self, "worker", None) is not None:
            self._disconnect_camera()

        backend_class = info["class"]
        self.backend = backend_class(self)
        self._current_camera_key = key

        ok = False
        try:
            ok = self.backend.connect()
        except Exception as e:
            print(f"connect failed: {e}")
            ok = False

        if not ok:
            self.backend = None
            self._set_status("Failed to connect camera.")
            return False

        # backend 側で hcam を持っているなら CameraPane 側にもコピー
        try:
            if hasattr(self.backend, "hcam"):
                self.hcam = self.backend.hcam
        except Exception:
            pass

        # backend.connect() の中で _init_camera_ui() が呼ばれている前提
        # （Nikon / Thorlabs の現状コードと同じパターン）
        # ここでは UI 全体の状態だけ整える
        self._set_cam_controls_visible_enabled(True, True)
        self.grp_cam.setVisible(True)

        # 接続が済んだら、Connect ボタンと backend 選択はロックする
        self.btn_connect.setEnabled(False)
        self.cmb_camera.setEnabled(False)

        # ★ Connect を隠して Disconnect を出す
        self.btn_connect.setVisible(False)
        self.btn_disconnect.setVisible(True)
        self.btn_disconnect.setEnabled(True)

        # ★ 接続成功した backend key を保存（次回復元用）
        self._settings.setValue("last_camera_backend", key)

        return True

    def _disconnect_camera(self):
        """
        カメラ接続の完全終了処理を 1 箇所に集約。
        - backend / worker / thread の後始末
        - シグナル切断
        - UI を 'Not connected' 状態に戻す
        """
        if getattr(self, "_disconnecting", False):
            return
        self._disconnecting = True

        try:
            # 0) 再生タイマー停止
            try:
                if hasattr(self, "play_timer") and self.play_timer.isActive():
                    self.play_timer.stop()
            except Exception:
                pass

            backend = getattr(self, "backend", None)
            worker = getattr(self, "worker", None)
            th     = getattr(self, "worker_thread", None)

            # 1) backend -> CameraPane のシグナル切断
            if backend is not None:
                for sig_name, slot in [
                    ("sig_event",        self.on_any_event),
                    ("sig_error",        self.on_error_event),
                    ("sig_disconnected", self.on_disconnected_event),
                    ("sig_frame",        self.on_frame_ready),
                ]:
                    sig = getattr(backend, sig_name, None)
                    if sig is not None and slot is not None:
                        try:
                            sig.disconnect(slot)
                        except Exception:
                            pass

                # sig_image → worker.on_image_event
                if worker is not None and hasattr(backend, "sig_image"):
                    try:
                        backend.sig_image.disconnect(worker.on_image_event)
                    except Exception:
                        pass

            # 2) worker -> CameraPane のシグナル切断
            if worker is not None:
                for sig, slot in [
                    (worker.sig_frame_ready,   self.on_frame_ready),
                    (worker.sig_record_status, self.on_record_status),
                    (worker.sig_autostop,      self.on_worker_autostop),
                ]:
                    try:
                        sig.disconnect(slot)
                    except Exception:
                        pass

            # 3) worker thread の停止
            if th is not None:
                try:
                    th.quit()
                    th.wait(3000)
                except Exception:
                    pass

            # 4) オブジェクト破棄
            try:
                if worker is not None:
                    worker.deleteLater()
            except Exception:
                pass
            try:
                if th is not None:
                    th.deleteLater()
            except Exception:
                pass

            self.worker = None
            self.worker_thread = None

            # 5) backend 側の disconnect
            if backend is not None:
                try:
                    backend.disconnect()
                except Exception:
                    pass

            # backend 参照も消しておく（再接続時にクリーンな状態から）
            self.backend = None

            # 6) UI を「未接続」状態に戻す
            self.hcam = None
            self._paused = False
            self._is_recording = False
            self._recording_active = False

            self._set_cam_controls_visible_enabled(False, False)
            self.btn_connect.setEnabled(True)
            self.cmb_camera.setEnabled(True)

            # ★ Connect を表示、Disconnect を隠す
            self.btn_connect.setVisible(True)
            self.btn_disconnect.setVisible(False)
            self.btn_disconnect.setEnabled(False)

            self._set_status("Not connected")

        finally:
            self._disconnecting = False

    def _init_camera_ui(self):
        # hcamあり前提。ここで only 一度だけワーカ等を立ち上げる
        cur_bits = 8
        try:
            if hasattr(self, "backend") and hasattr(self.backend, "get_current_bit_depth"):
                cur_bits = int(self.backend.get_current_bit_depth())
        except Exception as e:
            print(f"[CameraPane] get_current_bit_depth error: {e}")
            cur_bits = 8

        # WinMsg登録＋ストリーム開始（backend 経由）
        hwnd = int(self.window().winId())
        try:
            self.backend.start_stream(hwnd)
        except Exception as e:
            print(f"[CameraPane] backend.start_stream error: {e}")

        # ワーカ生成（接続後のみ）
        self.worker_thread = QThread(self)
        self.worker = CaptureWorker(self.hcam, bits=cur_bits, backend=self.backend)
        self.worker.main = self

        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.start()

        # ★ここで worker を backend に渡す（フレーム中継の設定）
        try:
            self.backend.attach_worker(self.worker)
        except Exception:
            pass

        # シグナル接続（backend 経由）
        self.backend.sig_event.connect(self.on_any_event)
        self.backend.sig_error.connect(self.on_error_event)
        self.backend.sig_disconnected.connect(self.on_disconnected_event)
        self.backend.sig_image.connect(self.worker.on_image_event, Qt.QueuedConnection)

        # フレームは backend → worker.sig_frame_ready → CameraPane の流れ
        self.backend.sig_frame.connect(self.on_frame_ready, Qt.QueuedConnection)
        

        # UI→スロット接続（既存のまま）
        # Gain/Exposure/Bit/ROI など
        self.btn_apply_ae.clicked.connect(self.apply_gain_expo)
        self.btn_apply_rb.clicked.connect(self.apply_res_bit)
        self.btn_toggle.clicked.connect(self.toggle_pause)

        self.btn_roi_set.clicked.connect(self.on_set_roi)
        self.btn_roi_apply.clicked.connect(self.on_apply_roi)
        self.btn_roi_reset.clicked.connect(self.on_reset_roi)
        
        # キャプチャボタン
        self.btn_capture.clicked.connect(self.on_click_capture)
        self.btn_save.clicked.connect(self.on_click_save)

        # Record 関連
        self.req_capture_snapshot.connect(self.worker.do_capture_snapshot, Qt.QueuedConnection)
        self.req_record_start_ram.connect(self.worker.start_recording_ram, Qt.QueuedConnection)
        self.req_record_start_ram_continuous.connect(self.worker.start_recording_continuous_mode, Qt.QueuedConnection)
        self.req_record_start_ram_step.connect(self.worker.start_recording_ram_step, Qt.QueuedConnection)
        self.req_record_stop_ram.connect(self.worker.stop_recording_ram, Qt.QueuedConnection)
        self.worker.sig_record_status.connect(self.on_record_status)
        self.btn_record.clicked.connect(self.on_click_record)
        self.worker.sig_recording_stopped.connect(self._on_worker_recording_stopped)
        #self.worker.sig_on_snapshot_ready.connect(self.on_snapshot_ready, Qt.QueuedConnection)
        self.worker.sig_snapshot_ready.connect(self.on_snapshot_ready, Qt.QueuedConnection)

        # ★ ステージ連動フラグ
        #self.req_set_stage_link.connect(self.worker.set_stage_link_enabled, Qt.QueuedConnection)
        #self.chk_record_arm.toggled.connect(self.on_link_stage_toggled)
        # 初期状態を Worker に同期
        #self.req_set_stage_link.emit(self.chk_record_arm.isChecked())

        # ★ Auto-return フラグ
        self.req_set_auto_return.connect(self.worker.set_auto_return_enabled, Qt.QueuedConnection)
        self.chk_auto_return.toggled.connect(self.on_auto_return_toggled)
        # 初期状態（デフォルト False）を同期
        self.req_set_auto_return.emit(self.chk_auto_return.isChecked())
        
        # Auto-stop 関連
        self.req_set_autostop.connect(self.worker.set_auto_stop, Qt.QueuedConnection)
        self.chk_autostop.toggled.connect(self.on_autostop_toggled)
        self.spin_autostop.valueChanged.connect(self.on_autostop_value_changed)
        self.worker.sig_autostop.connect(self.on_worker_autostop)

        # 再生UI
        self.btn_play.clicked.connect(self._on_click_play)
        self.slider.valueChanged.connect(self._on_slider_changed)

        # コントロールをSDK値で初期化
        self._populate_controls()
        self.grp_cam.setVisible(True)
        self.set_paused(True)
        self.btn_toggle.setText("Live view Start")
        self._set_status("Pause")

        # ★ step mode: stage完了通知 → workerへ
        if self.stage_bridge is not None and hasattr(self.stage_bridge, "sig_step_done"):
            try:
                self.stage_bridge.sig_step_done.connect(self.worker.on_stage_step_done, Qt.QueuedConnection)
            except Exception as e:
                print(f"[CameraPane] connect sig_step_done failed: {e}")


    def showEvent(self, ev):
        super().showEvent(ev)
        # 何もしない（フィルタは backend 側でインストール済み）

    def closeEvent(self, ev):
        # ウィンドウを閉じるときも、必ず共通の teardown を通す
        self._disconnect_camera()
        print("[CameraPane] closeEvent cleanly finished.")
        super().closeEvent(ev)

    # ==============================
    # StageBridge 連携
    # ==============================
    def set_stage_bridge(self, bridge):
        self.stage_bridge = bridge
        try:
            self.stage_bridge.sig_recording_state.connect(self._on_recording_state_changed)
        except Exception:
            pass

        # ★ 現在の設定を一度反映
        self._update_stage_link_config()

    def _update_stage_link_config(self):
        if self.stage_bridge is None:
            return

        mode_value  = int(getattr(self, "_stage_link_mode", StageLinkMode.STAGE_OFF))
        auto_return = self.chk_auto_return.isChecked()

        # 追加：StageStopMode に変換
        if auto_return:
            stop_mode = StageStopMode.STOP_AND_RETURN
        else:
            stop_mode = StageStopMode.STOP_ONLY

        try:
            # StageBridge 側も set_link_config(mode, stop_mode:int) に直す
            if hasattr(self.stage_bridge, "set_link_config"):
                self.stage_bridge.set_link_config(mode_value, int(stop_mode))
        except Exception as e:
            print(f"[CameraPane] _update_stage_link_config error: {e}")


    """
    @Slot(bool)
    def on_link_stage_toggled(self, v: bool):
        print("[CameraPane] on_link_stage_toggled:", v)
        #UI からのステージ連動 ON/OFF を Worker に伝える
        self.req_set_stage_link.emit(v)

        # ★ Link stage が OFF のときは Auto-return を強制 OFF + 無効化
        if not v:
            self.chk_auto_return.blockSignals(True)
            self.chk_auto_return.setChecked(False)
            self.chk_auto_return.blockSignals(False)
            self.chk_auto_return.setEnabled(False)
            self.req_set_auto_return.emit(False)
        else:
            # ON のときだけユーザーが触れる
            self.chk_auto_return.setEnabled(True)

        # ★ StageBridge にも現在設定を通知
        self._update_stage_link_config()
    """

    @Slot(bool)
    def on_auto_return_toggled(self, v: bool):
        # モードが STAGE_OFF のときは Auto-return は触らせない
        if getattr(self, "_stage_link_mode", StageLinkMode.STAGE_OFF) == StageLinkMode.STAGE_OFF:
            self.chk_auto_return.blockSignals(True)
            self.chk_auto_return.setChecked(False)
            self.chk_auto_return.blockSignals(False)

            # Worker にも常に False を送る
            self.req_set_auto_return.emit(False)

            # StageBridge 側にも OFF を通知
            self._update_stage_link_config()
            return

        # それ以外 (MOVE / STEP) のときだけ設定を反映
        self.req_set_auto_return.emit(v)
        self._update_stage_link_config()


    @Slot(int)
    def on_stage_mode_changed(self, index: int):
        data = self.cmb_stage_mode.itemData(index)
        print("[CameraPane] on_stage_mode_changed: mode =", data)
        if isinstance(data, StageLinkMode):
            self._stage_link_mode = data
        else:
            try:
                self._stage_link_mode = StageLinkMode(int(data))
            except Exception:
                self._stage_link_mode = StageLinkMode.MOVE_CONTINUOUS

        # ★ モード変更を StageBridge に通知
        self._update_stage_link_config()



    # ==============================
    # LiveView / Pause 制御
    # ==============================
    def toggle_pause(self):
        self.set_paused(not self._paused)

    def set_paused(self, v: bool):
        self._paused = v

        if hasattr(self, "worker"):
            self.worker._paused = v

        backend = getattr(self, "backend", None)
        if backend is not None:
            backend.set_paused(v)

        if v:
            # Pause 状態
            self.btn_toggle.setText("Live View")
            self.btn_toggle.setStyleSheet("")   # 停止中は常にデフォルト
            self._set_status("Pause")
        else:
            # Running 状態
            self.btn_toggle.setText("Live view Stop")
            self.btn_toggle.setStyleSheet(self._style_running_red)
            self._set_status("Running")
            
            # ★ 録画中なら緑、そうでなければ赤
            #if getattr(self, "_recording_active", False):
            #    self.btn_toggle.setStyleSheet(self._style_recording_green)
            #else:
            #    self.btn_toggle.setStyleSheet(self._style_running_red)
            #self._set_status("Running")

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_P:
            self.toggle_pause()
            e.accept()
            return
        super().keyPressEvent(e)

    # ==============================
    # Gain / Exposure / Resolution / Bit
    # ==============================
    @Slot()
    def apply_gain_expo(self):
        """UI から値を取り出して backend に渡すだけにする"""
        if not self.hcam:
            return

        gain = int(self.ctrl_gain.value())
        expo_ms = float(self.ctrl_expo.value())

        # backend に反映を依頼
        if hasattr(self, "backend") and hasattr(self.backend, "apply_gain_expo"):
            self.backend.apply_gain_expo(gain, expo_ms)

        # ユーザー設定として保存（これは GUI の責務）
        self._settings.setValue("gain", gain)
        self._settings.setValue("expo_ms", expo_ms)

    def eventFilter(self, obj, event):
        # Gain / Exposure のスピンボックスで Enter が押されたら apply_gain_expo を実行
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if obj is self.ctrl_gain or obj is self.ctrl_expo:
                self.apply_gain_expo()
                return True  # イベントをここで消費
        return super().eventFilter(obj, event)

    @Slot()
    def apply_res_bit(self):
        if not self.hcam:
            return

        # UI から値を取得
        self._set_status("Waiting...")
        res_idx = self.ctrl_res.currentData()
        bit_idx = self.ctrl_bit.currentIndex()

        # backend にデバイス設定を任せる
        if hasattr(self, "backend") and hasattr(self.backend, "apply_res_bit"):
            self.backend.apply_res_bit(res_idx, bit_idx)

        # ここで一括して「Pause状態」にする（スタイルも含めて）
        self.set_paused(True)

    def _populate_controls(self):
        """backend で SDK 値を読み込み、その後にユーザー設定を反映する"""
        # まず backend 側に SDK→UI の初期化を任せる
        if hasattr(self, "backend") and hasattr(self.backend, "populate_controls"):
            self.backend.populate_controls(self)

        # その上から QSettings の値を上書き（UI の責務）
        g = self._settings.value("gain", None, type=int)
        e = self._settings.value("expo_ms", None, type=float)

        if g is not None:
            self.ctrl_gain.setValue(g)
        if e is not None:
            self.ctrl_expo.setValue(e)

        # UI を SDK に反映（保存設定があれば）
        if g is not None or e is not None:
            self.apply_gain_expo()

    # ==============================
    # Backend からのイベント処理
    # ==============================
    @Slot(int, int)
    def on_any_event(self, wparam: int, lparam: int):
        name = None
        # backend が describe_event を持っていれば使う
        if hasattr(self, "backend") and hasattr(self.backend, "describe_event"):
            try:
                name = self.backend.describe_event(wparam)
            except Exception:
                name = None

        if not name:
            name = f"0x{wparam:04x}"

        print(f"evt={name} wp={wparam:#x} lp={lparam:#x}")

    @Slot(int, int)
    def on_error_event(self, wparam: int, lparam: int):
        #self._set_text(f"[ERROR] wp={wparam:#x} lp={lparam:#x}")
        print(f"[ERROR] wp={wparam:#x} lp={lparam:#x}")     # ← 表示しない

    @Slot(int, int)
    def on_disconnected_event(self, wparam: int, lparam: int):
        print(f"[DISCONNECTED] wp={wparam:#x} lp={lparam:#x}")
        # デバイス側から切断通知が来たときも、統一の teardown を使う
        self._disconnect_camera()

    # ==============================
    # 単枚キャプチャ / スナップショット保存
    # ==============================
    @Slot()
    def on_click_capture(self):
        # もともと動いていたかどうか記録
        was_paused = self._paused
        if not was_paused:
            self.set_paused(True)

        self.req_capture_snapshot.emit()


    @Slot(object)
    def on_snapshot_ready(self, snapshot):
        if snapshot is None:
            self._set_status("Snapshot failed.")
            return

        w, h, bits, bpl, data = (
            snapshot["w"], snapshot["h"], snapshot["bits"], snapshot["bpl"], snapshot["data"]
        )

        fmt = QImage.Format_Grayscale8 if bits == 8 else QImage.Format_Grayscale16
        img = QImage(data, w, h, bpl, fmt).copy()

        # 画面表示用に保持
        self._last_img = img
        self._render_current()  # 回転を反映した描画
        self._set_status("Snapshot captured (not saved).")        # あとは「保存ボタン」を押したときに self._last_img を保存する
            
    @Slot()
    def on_click_save(self):
        if self._last_img is None:
            self._set_status("No image to save.")
            return

        # 回転を反映
        img = self._last_img
        if self._rot_deg % 360 != 0:
            tf = QTransform().rotate(self._rot_deg)
            img = img.transformed(tf, Qt.SmoothTransformation)

        # 前回使ったフォルダを QSettings から復元（なければカレントディレクトリ）
        last_dir = self._settings.value("snapshot_last_dir", os.getcwd(), type=str)

        # ファイル保存ダイアログを表示
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save snapshot",
            os.path.join(last_dir, "snapshot.tif"),
            "TIFF (*.tif *.tiff);;PNG (*.png)"
        )
        if not path:
            self._set_status("Save canceled.")
            return

        # 選ばれたフォルダを覚えておく
        self._settings.setValue("snapshot_last_dir", os.path.dirname(path))

        self.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ext = os.path.splitext(path)[1].lower()
            if ext in (".tif", ".tiff"):
                h = img.height()
                w = img.width()
                bpl = img.bytesPerLine()
                ptr = img.bits()
                ptr.setsize(bpl * h)

                if img.format() == QImage.Format_Grayscale8:
                    arr = np.frombuffer(ptr, dtype=np.uint8).reshape(h, bpl)
                    arr = arr[:, :w]
                    tifffile.imwrite(path, arr)
                elif img.format() == QImage.Format_Grayscale16:
                    arr = np.frombuffer(ptr, dtype=np.uint16).reshape(h, bpl // 2)
                    arr = arr[:, :w]
                    tifffile.imwrite(path, arr)
                else:
                    # 想定外フォーマットは QImage 側に任せる
                    img.save(path)
            else:
                # PNG などは普通に QImage.save() に任せる
                img.save(path)

            self._set_status(f"Snapshot saved: {os.path.basename(path)}")
        finally:
            QApplication.restoreOverrideCursor()
            self.setEnabled(True)


    # ==============================
    # 録画 / Auto-stop / TIFF 保存
    # ==============================

    # 録画開始前の STEP モードで、レーザーフィルタの組み合わせをユーザーに選ばせるダイアログを出す
    def _show_step_multicolor_dialog(self):
        main = self.window()

        laser_pane = getattr(main, "laser_pane", None)
        filter_pane = getattr(main, "filter_pane", None)

        if laser_pane is None or filter_pane is None:
            raise RuntimeError("laser_pane or filter_pane not found")

        laser_choices = laser_pane.get_line_choices()
        filter_choices = filter_pane.get_filter_choices()

        if not laser_choices:
            raise RuntimeError("No connected laser lines available")
        if not filter_choices:
            raise RuntimeError("No connected filters available")

        last_n = int(self._settings.value("step_multicolor/n_colors", 1))

        #dlg1 = StepColorCountDialog(max_colors=len(laser_choices), parent=self)

        dlg1 = StepColorCountDialog(
            max_colors=len(laser_choices),
            parent=self,
            initial_value=last_n,
        )

        n_colors = dlg1.get_value()
        if n_colors is None:
            return None

        raw = self._settings.value("step_multicolor/program_json", "", type=str)
        try:
            last_program = json.loads(raw) if raw else []
        except Exception:
            last_program = []

        dlg2 = StepColorProgramDialog(
            n_colors=n_colors,
            laser_choices=laser_choices,
            filter_choices=filter_choices,
            parent=self,
            initial_program=last_program,
        )
        #return dlg2.get_program()

        program = dlg2.get_program()
        if not program:
            return None

        self._settings.setValue("step_multicolor/n_colors", n_colors)
        self._settings.setValue("step_multicolor/program_json", json.dumps(program, ensure_ascii=False))
        return program

    @Slot()
    def on_click_record(self):
        # 現在のステージモードを取得（なければ STAGE_OFF 扱い）
        mode = getattr(self, "_stage_link_mode", StageLinkMode.STAGE_OFF)

        # STAGE_OFF 以外のときだけステージを連動させる
        #stage_active = (mode != StageLinkMode.STAGE_OFF)

        if not self._is_recording:
            # ==== 録画開始 ====
            self._is_recording = True
            self.btn_record.setText("Stop")
            self.btn_record.setStyleSheet(self._style_running_red)
            #self._on_recording_state_changed(True)

            if mode == StageLinkMode.STAGE_OFF:
                if self._paused:
                    self.set_paused(False)
                    self.btn_toggle.setStyleSheet(self._style_recording_green)  # Live Viewボタンを緑
                    self._set_status("Recording to RAM…")
                try:
                    self.req_record_start_ram.emit()    # 録画スタートだけをWorkerに投げる
                    #self.stage_bridge.sig_recording_state.emit(True)    # start(test)ボタンを緑にしてる
                except Exception:
                    pass

            elif mode == StageLinkMode.MOVE_CONTINUOUS:
                if self._paused:
                    self.set_paused(False)
                    self.btn_toggle.setStyleSheet(self._style_recording_green)  # Live Viewボタンを緑
                    self._set_status("Recording to RAM…")
                try:
                    self.stage_bridge.sig_recording_state.emit(True)    # start(test)ボタンを緑にしてる
                    self.req_record_start_ram_continuous.emit()    # 録画スタート、ステージスタートをWorkerに投げる（最小ジッタ）
                except Exception:
                    pass

                """
            elif mode == StageLinkMode.STEP:
                try:
                    # STEP開始前にストリームを止める（混入防止）
                    backend = getattr(self, "backend", None)
                    if backend is not None and hasattr(backend, "stop_stream"):
                        backend.stop_stream()

                    #self.btn_toggle.setStyleSheet(self._style_recording_green)  # Live Viewボタンを緑
                    if not self._paused:
                        self.set_paused(True)
                        self.btn_toggle.setStyleSheet("")  # Live Viewボタンを緑
                    self.stage_bridge.sig_recording_state.emit(True)    # start(test)ボタンを緑にしてる
                    self.req_record_start_ram_step.emit()    # step recording startをworkerに投げる
                except Exception:
                    pass
                """

            elif mode == StageLinkMode.STEP:
                try:
                    # STEP開始前にストリームを止める
                    backend = getattr(self, "backend", None)
                    if backend is not None and hasattr(backend, "stop_stream"):
                        backend.stop_stream()

                    if not self._paused:
                        self.set_paused(True)
                        self.btn_toggle.setStyleSheet("")

                    program = self._show_step_multicolor_dialog()
                    if not program:
                        # キャンセル時は録画開始UIを元に戻す
                        self._is_recording = False
                        self.btn_record.setText("Start Recording")
                        self.btn_record.setStyleSheet("")
                        return

                    self.stage_bridge.sig_recording_state.emit(True)
                    self.req_record_start_ram_step.emit(program)

                except Exception as e:
                    print(f"[CameraPane] STEP start error: {e}")
                    self._is_recording = False
                    self.btn_record.setText("Start Recording")
                    self.btn_record.setStyleSheet("")



        else:
            #try:        #ステージstep完了フラグのデバッグ用
            #    mode = getattr(self, "_stage_link_mode", None)
            #    w = getattr(self, "worker", None)
            #    print(
            #        "[STOP]",
            #        "mode=", mode,
            #        "worker=", w,
            #        "recording=", getattr(w, "_recording", None),
            #        "step_waiting=", getattr(w, "_step_waiting", None),
            #        "step_inflight=", getattr(w, "_step_inflight", None),
            #    )
            #except Exception as e:
            #    print("[STOP] print failed:", e)

            # ==== 録画停止 ====
            self.req_record_stop_ram.emit()
            self._is_recording = False
            self.btn_record.setText("Start Recording")
            self.btn_record.setStyleSheet("")
            self.btn_toggle.setStyleSheet("")  # Live Viewボタンを戻す（step用）
            self.stage_bridge.sig_recording_state.emit(False)
            #self._on_recording_state_changed(False)

            if not self._paused:
                self.set_paused(True)

            # カメラ側は常に同じ：保存してレビューに入る
            self.blocking_save_to_tiff()
            self.enter_review_mode_ram()

            # STEP終了後：ストリーム復帰（paused=Trueのまま）
            if mode == StageLinkMode.STEP:
                backend = getattr(self, "backend", None)
                if backend is not None and hasattr(backend, "resume_stream"):
                    backend.resume_stream()

        
    @Slot()
    def _on_worker_recording_stopped(self):
        mode = getattr(self, "_stage_link_mode", StageLinkMode.STAGE_OFF)
        # ステージ連動 OFF なら何もしない
        if self.stage_bridge is None or mode == StageLinkMode.STAGE_OFF:
            return

        try:            # 将来モードごとに分岐してもよい
            self.stage_bridge.on_stage_stop()
            print(f"[CameraPane] on_worker_recording_stopped")
        except Exception as e:
            print(f"[CameraPane] on_worker_recording_stopped error: {e}")

    def blocking_save_to_tiff(self):
        if not hasattr(self, "worker"):
            self._set_status("Nothing to save.")
            return

        was_paused = self._paused
        # データ無しなら何もしない
        n = len(self.worker._ram_frames)
        #print(f"[CameraPane] blocking_save_to_tiff: RAM frames = {n}")  #デバッグ用
        if n == 0:
            self._set_status("Nothing to save.")
            return

        path, _ = QFileDialog.getSaveFileName(self, "Save buffered TIFF", "record.tif", "TIFF (*.tif *.tiff)")
        if not path:
            self._set_status("Save canceled.")
            return

        # ---- 保存モードへ：UI無効化 & カメラ停止 & 画像イベント切断 ----
        self.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)

        # 保存中は一時停止したいならここで pause だけする(画像が上書きされるかも？)
        # なんでbackendを直たたき？-----
        backend = getattr(self, "backend", None)
        if backend is not None and self.hcam:
            try:
                backend.set_paused(True)
            except Exception as e:
                print(f"[blocking_save_to_tiff] pause error: {e}")
        # -----

        # 進捗ダイアログ（モーダル）
        dlg = QProgressDialog("Saving...", None, 0, n, self)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(True)
        dlg.setValue(0)

        # ---- メインスレッドで順次書き出し（無圧縮・BigTIFF）----
        try:
            with tifffile.TiffWriter(path, bigtiff=True) as tw:
                for i, frame in enumerate(self.worker._ram_frames):
                    tw.write(frame, contiguous=True, photometric='minisblack')
                    if (i+1) % 50 == 0 or (i+1) == n:
                        dlg.setValue(i+1)
                        self._set_status(f"Saving {i+1}/{n} ({100*(i+1)/n:.1f}%)")
                        QCoreApplication.processEvents()  # ここでUIを再描画

            # ---- サイドカーのCSVを書き出し（同じフォルダに *_meta.csv）----
            base, ext = os.path.splitext(path)
            meta_path = base + "_meta.csv"
            try:
                with open(meta_path, "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["index", "seq", "camera_timestamp_us",
                                "host_monotonic_ns", "host_wall_epoch_ns", "host_wall_iso8601_utc",
                                "exposure_us"])
                    for idx, (seq, ts_us, host_ns, wall_ns, exp_us) in enumerate(self.worker._meta):
                        wall_iso = datetime.fromtimestamp(wall_ns / 1e9, tz=timezone.utc).isoformat()
                        w.writerow([idx, seq, ts_us, host_ns, wall_ns, wall_iso, exp_us])

                # ついでにドロップ総数を簡易チェック（連番の途切れ合計）
                drops = 0
                if len(self.worker._meta) >= 2:
                    for i in range(1, len(self.worker._meta)):
                        prev = self.worker._meta[i-1][0]
                        cur  = self.worker._meta[i][0]
                        if cur != prev + 1:
                            drops += (cur - (prev + 1))
                self._set_status(f"Save done. meta: {os.path.basename(meta_path)} (drops={drops})")
            except Exception as e:
                self._set_status(f"Save done, but meta save failed: {e}")

        finally:
            # 保存後に元の pause 状態に戻すだけ
            # なんでbackendを直たたき？-----
            backend = getattr(self, "backend", None)
            if backend is not None and self.hcam:
                try:
                    backend.set_paused(bool(was_paused))
                except Exception as e:
                    print(f"[blocking_save_to_tiff] resume error: {e}")
            # -----    

            QApplication.restoreOverrideCursor()
            self.setEnabled(True)

    @Slot(str)
    def on_record_status(self, s: str):
        self._set_status(s)

    @Slot(bool)
    def on_autostop_toggled(self, v: bool):
        self.spin_autostop.setEnabled(v)
        n = self.spin_autostop.value()
        self.req_set_autostop.emit(v, n)

    @Slot(int)
    def on_autostop_value_changed(self, n: int):
        self.req_set_autostop.emit(self.chk_autostop.isChecked(), n)

    @Slot(str)
    def on_worker_autostop(self, msg: str):
        # UIを停止状態に戻す
        if self._is_recording:
            self._is_recording = False
            self.btn_record.setText("Start Recording")
            self.btn_record.setStyleSheet("")  # ← ここもデフォルトに戻す

        # ★ Link stage の状態を確認
        #link_stage = self.chk_record_arm.isChecked()

        # ★ Auto-stop 時も録画終了を通知（Link stage が ON のときだけ）
        #if link_stage:
        if getattr(self, "_stage_link_mode") != StageLinkMode.STAGE_OFF:
            try:
                if self.stage_bridge is not None:
                    self.stage_bridge.sig_recording_state.emit(False)
            except Exception:
                pass

        # 手動 Stop と同じく、Live view は一度 Pause に戻す
        if not self._paused:
            self.set_paused(True)

        # 自動的に保存フローへ（手動Stopと同じ動作）
        self._set_status(msg + " Saving…")
        self.blocking_save_to_tiff()
        self.enter_review_mode_ram()

    # ==============================
    # RAM 再生 / Review モード
    # ==============================
    def enter_review_mode_ram(self):
        buf = self.worker._ram_frames
        n = len(buf)
        if n == 0:
            self._set_status("No buffered frames."); return
        self._ram_view = buf                      # 参照のみ（ゼロコピー）
        self._ram_meta = list(self.worker._meta)  # メタは固定長のlist化
        if len(self._ram_meta) == n:
            t0 = self._ram_meta[0][1]
            self._times_ms = [(m[1]-t0)/1000.0 for m in self._ram_meta]
        else:
            self._times_ms = None
        self.slider.setRange(0, n-1)
        self.slider.setEnabled(True)
        self.btn_play.setEnabled(True)
        self.slider.setValue(0)
        self._show_frame_index(0)
        self._set_status(f"RAM review: {n} frames (kept in memory)")

    def _qimage_from_ndarray(self, arr: np.ndarray) -> QImage:
        h, w = arr.shape
        if arr.dtype == np.uint8:
            img = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
        elif arr.dtype == np.uint16:
            img = QImage(arr.data, w, h, w*2, QImage.Format_Grayscale16)
        else:
            raise ValueError(f"unsupported dtype: {arr.dtype}")
        return img.copy()  # 安全のためコピー

    def _show_frame_index(self, i: int):
        # RAM優先→ファイル
        if self._ram_view is not None and len(self._ram_view) > 0:
            n = len(self._ram_view)
            i = max(0, min(i, n-1))
            frame = self._ram_view[i]
        elif self._stack is not None:
            n = self._stack.shape[0]
            i = max(0, min(i, n-1))
            frame = self._stack[i]
        else:
            return
        # ここから：回転ルートを統一
        img = self._qimage_from_ndarray(frame)
        self._last_img = img                 # ← 「元画像」を保持
        self._render_current()               # ← 現在の回転角 self._rot_deg で描画
        self._update_time_label(i)

    def _update_time_label(self, i: int):
        # 総フレーム数を取得
        if self._ram_view is not None and len(self._ram_view) > 0:
            n = len(self._ram_view)
        elif self._stack is not None:
            n = self._stack.shape[0]
        else:
            self.lbl_time.setText("0 / 0 frames")
            return

        # i は 0 始まりなので +1 して表示
        self.lbl_time.setText(f"{i+1} / {n} frames")

    @Slot()
    def _on_play_tick(self):
        # 固定fps（デフォルト30fps）
        if self._ram_view is not None and len(self._ram_view) > 0:
            n = len(self._ram_view)
        elif self._stack is not None:
            n = self._stack.shape[0]
        else:
            self.play_timer.stop()
            self.btn_play.setText("Play")
            return

        i = self.slider.value() + 1
        if i >= n:
            self.play_timer.stop()
            self.btn_play.setText("Play")
            return

        self.slider.blockSignals(True)
        self.slider.setValue(i)
        self.slider.blockSignals(False)
        self._show_frame_index(i)

    @Slot()
    def _on_play_tick_variable(self):
        # メタの時刻間隔に合わせて可変再生（_times_ms がある場合に使用）
        if self._ram_view is not None and len(self._ram_view) > 0:
            n = len(self._ram_view)
        elif self._stack is not None:
            n = self._stack.shape[0]
        else:
            self._on_play_tick()
            return

        i = self.slider.value()
        if i >= n-1:
            self.play_timer.stop()
            self.btn_play.setText("Play")
            return

        if self._times_ms is None or len(self._times_ms) != n:
            self._on_play_tick()
            return

        dt_ms = max(1, int(round(self._times_ms[i+1] - self._times_ms[i])))
        self.play_timer.setInterval(dt_ms)

        self.slider.blockSignals(True)
        self.slider.setValue(i+1)
        self.slider.blockSignals(False)
        self._show_frame_index(i+1)

    @Slot()
    def _on_click_play(self):
        # 再生/一時停止切替。時刻があるなら可変、無いなら固定fps
        if self._ram_view is None and self._stack is None:
            return
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.btn_play.setText("Play")
            return

        # 可変 or 固定を接続し直す
        try:
            self.play_timer.timeout.disconnect()
        except Exception:
            pass

        if (self._ram_view is not None and len(self._ram_view) > 0 and
            self._times_ms is not None and len(self._times_ms) == len(self._ram_view)):
            self.play_timer.timeout.connect(self._on_play_tick_variable)
        elif (self._stack is not None and
            self._times_ms is not None and self._stack is not None and
            len(self._times_ms) == self._stack.shape[0]):
            self.play_timer.timeout.connect(self._on_play_tick_variable)
        else:
            self.play_timer.timeout.connect(self._on_play_tick)
            self.play_timer.setInterval(int(1000/30))

        self.play_timer.start()
        self.btn_play.setText("Pause")

    @Slot(int)
    def _on_slider_changed(self, v: int):
        self._show_frame_index(v)

    # ==============================
    # 表示 / 回転 / ROI
    # ==============================
    def _render_current(self):
        if self._last_img is None:
            return
        # 回転
        tf = QTransform().rotate(self._rot_deg)
        img_rot = self._last_img.transformed(tf, Qt.SmoothTransformation)
        # ラベルの描画領域にフィット
        target_sz = self.label.contentsRect().size()
        if not target_sz.isValid():
            return
        self.label.set_image(img_rot)

    @Slot()
    def _rotate_left(self):
        self._rot_deg = (self._rot_deg - 90) % 360
        self._render_current()

    @Slot()
    def _rotate_right(self):
        self._rot_deg = (self._rot_deg + 90) % 360
        self._render_current()

    @Slot(object)
    def on_frame_ready(self, frame):
        w, h, bits, bpl, data = frame["w"], frame["h"], frame["bits"], frame["bpl"], frame["data"]
        fmt = QImage.Format_Grayscale8 if bits == 8 else QImage.Format_Grayscale16
        self._last_img = QImage(data, w, h, bpl, fmt).copy()  # 元画像を保持
        self._render_current()
        if not self._paused:
            self._set_status("Running")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render_current()

    def _snap_roi(self, x, y, w, h):
        # 仕様: 位置2px単位, サイズ4px単位, 最小16x16
        x = (x // 2) * 2
        y = (y // 2) * 2
        w = max(16, (w // 4) * 4)
        h = max(16, (h // 4) * 4)
        return x, y, w, h

    @Slot()
    def on_set_roi(self):
        # 回転していたら0°に戻す（ズレ防止）
        if self._rot_deg != 0:  
            self._rot_deg = 0
            self._render_current()
            self._set_status("ROI設定: 表示回転を0°に戻しました")
        """ROI編集を有効化"""
        self.label.enable_edit(True)
        self.set_paused(True)
        self._set_status("ROI設定モード")

    @Slot()
    def on_apply_roi(self):
        """ROIをSDKに適用"""
        if not self.hcam:
            return

        # 処理前の Pause 状態を保存
        prev_paused = self._paused

        x, y, w, h = self.label.get_roi()
        x, y, w, h = self._snap_roi(x, y, w, h)
        print(f"Apply ROI: ({x},{y},{w},{h})")

        # --- デバイス側の処理は backend に任せる ---
        self.backend.set_roi(x, y, w, h)

        # --- UI 更新 ---
        self.label.clear_roi()
        self.label.enable_edit(False)
        self._current_roi = (x, y, w, h)
        self._set_roi_text(self._current_roi)
        self._set_status(f"ROI applied: {x},{y},{w},{h}")

        # 処理前の Live/Pause 状態に戻す
        self.set_paused(prev_paused)

    @Slot()
    def on_reset_roi(self):
        """ROIをフルフレームに戻す（処理は backend 側に任せる）"""
        if not self.hcam or not hasattr(self, "backend"):
            return

        # 処理前の Pause 状態を保存
        prev_paused = self._paused

        # UI から現在の解像度インデックスを取得
        res_idx = self.ctrl_res.currentData()
        if res_idx is None:
            self._set_status("Resolution index not found.")
            return

        # --- backend 経由でフルフレームのサイズを取得 ---
        full_w, full_h = self.backend.get_full_frame_size(res_idx)
        if full_w <= 0 or full_h <= 0:
            self._set_status("Failed to get full-frame size.")
            return

        # --- デバイス側 ROI リセットは backend に任せる ---
        self.backend.reset_roi(full_w, full_h)

        # --- GUI更新 ---
        self.label.clear_roi()
        self.label.enable_edit(False)
        self._current_roi = None
        self._set_roi_text(None)
        self._set_status(f"ROI reset (FULL {full_w}x{full_h})")

        # 処理前の Live/Pause 状態に戻す
        self.set_paused(prev_paused)

    @Slot(int, int, int, int)
    def on_roi_changed(self, x, y, w, h):
        """ROI矩形が動いたらステータスに表示"""
        self._set_status(f"ROI: {x},{y},{w},{h}")

    def _set_roi_text(self, roi):
        """roi=(x,y,w,h) or None(FULL) を表示"""
        if roi is None:
            self.roi_label.setText("ROI: FULL")
        else:
            x, y, w, h = roi
            self.roi_label.setText(f"ROI: ({x}, {y}, {w}, {h})")
