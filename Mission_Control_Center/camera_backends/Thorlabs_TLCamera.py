# camera_backends/Thorlabs_TLCamera.py
# -*- coding: utf-8 -*-
# Copyright © 2026 Kiyotada Naitou
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0


from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Any
import time

from PySide6.QtCore import QObject, Signal, Qt, QTimer

from .camera_backend_base import ICameraBackend

import numpy as np

# Optional SDK symbols are intentionally loaded only when the user connects this
# backend.  camera_integration.scan_camera_backends() imports every backend at
# application startup, so importing the vendor SDK here would make optional
# hardware a startup dependency.
TLCameraSDK = None
OPERATION_MODE = None
ROI = None
_TSI_DLL_DIRECTORY_HANDLE = None


def _load_thorlabs_sdk() -> None:
    """Prepare the native runtime and import the optional Thorlabs SDK lazily."""
    global TLCameraSDK, OPERATION_MODE, ROI, _TSI_DLL_DIRECTORY_HANDLE

    if TLCameraSDK is not None and OPERATION_MODE is not None and ROI is not None:
        return

    if os.name != "nt":
        raise RuntimeError("The Thorlabs TSI camera backend requires Windows.")
    if sys.maxsize <= 2**32:
        raise RuntimeError("The MCC installation requires 64-bit Python.")

    dll_directory = Path(__file__).resolve().parents[1] / "dlls" / "64_lib"
    if not dll_directory.is_dir():
        raise RuntimeError(
            "Thorlabs native DLL directory not found: "
            f"{dll_directory}. Follow the installation manual and copy the "
            "64-bit Native Toolkit DLLs to MCC\\dlls\\64_lib."
        )
    if not any(dll_directory.glob("*.dll")):
        raise RuntimeError(f"No Thorlabs native DLLs found in: {dll_directory}")

    dll_directory_text = str(dll_directory)
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    if dll_directory_text not in path_entries:
        os.environ["PATH"] = dll_directory_text + os.pathsep + os.environ.get("PATH", "")

    # Keep the returned handle alive for as long as the imported SDK can need
    # this search directory. Closing or releasing it removes the registration.
    dll_handle = os.add_dll_directory(dll_directory_text)
    try:
        from thorlabs_tsi_sdk.tl_camera import (
            OPERATION_MODE as _OPERATION_MODE,
            ROI as _ROI,
            TLCameraSDK as _TLCameraSDK,
        )
    except Exception:
        dll_handle.close()
        raise

    _TSI_DLL_DIRECTORY_HANDLE = dll_handle
    TLCameraSDK = _TLCameraSDK
    OPERATION_MODE = _OPERATION_MODE
    ROI = _ROI


