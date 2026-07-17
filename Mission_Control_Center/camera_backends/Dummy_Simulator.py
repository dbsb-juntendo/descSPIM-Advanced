# camera_backends/Dummy_Simulator.py
# -*- coding: utf-8 -*-
# Copyright © 2026 Kiyotada Naitou
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0


from __future__ import annotations

import numpy as np
import time
from typing import Optional, Any
from PySide6.QtCore import QObject, Signal, QTimer, Qt

from camera_backends.camera_backend_base import ICameraBackend


class DummySimulatorBackend(ICameraBackend):
    """
    実機なしで descSPIM-Fullmoon を完全動作させるダミーカメラ。

    特徴：
    - 640x480 のグレースケール画像を 30fps で生成する
    - gain/exposure は画像の輝度に反映
    - ROI / 解像度 / ビット深度 も一応動く
    - WinMsg 不使用（QTimer 制御）
    """

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._pane = parent
        self._worker = None

        # ダミー用パラメータ
        self._w = 640
        self._h = 480
        self._bits = 8      # 8-bit or 16-bit
        self._bpl = self._w * 1
        self._size = self._w * self._h

        self._gain = 100
        self._expo_ms = 10.0

        # ROI（None = full）
        self._roi = None    # (x, y, w, h)

        # timer ベースでフレーム生成
        self._timer = None
        self._seq = 0

    # -------------------------------------------------------------------------
    # backend API 必須メソッド
    # -------------------------------------------------------------------------
    def connect(self) -> bool:
        print("[DummySimulator] connect() OK")
        return True

    def disconnect(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
        self._timer = None
        print("[DummySimulator] disconnect() finished")

    def set_paused(self, paused: bool) -> None:
        if self._timer is None:
            return
        if paused:
            self._timer.stop()
        else:
            self._timer.start()

    def start_stream(self, hwnd: int) -> None:
        """
        LiveView 開始。WinMsg 不使用、QTimer で 30fps 生成。
        """
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setInterval(int(1000/30))  # 30fps
            self._timer.timeout.connect(self._on_timer_frame)

        self._seq = 0
        self._timer.start()
        print("[DummySimulator] streaming started")

    # -------------------------------------------------------------------------
    # フレーム生成
    # -------------------------------------------------------------------------
    def _on_timer_frame(self):
        """ダミー画像を生成して worker → CameraPane に流す"""
        if self._worker is None:
            return

        self._seq += 1
        ts_us = int(time.time() * 1e6)

        # 画像生成（シンプルなグラデーション + 動くバー）
        y, x = np.mgrid[0:self._h, 0:self._w]
        frame = ((x + (self._seq % self._w)) % 256).astype(np.uint8)

        # gain/expo を輝度に反映（適当なスケーリング）
        frame = np.clip(frame * (self._gain / 100.0), 0, 255).astype(np.uint8)

        # ROI を適用（あえて画像サイズは変えず、ROI外は黒で）
        if self._roi is not None:
            x0, y0, rw, rh = self._roi
            mask = np.zeros_like(frame)
            mask[y0:y0+rh, x0:x0+rw] = frame[y0:y0+rh, x0:x0+rw]
            frame = mask

        # worker が pull_frame_into_buffer を呼ぶ構造なので
        # backend 側は frame を保持して返すだけにする
        self._last_frame = frame
        self._last_ts = ts_us

        # worker 側へ通知（Nikon/Thorlabs の sig_image 相当）
        self.sig_image.emit(1, 0)

    # -------------------------------------------------------------------------
    # worker が呼ぶ pull_frame_into_buffer
    # -------------------------------------------------------------------------
    def pull_frame_into_buffer(self, buf, size, bits: int):
        """
        worker が pull_frame... を呼んだら、保持しているダミーフレームを返す。
        """
        if not hasattr(self, "_last_frame"):
            return None

        arr = self._last_frame
        h, w = arr.shape
        bpl = w * 1
        data = arr.tobytes()

        return {
            "w": w,
            "h": h,
            "bits": 8,
            "bpl": bpl,
            "data": data,
            "seq": self._seq,
            "ts_us": self._last_ts,
            "exp_us": int(self._expo_ms * 1000),
        }

    # -------------------------------------------------------------------------
    # 初期パラメータ取得
    # -------------------------------------------------------------------------
    def query_params(self, bits: int):
        w, h = self._w, self._h
        bpl = w * 1
        size = w * h
        return (w, h, bits, bpl, size)

    def get_current_bit_depth(self) -> int:
        return self._bits

    # -------------------------------------------------------------------------
    # UI の populate
    # -------------------------------------------------------------------------
    def populate_controls(self, pane):
        # 解像度：ダミーで 640x480 だけ
        pane.ctrl_res.clear()
        pane.ctrl_res.addItem("640 x 480", 0)

        pane.ctrl_gain.setValue(self._gain)
        pane.ctrl_expo.setValue(self._expo_ms)

        print("[DummySimulator] populate_controls finished")

    # -------------------------------------------------------------------------
    # Gain / Exposure
    # -------------------------------------------------------------------------
    def apply_gain_expo(self, gain: int, expo_ms: float):
        self._gain = gain
        self._expo_ms = expo_ms
        print(f"[DummySimulator] gain={gain}, expo={expo_ms} ms applied")

    # -------------------------------------------------------------------------
    # Resolution / Bit Depth
    # -------------------------------------------------------------------------
    def apply_res_bit(self, res_index: int, bit_index: int):
        # 特に何もしない（1解像度のみ）
        self._bits = 8 if bit_index == 0 else 16
        print(f"[DummySimulator] bit depth set to {self._bits}")

    # -------------------------------------------------------------------------
    # ROI
    # -------------------------------------------------------------------------
    def set_roi(self, x: int, y: int, w: int, h: int):
        self._roi = (x, y, w, h)
        print(f"[DummySimulator] ROI set to ({x},{y},{w},{h})")

    def reset_roi(self, full_width: int, full_height: int):
        self._roi = None
        print("[DummySimulator] ROI reset to FULL")

    def get_full_frame_size(self, res_index: int | None):
        return (self._w, self._h)


# CameraPane が自動検出するためのファクトリ
def get_backend_class():
    return DummySimulatorBackend