class ThorlabsTLCameraBackend(ICameraBackend):
    """
    Thorlabs TSI カメラ (Zelux / Kiralux / Quantalux など) 用 backend。

    - NikonDS50MBackend と同じインターフェースで CameraPane / CaptureWorker に接続する
    - 画像イベントは Win32 メッセージではなく、QTimer でポーリングして擬似的に発火させる
    """

    # Nikon とインターフェースを合わせるためのシグナル定義
    sig_event = Signal(int, int)
    sig_image = Signal(int, int)
    sig_error = Signal(int, int)
    sig_disconnected = Signal(int, int)
    sig_frame = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pane: Any = parent          # CameraPane
        self._worker: Any = None          # CaptureWorker

        self._sdk: Any | None = None
        self._cam: Any = None             # 実際の TLCamera インスタンス

        self._width: int = 0
        self._height: int = 0
        self._bit_depth: int = 8
        self._bytes_per_pixel: int = 1
        self._bpl: int = 0

        # 追加: gain / exposure のレンジキャッシュ
        self._gain_min: float | None = None
        self._gain_max: float | None = None
        self._expo_min_ms: float | None = None
        self._expo_max_ms: float | None = None

        self._paused: bool = True
        self._seq_fallback: int = 0

        # 表示は常に 8bit に固定
        self._display_bits: int = 8

        # ポーリング用タイマー（擬似「IMAGE イベント」）
        self._timer = QTimer()
        self._timer.setInterval(50)  # ≒30fps
        self._timer.timeout.connect(self._on_timer)

    # -------------------------------------------------
    # Nikon と同じ「イベント名返し」だが、Thorlabs では特に使わない
    # -------------------------------------------------
    def describe_event(self, wparam: int) -> str:
        return ""

    # -------------------------------------------------
    # Worker 接続
    # -------------------------------------------------
    def attach_worker(self, worker: Any) -> None:
        """
        CaptureWorker.sig_frame_ready → backend.sig_frame → CameraPane.on_frame_ready
        の流れを作る。
        """
        self._worker = worker
        try:
            worker.sig_frame_ready.connect(self.sig_frame, Qt.QueuedConnection)
        except Exception:
            pass

    # -------------------------------------------------
    # connect / disconnect
    # -------------------------------------------------
    def _update_ranges_from_camera(self) -> None:
        """
        SDK から gain / exposure のレンジを一度だけ読み出してキャッシュする。
        """
        if self._cam is None:
            return

        # --- gain range ---
        try:
            g = self._cam.gain_range
            # すでにコード内で (min_gain, max_gain) = gain_range を想定しているので
            # タプルとみなしておく
            self._gain_min, self._gain_max = float(g[0]), float(g[1])
            print(f"[ThorlabsTLCameraBackend] gain_range = {self._gain_min} .. {self._gain_max}")
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] get gain_range failed: {e}")
            self._gain_min = self._gain_max = None

        # --- exposure range (us) → ms ---
        try:
            r = self._cam.exposure_time_range_us
            # SDK のバージョンによって Range(min,max) or タプルの可能性があるので両方対応
            if hasattr(r, "min") and hasattr(r, "max"):
                emin_us = float(r.min)
                emax_us = float(r.max)
            else:
                emin_us = float(r[0])
                emax_us = float(r[1])

            self._expo_min_ms = emin_us / 1000.0
            self._expo_max_ms = emax_us / 1000.0
            print(f"[ThorlabsTLCameraBackend] exposure_time_range = {self._expo_min_ms} .. {self._expo_max_ms} ms")
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] get exposure_time_range_us failed: {e}")
            self._expo_min_ms = self._expo_max_ms = None


    def connect(self) -> bool:
        """
        Connect Camera ボタンから呼ばれる。

        - Thorlabs SDK でカメラを open
        - pane.hcam にダミーのハンドル（True）を入れる
        - pane._init_camera_ui() を呼んで Worker などを立ち上げる
        """
        pane = self._pane
        if pane is None:
            return False

        try:
            _load_thorlabs_sdk()
        except Exception as e:
            message = f"Thorlabs camera runtime could not be loaded: {e}"
            print(f"[ThorlabsTLCameraBackend] {message}")
            try:
                if hasattr(pane, "_set_status"):
                    pane._set_status(message)
                elif hasattr(pane, "lbl_status"):
                    pane.lbl_status.setText(message)
            except Exception:
                pass
            return False

        assert TLCameraSDK is not None

        # すでに接続済みなら何もしない
        if getattr(pane, "hcam", None):
            return True

        try:
            self._sdk = TLCameraSDK()
            serials = self._sdk.discover_available_cameras()
            if not serials:
                print("[ThorlabsTLCameraBackend] カメラが検出されません。")
                self._sdk.dispose()
                self._sdk = None
                return False

            serial = serials[0]
            print(f"[ThorlabsTLCameraBackend] open_camera({serial})")
            self._cam = self._sdk.open_camera(serial)
            # 追加: レンジを一度読んでキャッシュ
            self._update_ranges_from_camera()

            """
            # デバッグ用情報出力
            try:
                print("===== dir(self._cam) =====")
                import pprint
                pprint.pp(dir(self._cam))
                print("===== end dir(self._cam) =====")
            except Exception as e:
                print(f"[ThorlabsTLCameraBackend] dir(self._cam) failed: {e}")

            try:
                print("===== Thorlabs camera parameters =====")
                print("model:", self._cam.model)
                print("sensor_width x height:", self._cam.sensor_width_pixels, "x", self._cam.sensor_height_pixels)
                print("image_width_range_pixels:", self._cam.image_width_range_pixels)
                print("image_height_range_pixels:", self._cam.image_height_range_pixels)
                print("binx_range:", self._cam.binx_range)
                print("biny_range:", self._cam.biny_range)
                print("roi:", self._cam.roi)
                print("roi_range:", self._cam.roi_range)
                print("======================================")
            except Exception as e:
                print(f"[ThorlabsTLCameraBackend] print params failed: {e}")
            """

            # === 基本設定（例に合わせる） ===
            try:
                if OPERATION_MODE is not None:
                    self._cam.operation_mode = OPERATION_MODE.SOFTWARE_TRIGGERED
                # 連続モード
                self._cam.frames_per_trigger_zero_for_unlimited = 0
                # ポーリングのタイムアウト
                self._cam.image_poll_timeout_ms = 1000
                # 必要ならフレームレート制御（任意）
                # self._cam.frame_rate_control_value = 10
                # self._cam.is_frame_rate_control_enabled = True
            except Exception as e:
                print(f"[ThorlabsTLCameraBackend] initial camera config error: {e}")


            # 基本情報
            self._width = int(self._cam.image_width_pixels)
            self._height = int(self._cam.image_height_pixels)
            self._bit_depth = int(self._cam.bit_depth)
            self._bytes_per_pixel = (self._bit_depth + 7) // 8
            self._bpl = self._width * self._bytes_per_pixel

            # CameraPane 側には「ハンドルあり」と認識させればよいので
            # 実ハンドルである必要はない（True で十分）
            pane.hcam = True

            # UI / worker セットアップ
            try:
                pane._init_camera_ui()
            except Exception as e:
                import traceback
                print("[ThorlabsTLCameraBackend] _init_camera_ui error:", e)
                traceback.print_exc()
                # 失敗したらクリーンアップ
                self.disconnect()
                pane.hcam = None
                return False

            return True

        except Exception as e:
            import traceback
            print(f"[ThorlabsTLCameraBackend] connect() failed: {e}")
            traceback.print_exc()
            self.disconnect()
            if pane is not None:
                pane.hcam = None
            return False

    def disconnect(self) -> None:
        """
        カメラとの接続を閉じる。
        """
        # タイマー停止
        if self._timer.isActive():
            self._timer.stop()

        # カメラ / SDK を解放
        if self._cam is not None:
            try:
                try:
                    # armed の場合 disarm
                    if hasattr(self._cam, "disarm"):
                        self._cam.disarm()
                except Exception:
                    pass
                try:
                    if hasattr(self._cam, "dispose"):
                        self._cam.dispose()
                    elif hasattr(self._cam, "close"):
                        self._cam.close()
                except Exception:
                    pass
            finally:
                self._cam = None

        if self._sdk is not None:
            try:
                self._sdk.dispose()
            except Exception:
                pass
            finally:
                self._sdk = None

        pane = self._pane
        if pane is not None and hasattr(pane, "hcam"):
            pane.hcam = None

        print("[ThorlabsTLCameraBackend] Camera disconnect sequence finished.")

    # -------------------------------------------------
    # stream / pause
    # -------------------------------------------------

    def start_stream(self, hwnd: int):
        if self._cam is None:
            print("[ThorlabsTLCameraBackend] start_stream: _cam is None")
            return

        # 連続撮影モード（trigger は arm/trigger の設定だけにする）
        self._cam.frames_per_trigger_zero_for_unlimited = 0
        self._cam.image_poll_timeout_ms = 1000  # 1 s timeout

        # 念のためログ
        print("[ThorlabsTLCameraBackend] start_stream: "
              f"frames_per_trigger_zero_for_unlimited={self._cam.frames_per_trigger_zero_for_unlimited}, "
              f"bit_depth={self._cam.bit_depth}")

        # software trigger モードで arm
        self._cam.arm(2)
        print("[ThorlabsTLCameraBackend] arm(2) done, is_armed =", self._cam.is_armed)

        # ★最初の 1 回だけ trigger（あとは必要に応じて GUI 側から呼ぶ）
        self._cam.issue_software_trigger()
        print("[ThorlabsTLCameraBackend] first issue_software_trigger()")

        self._paused = True
        self._timer.start()
        print("[ThorlabsTLCameraBackend] start_stream OK (timer started, paused=True)")

    def set_paused(self, paused: bool) -> None:
        """
        Pause/Resume 状態をフラグで保持。
        Pause→Run に変わったときに 1 回だけソフトウェアトリガを投げる。
        """
        prev = self._paused
        self._paused = bool(paused)
        print(f"[ThorlabsTLCameraBackend] paused={self._paused}")

        if self._cam is None:
            return

        # Pause → Run に切り替わった瞬間に 1 回トリガ
        if prev and not self._paused:
            try:
                print("[ThorlabsTLCameraBackend] issue_software_trigger()")
                self._cam.issue_software_trigger()
            except Exception as e:
                print(f"[ThorlabsTLCameraBackend] issue_software_trigger failed: {e}")



    # -------------------------------------------------
    # stream control (STEP用: stop/resume)
    # -------------------------------------------------
    def stop_stream(self) -> None:
        """
        STEP開始時に呼ぶ想定。
        - QTimer を止める（擬似IMAGEイベント停止）
        - paused=True にする（pull_frame_into_buffer を止める）
        - armed なら disarm
        """
        # 1) タイマー停止
        try:
            if self._timer.isActive():
                self._timer.stop()
        except Exception:
            pass

        # 2) paused フラグ
        self._paused = True

        # 3) disarm
        if self._cam is None:
            return
        try:
            if getattr(self._cam, "is_armed", False):
                self._cam.disarm()
                print("[ThorlabsTLCameraBackend] stop_stream: disarm done")
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] stop_stream: disarm failed: {e}")

    def resume_stream(self) -> None:
        """
        STEP終了時に呼ぶ想定。
        - arm（未armedなら）
        - QTimer を再開（pausedは True のままにしておく：勝手にtriggerしない）
        """
        if self._cam is None:
            return

        # 1) arm（未armedなら）
        try:
            if not getattr(self._cam, "is_armed", False):
                # start_stream と同じ設定に寄せる
                self._cam.frames_per_trigger_zero_for_unlimited = 0
                self._cam.image_poll_timeout_ms = 1000
                self._cam.arm(2)
                print("[ThorlabsTLCameraBackend] resume_stream: arm(2) done")
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] resume_stream: arm failed: {e}")
            return

        # 2) paused は True のまま（＝勝手にstream流さない/triggerしない）
        self._paused = True

        # 3) タイマー再開（paused=Trueなので _on_timer は何もしない）
        try:
            if not self._timer.isActive():
                self._timer.start()
                print("[ThorlabsTLCameraBackend] resume_stream: timer started (paused=True)")
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] resume_stream: timer start failed: {e}")



    # -------------------------------------------------
    # UI 初期化
    # -------------------------------------------------
    def populate_controls(self, pane: Any) -> None:
        """
        SDK から現在値を読み出して UI を初期化。
        Thorlabs では:
          - ビット深度コンボは「8-bit」固定扱い
          - 解像度コンボ(ctrl_res)は「ビニングプリセット」を入れる
        """
        if self._cam is None:
            return

        # ----- bit depth UI -----
        try:
            if hasattr(pane, "ctrl_bit"):
                # 表示は 8-bit 固定として扱う（実データは 12bit→16bit で扱っている）
                pane.ctrl_bit.setCurrentIndex(0)
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] populate_controls bit UI error: {e}")

        # ----- exposure range を UI に反映 -----
        try:
            if hasattr(pane, "ctrl_expo") and self._expo_min_ms is not None:
                # 露光時間 [ms] の範囲を SDK に合わせる
                pane.ctrl_expo.setRange(self._expo_min_ms, self._expo_max_ms)
                print(f"[ThorlabsTLCameraBackend] set ctrl_expo range to "
                      f"{self._expo_min_ms} .. {self._expo_max_ms} ms")
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] populate_controls expo UI error: {e}")

        # ----- resolution (= binning presets) -----
        try:
            if hasattr(pane, "ctrl_res"):
                pane.ctrl_res.clear()

                # SDK が許すビニング範囲を取得
                bx_range = self._cam.binx_range  # Range(min=1, max=16)
                by_range = self._cam.biny_range

                def clamp_bin(v, r):
                    return max(r.min, min(r.max, v))

                presets = [
                    ("Full, 1x1 bin", {"binx": 1, "biny": 1}),
                    ("Full, 2x2 bin", {"binx": 2, "biny": 2}),
                    ("Full, 4x4 bin", {"binx": 4, "biny": 4}),
                ]

                count = 0
                for label, cfg in presets:
                    bx = clamp_bin(cfg["binx"], bx_range)
                    by = clamp_bin(cfg["biny"], by_range)
                    cfg["binx"] = bx
                    cfg["biny"] = by
                    pane.ctrl_res.addItem(label, cfg)
                    count += 1

                if count > 0:
                    pane.ctrl_res.setCurrentIndex(0)

        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] populate_controls res UI error: {e}")

    # -------------------------------------------------
    # Gain / Exposure
    # -------------------------------------------------
    def apply_gain_expo(self, gain: int, expo_ms: float) -> None:
        if self._cam is None:
            return

        # --- exposure ---
        try:
            self._cam.exposure_time_us = int(expo_ms * 1000.0)
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] Failed to set exposure: {e}")

        # --- gain (Kiralux) ---
        # Kiralux の gain は 0〜最大値（通常 0〜48）
        try:
            min_gain, max_gain = self._cam.gain_range  # 例: (0, 48)
            # GUI の gain(=0〜4000) を 0〜max_gain に線形マップ
            mapped = int((gain / 4000) * max_gain)
            mapped = max(min_gain, min(mapped, max_gain))
            self._cam.gain = mapped
            print(f"[ThorlabsTLCameraBackend] set gain = {mapped} (raw={gain})")
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] Failed to set gain: {e}")

        print(f"[ThorlabsTLCameraBackend] apply_gain_expo done.")


    # -------------------------------------------------
    # Resolution / BitDepth
    # -------------------------------------------------
    def apply_res_bit(self, res_index: int, bit_index: int) -> None:
        """
        解像度(res_index)とビット深度(bit_index)を
        Thorlabs SDK に反映。
        ここでは:
          - res_index は populate_controls で仕込んだ dict (binx/biny) を想定
          - bit_index は無視して「表示は 8-bit 固定」とする
        """
        if self._cam is None:
            return

        # --- bit depth は Thorlabs では変更不可なので無視する ---
        if bit_index not in (0, None):
            msg = "Thorlabs camera: 16-bit display mode is not implemented (always handled as 8-bit display)."
            print(f"[ThorlabsTLCameraBackend] {msg}")
            # 可能ならステータスバーにも出す（失敗しても無視）
            pane = self._pane
            try:
                if pane is not None and hasattr(pane, "_set_status"):
                    pane._set_status(msg)
                elif pane is not None and hasattr(pane, "lbl_status"):
                    pane.lbl_status.setText(msg)
            except Exception:
                pass
            # 処理自体は 8bit 前提で続行する

        preset = res_index
        if not isinstance(preset, dict):
            # 予期しない値が来たときのフォールバック
            preset = {"binx": 1, "biny": 1}

        bx = int(preset.get("binx", 1))
        by = int(preset.get("biny", 1))

        try:
            bx_range = self._cam.binx_range
            by_range = self._cam.biny_range

            bx = max(bx_range.min, min(bx_range.max, bx))
            by = max(by_range.min, min(by_range.max, by))

            # （以下は元のコードそのまま）
            was_armed = False
            try:
                was_armed = bool(self._cam.is_armed)
            except Exception:
                pass

            if was_armed:
                try:
                    self._cam.disarm()
                except Exception:
                    pass

            self._cam.binx = bx
            self._cam.biny = by

            print(f"[ThorlabsTLCameraBackend] set binning to {bx}x{by}")

            try:
                self._cam.arm(2)
                self._cam.issue_software_trigger()
            except Exception as e:
                print(f"[ThorlabsTLCameraBackend] re-arm after binning failed: {e}")

            try:
                self._width = int(self._cam.image_width_pixels)
                self._height = int(self._cam.image_height_pixels)
            except Exception:
                pass

            worker = getattr(self._pane, "worker", None)
            if worker is not None:
                worker.reconfigure()

        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] apply_res_bit error: {e}")


    # -------------------------------------------------
    # ROI
    # -------------------------------------------------
    def set_roi(self, x: int, y: int, w: int, h: int) -> None:
        if self._cam is None or ROI is None:
            return

        try:
            rng = getattr(self._cam, "roi_range", None)
            sensor_w = int(self._cam.sensor_width_pixels)
            sensor_h = int(self._cam.sensor_height_pixels)

            # GUI からの (x, y, w, h) → UL/LR
            ulx = int(x)
            uly = int(y)
            lrx = int(x + w - 1)
            lry = int(y + h - 1)

            # センサ範囲でクリップ
            ulx = max(0, min(ulx, sensor_w - 1))
            uly = max(0, min(uly, sensor_h - 1))
            lrx = max(ulx + 1, min(lrx, sensor_w - 1))
            lry = max(uly + 1, min(lry, sensor_h - 1))

            # roi_range があれば、さらにその範囲にもクリップ
            if rng is not None:
                ulx = max(rng.upper_left_x_pixels_min,
                        min(ulx, rng.upper_left_x_pixels_max))
                uly = max(rng.upper_left_y_pixels_min,
                        min(uly, rng.upper_left_y_pixels_max))
                lrx = max(rng.lower_right_x_pixels_min,
                        min(lrx, rng.lower_right_x_pixels_max))
                lry = max(rng.lower_right_y_pixels_min,
                        min(lry, rng.lower_right_y_pixels_max))

            print(f"[ThorlabsTLCameraBackend] set_roi -> "
                f"({ulx},{uly})-({lrx},{lry})")

            # ROI 変更前の状態を記録
            was_armed = False
            try:
                was_armed = bool(self._cam.is_armed)
            except Exception:
                pass

            was_paused = self._paused

            # armed なら一旦 disarm
            if was_armed:
                try:
                    self._cam.disarm()
                except Exception:
                    pass

            # ROI 設定
            self._cam.roi = ROI(
                upper_left_x_pixels=ulx,
                upper_left_y_pixels=uly,
                lower_right_x_pixels=lrx,
                lower_right_y_pixels=lry,
            )

            # ここでは frames_per_trigger_zero_for_unlimited を 0 に固定
            # （start_stream と同じモードにする）
            self._cam.frames_per_trigger_zero_for_unlimited = 0
            self._cam.image_poll_timeout_ms = 1000

            # ROI 変更後に再 arm
            self._cam.arm(2)

            # 幅・高さキャッシュ更新
            self._width = int(self._cam.image_width_pixels)
            self._height = int(self._cam.image_height_pixels)

            # Worker 側バッファ再構成
            pane = self._pane
            worker = getattr(pane, "worker", None) if pane is not None else None
            if worker is not None:
                worker.reconfigure()

            # もし ROI 変更前に「走っていた」場合は、arm 後に 1 回だけ trigger
            if not was_paused:
                try:
                    self._cam.issue_software_trigger()
                except Exception as e:
                    print(f"[ThorlabsTLCameraBackend] issue_software_trigger after ROI failed: {e}")

        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] set_roi error: {e}")


    def reset_roi(self, full_width: int, full_height: int) -> None:
        if self._cam is None or ROI is None:
            return

        try:
            sensor_w = int(self._cam.sensor_width_pixels)
            sensor_h = int(self._cam.sensor_height_pixels)

            ulx = 0
            uly = 0
            lrx = sensor_w - 1
            lry = sensor_h - 1

            print(f"[ThorlabsTLCameraBackend] reset_roi -> "
                f"({ulx},{uly})-({lrx},{lry})")

            was_armed = False
            try:
                was_armed = bool(self._cam.is_armed)
            except Exception:
                pass

            was_paused = self._paused

            if was_armed:
                try:
                    self._cam.disarm()
                except Exception:
                    pass

            self._cam.roi = ROI(
                upper_left_x_pixels=ulx,
                upper_left_y_pixels=uly,
                lower_right_x_pixels=lrx,
                lower_right_y_pixels=lry,
            )

            self._cam.frames_per_trigger_zero_for_unlimited = 0
            self._cam.image_poll_timeout_ms = 1000
            self._cam.arm(2)

            self._width = int(self._cam.image_width_pixels)
            self._height = int(self._cam.image_height_pixels)

            pane = self._pane
            worker = getattr(pane, "worker", None) if pane is not None else None
            if worker is not None:
                worker.reconfigure()

            if not was_paused:
                try:
                    self._cam.issue_software_trigger()
                except Exception as e:
                    print(f"[ThorlabsTLCameraBackend] issue_software_trigger after reset_roi failed: {e}")

        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] reset_roi error: {e}")


    def get_full_frame_size(self, res_index: int | None) -> tuple[int, int]:
        if self._cam is None:
            return (0, 0)
        try:
            w = int(self._cam.image_width_pixels)
            h = int(self._cam.image_height_pixels)
            return (w, h)
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] get_full_frame_size error: {e}")
            return (0, 0)


    # -------------------------------------------------
    # フレーム取得
    # -------------------------------------------------
    def pull_frame_into_buffer(self, buf, size, bits):
        if self._cam is None:
            print("[ThorlabsTLCameraBackend] pull_frame_into_buffer: _cam is None")
            return None
        if self._paused:
            return None
        if not self._cam.is_armed:
            print("[ThorlabsTLCameraBackend] pull_frame_into_buffer: camera not armed")
            return None

        frame = self._cam.get_pending_frame_or_null()
        if frame is None:
            # 新しいフレームが来ていないだけ
            return None

        print("[ThorlabsTLCameraBackend] NEW FRAME ARRIVED")
        # ★ Thorlabs 形式：image_buffer は「行ごとのシーケンス」
        #    → np.array(..., copy=False) で (h, w) の 2D uint16 配列になる
        img16 = np.array(frame.image_buffer, copy=False, dtype=np.uint16)
        if img16.ndim != 2:
            print(f"[ThorlabsTLCameraBackend] unexpected ndim: {img16.ndim}")
            return None

        h, w = img16.shape
        bit_depth = self._cam.bit_depth

        #print(f"[ThorlabsTLCameraBackend] frame shape = {h}x{w}, bit_depth={bit_depth}")        # デバッグ用

        # 表示は 8bit 固定にスケール
        if bit_depth > 8:
            shift = bit_depth - 8
            img8 = (img16 >> shift).astype(np.uint8)
        else:
            img8 = img16.astype(np.uint8)

        # QImage 用に row-major の 1D bytes
        data_bytes = img8.tobytes()
        if buf is not None:
            n = min(len(data_bytes), size)
            buf[:n] = data_bytes[:n]

        return {
            "w": w,
            "h": h,
            "bits": 8,              # 表示は 8bit
            "bpl": w,               # 8bit なので 1byte/pixel
            "data": data_bytes,
            "seq": frame.frame_count,
            "ts_us": int(time.time() * 1e6),
            "exp_us": self._cam.exposure_time_us,
        }


    def query_params(self, bits: int):
        """
        CaptureWorker 初期化・再設定用のパラメータ問い合わせ。
        戻り値: (w, h, bits, bpl, size)  ※ Thorlabs は常に 8bit 表示。
        """
        if self._cam is None:
            return None

        try:
            w = int(self._cam.image_width_pixels)
            h = int(self._cam.image_height_pixels)
            bit_depth = int(self._cam.bit_depth)
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] query_params error: {e}")
            return None

        self._width = w
        self._height = h
        self._bit_depth = bit_depth

        # 表示は常に 8bit
        bpp = 1
        self._bytes_per_pixel = bpp
        self._bpl = w * bpp
        size = h * self._bpl

        return (w, h, 8, self._bpl, size)


    def get_current_bit_depth(self) -> int:
        # 表示ビット深度としては常に 8bit
        return 8

    def capture_snapshot(self, bits: int):
        """
        カメラから 1 フレームだけ同期取得して返す。
        UI 側では必ず LiveView(Pause) してから呼ぶ前提。

        戻り値: dict (w,h,bits,bpl,data,seq,ts_us,exp_us) or None
        """
        if self._cam is None:
            print("[ThorlabsTLCameraBackend] capture_snapshot: _cam is None")
            return None

        # 1) 古い pending フレームを捨てる
        try:
            for _ in range(4):  # 最大 4 枚くらい捨てれば十分
                f = self._cam.get_pending_frame_or_null()
                if f is None:
                    break
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] capture_snapshot: drain error: {e}")

        # 2) 必要なら arm
        try:
            if not getattr(self._cam, "is_armed", False):
                self._cam.arm(2)
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] capture_snapshot: arm failed: {e}")
            return None

        # 3) 新しいフレーム用に 1 回だけソフトウェアトリガ
        try:
            self._cam.issue_software_trigger()
        except Exception as e:
            print(f"[ThorlabsTLCameraBackend] capture_snapshot: issue_software_trigger failed: {e}")
            return None

        # 4) そのトリガで撮れたフレームが来るまで短時間ポーリング
        frame = None
        frame = self._cam.get_pending_frame_or_null()
        if frame is None:
            print("timeout(1000ms) or capture failed")
            return None        
        #t0 = time.time()
        #timeout_s = 0.01  # 500 ms くらい待ったほうがよい？
        #while time.time() - t0 < timeout_s:
        #    frame = self._cam.get_pending_frame_or_null()
        #    if frame is not None:
        #        break
        #    time.sleep(0.005)

        #if frame is None:
        #    print("[ThorlabsTLCameraBackend] capture_snapshot: no frame within timeout")
        #    return None

        # 5) buffer → ndarray → 8bit/16bit に整形（pull_frame_into_buffer とほぼ同じ）
        img16 = np.array(frame.image_buffer, copy=True, dtype=np.uint16)

        try:
            h = int(self._cam.image_height_pixels)
            w = int(self._cam.image_width_pixels)
        except Exception:
            h, w = int(self._height), int(self._width)

        if img16.size < h * w:
            print("[ThorlabsTLCameraBackend] capture_snapshot: buffer size too small")
            return None

        img16 = img16.reshape(h, w)

        want_16 = (bits == 16)

        if want_16:
            data = img16.tobytes()
            bpl = w * 2
            out_bits = 16
        else:
            try:
                bit_depth = int(self._cam.bit_depth)
            except Exception:
                bit_depth = 12

            if bit_depth > 8:
                shift = bit_depth - 8
                img8 = (img16 >> shift).astype(np.uint8)
            else:
                img8 = img16.astype(np.uint8)

            data = img8.tobytes()
            bpl = w
            out_bits = 8

        ts_us = int(time.time() * 1e6)
        seq = getattr(frame, "frame_count", 0)
        exp_us = getattr(self._cam, "exposure_time_us", 0)

        return {
            "w": w,
            "h": h,
            "bits": out_bits,
            "bpl": bpl,
            "data": data,
            "seq": seq,
            "ts_us": ts_us,
            "exp_us": exp_us,
        }


    # -------------------------------------------------
    # 内部タイマー：疑似「IMAGEイベント」
    # -------------------------------------------------
    def _on_timer(self):
        """
        QTimer から呼ばれ、Nikon の WinMsg 相当として sig_image を投げる。
        wparam / lparam はダミー。
        """
        if self._paused:
            return
        #print("[ThorlabsTLCameraBackend] _on_timer emit sig_image")    # デバッグ用
        self.sig_image.emit(0, 0)



def get_backend_class():
    return ThorlabsTLCameraBackend
