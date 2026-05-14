# camera_backend_nikon.py
from __future__ import annotations
import sys
from typing import Any
import ctypes
from ctypes import c_int, c_uint, c_ushort, byref, c_void_p,wintypes
from PySide6.QtCore import QObject, Signal, Qt, QAbstractNativeEventFilter, QCoreApplication
from .camera_backend_base import ICameraBackend
import win32con


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd",    ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam",  wintypes.WPARAM),  # ← ここを変更
        ("lParam",  wintypes.LPARAM),  # ← ここを変更
        ("time",    ctypes.c_uint),
        ("pt_x",    ctypes.c_long),
        ("pt_y",    ctypes.c_long),
    ]

_backend_filter = None  # グローバルに 1 個だけ入れる

class WinMsgFilter(QAbstractNativeEventFilter):
    def __init__(self, backend: "NikonDS50MBackend", msg_id: int):
        super().__init__()
        self._backend = backend
        self._msg_id = msg_id

    def nativeEventFilter(self, eventType, message):
        # PySide6 では eventType は bytes
        if eventType not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0

        addr = int(message)
        m = MSG.from_address(addr)
        if m.message != self._msg_id:
            return False, 0

        wparam = int(m.wParam)
        lparam = int(m.lParam)

        # 汎用イベント
        self._backend.sig_event.emit(wparam, lparam)

        ci = _ci()
        if wparam == ci.NkcamEvent.NKCAM_EVENT_IMAGE:
            self._backend.sig_image.emit(wparam, lparam)
        elif wparam == ci.NkcamEvent.NKCAM_EVENT_ERROR:
            self._backend.sig_error.emit(wparam, lparam)
        elif wparam == ci.NkcamEvent.NKCAM_EVENT_DISCONNECTED:
            self._backend.sig_disconnected.emit(wparam, lparam)

        return True, 0



def _ci():
    """
    Nikon SDK 定義を持つモジュールを遅延インポートして返すヘルパ。
    """
    import nikon_sdk as ci
    return ci


class NikonDS50MBackend(ICameraBackend):
    """
    DS50M 専用 backend 実装。
    低レベル SDK 呼び出しは camera_integration 内の関数/定数を経由して行う。
    """

    # NKCAM_MSG_ID をこのファイルで定義
    NKCAM_MSG_ID = win32con.WM_APP + 1

    # Win32 メッセージ → SDK イベントの橋渡し用シグナル
    sig_event = Signal(int, int)
    sig_image = Signal(int, int)
    sig_error = Signal(int, int)
    sig_disconnected = Signal(int, int)
    sig_frame = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._worker: Any = None        # CaptureWorker 相当
        self._pane: Any = parent        # CameraPane を想定
        self.ensure_filter_installed()

    def describe_event(self, wparam: int) -> str:
            """
            Nkcam のイベントコードを人間可読な名前に変換する（なければ None）。
            """
            try:
                ci = _ci()
                member = ci.NkcamEvent._value2member_map_.get(int(wparam))
                return member.name if member is not None else ""
            except Exception:
                return ""

    def ensure_filter_installed(self) -> None:
        """
        Win32 メッセージを受け取るネイティブイベントフィルタを 1 回だけインストール。
        """
        global _backend_filter
        app = QCoreApplication.instance()
        if app is None:
            return
        if _backend_filter is None:
            _backend_filter = WinMsgFilter(self, self.NKCAM_MSG_ID)
            app.installNativeEventFilter(_backend_filter)

    # ------------------------
    # Worker 接続
    # ------------------------
    def attach_worker(self, worker: Any) -> None:
        """
        CaptureWorker の sig_frame_ready を backend.sig_frame に橋渡し。
        """
        self._worker = worker
        try:
            worker.sig_frame_ready.connect(self.sig_frame, Qt.QueuedConnection)
        except Exception:
            pass

    # ------------------------
    # connect / disconnect
    # ------------------------
    def connect(self) -> bool:
        """
        Connect Camera ボタンから呼ばれる。
        - Nkcam_Open でカメラを開く
        - CameraPane.hcam にセット
        - CameraPane._init_camera_ui() を呼んで Worker などを立ち上げる
        """
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return False

        # すでに接続済みなら何もしない
        if getattr(pane, "hcam", None):
            return True

        ci = _ci()

        # カメラを開く
        hcam = ci.Nkcam_Open(None)
        if not hcam:
            return False

        # CameraPane 側にハンドルを渡して UI 初期化
        pane.hcam = hcam
        try:
            pane._init_camera_ui()
        except Exception as e:
            # ★ 何が起きたかコンソールに出す
            import traceback
            print("[NikonDS50MBackend] _init_camera_ui error:", e)
            traceback.print_exc()

            # 失敗したらクローズして後始末しておく
            try:
                ci.Nkcam_Close(hcam)
            except Exception:
                pass
            pane.hcam = None
            return False


        return True

    def disconnect(self) -> None:
        """
        カメラとの接続を閉じる（Pause/Stop/Close をまとめて実行）
        """
        pane = self._pane
        if pane is None:
            print("[Backend] disconnect() called but no pane")
            return

        hcam = getattr(pane, "hcam", None)
        if not hcam:
            print("[Backend] disconnect() called but no hcam")
            return

        ci = _ci()

        # --- ストリーム停止 ---
        try:
            ci.Nkcam_Pause(hcam, c_int(1))
        except Exception:
            pass
        try:
            ci.Nkcam_Stop(hcam)
        except Exception:
            pass

        # --- Close ---
        try:
            ci.Nkcam_Close(hcam)
        except Exception:
            pass

        pane.hcam = None

        print("[Backend] Camera disconnect sequence finished.")

    def start_stream(self, hwnd: int) -> None:
        """
        WinMsg 登録＋ストリーム開始をまとめて実行。
        初期状態では Pause=ON にしておく。
        """
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return

        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return

        ci = _ci()

        try:
            hr = ci.Nkcam_StartPullModeWithWndMsg(
                hcam,
                wintypes.HWND(hwnd),
                wintypes.UINT(self.NKCAM_MSG_ID),
            )
            code = int(hr) & 0xFFFFFFFF
            if int(hr) != 0:
                print(f"[Backend] Nkcam_StartPullModeWithWndMsg failed: hr=0x{code:08X}")
        except Exception as e:
            print(f"[Backend] start_stream error: {e}")
            return

        # 初期状態は Pause=ON（これまで sdk_register_message_window + sdk_pause_stream
        # でやっていたことと同等の挙動）
        try:
            hr2 = ci.Nkcam_Pause(hcam, c_int(1))
            code2 = int(hr2) & 0xFFFFFFFF
            if int(hr2) != 0:
                print(f"[Backend] Nkcam_Pause(ON) failed: hr=0x{code2:08X}")
        except Exception as e:
            print(f"[Backend] start_stream pause error: {e}")


    # ------------------------
    # Pause / Resume
    # ------------------------
    def set_paused(self, paused: bool) -> None:
        """
        SDK の Pause/Resume を backend が責任を持って実装。
        """
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return

        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return

        ci = _ci()

        if paused:
            # Pause=ON
            try:
                ci.Nkcam_Pause(hcam, c_int(1))
            except Exception:
                pass
        else:
            # Resume （FLUSH → Pause OFF）
            try:
                ci.Nkcam_put_Option(
                    hcam,
                    c_uint(ci.NKCAM_OPTION_FLUSH),
                    c_int(3),
                )
            except Exception:
                pass
            try:
                ci.Nkcam_Pause(hcam, c_int(0))
            except Exception:
                pass

    # ------------------------
    # SDK → UI 初期化
    # ------------------------
    def populate_controls(self, pane: Any) -> None:
        """
        DS50M から範囲・現在値を読み出して UI を初期化する。
        （元の CameraPane._populate_controls の SDK 部分をこちらに移行）
        """
        if pane is None or not hasattr(pane, "hcam"):
            return
        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return

        ci = _ci()

        # ----- Gain range/current -----
        gmin = c_ushort(0)
        gmax = c_ushort(0)
        gdef = c_ushort(0)
        hr = ci.Nkcam_get_ExpoAGainRange(hcam, byref(gmin), byref(gmax), byref(gdef))
        if hr == 0:
            pane.ctrl_gain.setRange(int(gmin.value), int(gmax.value))

        curg = c_ushort(0)
        if ci.Nkcam_get_ExpoAGain(hcam, byref(curg)) == 0:
            pane.ctrl_gain.setValue(int(curg.value))

        # ----- Exposure range/current (SDK は μs) -----
        emin = c_uint(0)
        emax = c_uint(0)
        edef = c_uint(0)
        if ci.Nkcam_get_ExpTimeRange(hcam, byref(emin), byref(emax), byref(edef)) == 0:
            pane.ctrl_expo.setRange(
                ci.us_to_ms(emin.value),
                ci.us_to_ms(emax.value),
            )
            span_ms = ci.us_to_ms(emax.value - max(emin.value, 1))
            pane.ctrl_expo.setSingleStep(0.1 if span_ms > 10 else 0.01)

        cure = c_uint(0)
        if ci.Nkcam_get_ExpoTime(hcam, byref(cure)) == 0:
            pane.ctrl_expo.setValue(ci.us_to_ms(cure.value))

        # ----- Resolution list/current -----
        pane.ctrl_res.clear()
        n = int(ci.Nkcam_get_ResolutionNumber(hcam) or 0)
        if n > 0:
            for i in range(n):
                w = c_int(0)
                h_ = c_int(0)
                if ci.Nkcam_get_Resolution(hcam, c_uint(i), byref(w), byref(h_)) == 0:
                    pane.ctrl_res.addItem(f"{w.value}x{h_.value}", i)

        # 現在の実出力サイズに最も近いインデックスを選択
        cw = c_int(0)
        ch = c_int(0)
        if ci.Nkcam_get_FinalSize(hcam, byref(cw), byref(ch)) == 0:
            text = f"{cw.value}x{ch.value}"
            idx = pane.ctrl_res.findText(text)
            if idx >= 0:
                pane.ctrl_res.setCurrentIndex(idx)

        # ----- Bit depth current (0=Y8, 1=Y16) -----
        v = c_int(0)
        if ci.Nkcam_get_Option(hcam, c_uint(ci.NKCAM_OPTION_BITDEPTH), byref(v)) == 0:
            pane.ctrl_bit.setCurrentIndex(0 if v.value == 0 else 1)

    # ------------------------
    # Gain / Exposure 適用
    # ------------------------
    def apply_gain_expo(self, gain: int, expo_ms: float) -> None:
        """
        gain / exposure(ms) を DS50M SDK に反映する。
        """
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return
        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return

        ci = _ci()

        # UI は ms、SDK は μs
        expo_us = ci.ms_to_us(expo_ms)

        # 安全のため SDK 範囲でクリップ
        emin = c_uint(0)
        emax = c_uint(0)
        edef = c_uint(0)
        if ci.Nkcam_get_ExpTimeRange(hcam, byref(emin), byref(emax), byref(edef)) == 0:
            expo_us = max(
                int(emin.value),
                min(int(emax.value), int(expo_us)),
            )

        g = c_ushort(int(gain))
        hr1 = ci.Nkcam_put_ExpoAGain(hcam, g)
        hr2 = ci.Nkcam_put_ExpoTime(hcam, c_uint(expo_us))

        print(
            f"put_ExpoAGain hr=0x{(int(hr1)&0xffffffff):08X}, "
            f"put_ExpoTime({expo_us}us) hr=0x{(int(hr2)&0xffffffff):08X}"
        )

    # ------------------------
    # Resolution / BitDepth 適用
    # ------------------------
    def apply_res_bit(self, res_index: int, bit_index: int) -> None:
        """
        解像度(res_index)とビット深度(bit_index: 0=8bit, 1=16bit)を
        DS50M SDK に反映する。
        """
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return
        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return

        ci = _ci()

        hwnd = int(pane.window().winId())

        # ① Stop
        hr = ci.Nkcam_Stop(hcam)
        print(f"Stop hr=0x{(int(hr)&0xffffffff):08X}")

        # ② 解像度設定（eSize）
        if res_index is not None:
            hrr = ci.Nkcam_put_eSize(hcam, c_uint(int(res_index)))
            print(f"put_eSize({int(res_index)}) hr=0x{(int(hrr)&0xffffffff):08X}")

        # ③ BitDepth（0=Y8, 1=Y16）
        new_bit_idx = int(bit_index)
        hrb = ci.Nkcam_put_Option(
            hcam,
            c_uint(ci.NKCAM_OPTION_BITDEPTH),
            c_int(0 if new_bit_idx == 0 else 1),
        )
        print(f"put_Option(BITDEPTH) hr=0x{(int(hrb)&0xffffffff):08X}")

        # ④ RGB（3=Y8, 4=Y16）
        rgb_code = 3 if new_bit_idx == 0 else 4
        hrrgb = ci.Nkcam_put_Option(
            hcam,
            c_uint(ci.NKCAM_OPTION_RGB),
            c_int(rgb_code),
        )
        print(f"put_Option(RGB={rgb_code}) hr=0x{(int(hrrgb)&0xffffffff):08X}")

        # ⑤ FinalSizeでバッファ準備（Worker側のbitsも更新）
        worker = getattr(pane, "worker", None)
        if worker is not None:
            worker._bits = 8 if new_bit_idx == 0 else 16
            worker.reconfigure()

        # ⑥ メッセージ登録＋ストリーム開始（Pause=ON）を共通関数で
        hwnd = int(pane.window().winId())
        #self.start_stream(hwnd, self.NKCAM_MSG_ID)
        self.start_stream(hwnd)


    # ------------------------
    # ROI 関連
    # ------------------------
    def set_roi(self, x: int, y: int, w: int, h: int) -> None:
        """ROI を SDK に設定し、ストリームを再構成する。"""
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return
        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return

        ci = _ci()

        ci.Nkcam_Stop(hcam)
        hr = ci.Nkcam_put_Roi(
            hcam,
            c_uint(x),
            c_uint(y),
            c_uint(w),
            c_uint(h),
        )
        code = int(hr) & 0xFFFFFFFF
        print(f"[Backend] Nkcam_put_Roi({x},{y},{w},{h}) hr=0x{code:08X}")

        # メッセージ登録＋ストリーム開始（Pause=ON）を共通関数で
        hwnd = int(pane.window().winId())
        #self.start_stream(hwnd, self.NKCAM_MSG_ID)
        self.start_stream(hwnd)

        worker = getattr(pane, "worker", None)
        if worker is not None:
            worker.reconfigure()

    def reset_roi(self, full_width: int, full_height: int) -> None:
        """ROI をフルフレームに戻し、ストリームを再構成する。"""
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return
        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return

        ci = _ci()

        ci.Nkcam_Stop(hcam)
        hr = ci.Nkcam_put_Roi(
            hcam,
            c_uint(0),
            c_uint(0),
            c_uint(full_width),
            c_uint(full_height),
        )
        code = int(hr) & 0xFFFFFFFF
        print(f"[Backend] Nkcam_put_Roi(reset) hr=0x{code:08X}")

        hwnd = int(pane.window().winId())
        #self.start_stream(hwnd, self.NKCAM_MSG_ID)
        self.start_stream(hwnd)

        worker = getattr(pane, "worker", None)
        if worker is not None:
            worker.reconfigure()



    def get_full_frame_size(self, res_index: int | None) -> tuple[int, int]:
        """
        解像度インデックスからフルフレームサイズ (w, h) を返す。
        res_index が None の場合は、Nkcam_get_FinalSize から取得を試みる。
        どちらも失敗した場合は (0, 0) を返す。
        """
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return (0, 0)
        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return (0, 0)

        ci = _ci()

        # 解像度インデックスが指定されている場合は Nkcam_get_Resolution を優先
        if res_index is not None:
            w = c_int(0)
            h = c_int(0)
            hr = ci.Nkcam_get_Resolution(
                hcam,
                c_uint(int(res_index)),
                byref(w),
                byref(h),
            )
            if hr == 0 and w.value > 0 and h.value > 0:
                return (w.value, h.value)
            else:
                print(
                    f"[Backend] Nkcam_get_Resolution failed: "
                    f"hr=0x{(int(hr)&0xffffffff):08X}"
                )

        # フォールバック: 現在の FinalSize から取得
        w2 = c_int(0)
        h2 = c_int(0)
        hr2 = ci.Nkcam_get_FinalSize(hcam, byref(w2), byref(h2))
        if hr2 == 0 and w2.value > 0 and h2.value > 0:
            return (w2.value, h2.value)

        print(
            f"[Backend] get_full_frame_size fallback failed: "
            f"hr=0x{(int(hr2)&0xffffffff):08X}"
        )
        return (0, 0)
    
    def pull_frame_into_buffer(self, buf, size, bits: int):
        """
        カメラから 1 フレーム取得して dict を返す。
        CameraPane 側の hcam を利用する。
        """
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return None

        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return None

        ci = _ci()

        # 画像を pull
        info = ci.NkcamFrameInfoV3()
        hr = ci.Nkcam_PullImageV3(
            hcam,
            ctypes.cast(buf, c_void_p),
            c_int(0),              # bStill = 0 (video)
            c_int(bits),           # 8 or 16
            c_int(0),              # rowPitch = 0 (連続)
            byref(info),
        )
        if hr != 0:
            # 必要ならデバッグ用にログを出す
            # print(f"[Backend] Nkcam_PullImageV3 failed: hr=0x{(int(hr)&0xffffffff):08X}")
            return None

        # 現在の出力サイズ（ROI 反映後）を取得
        w = c_int(0)
        h = c_int(0)
        hr2 = ci.Nkcam_get_FinalSize(hcam, byref(w), byref(h))
        if hr2 != 0 or w.value <= 0 or h.value <= 0:
            return None

        # バイト列に変換
        data = ctypes.string_at(buf, size)
        bpl = w.value * (bits // 8)

        return {
            "w": w.value,
            "h": h.value,
            "bits": bits,
            "bpl": bpl,
            "data": data,
            "seq": int(info.seq),
            "ts_us": int(info.timestamp),
            "exp_us": int(info.expotime),
        }

    def query_params(self, bits: int):
        """
        現在の FinalSize などから、
        (w, h, bits, bpl, size) を返す。
        """
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return None

        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return None

        ci = _ci()

        w = c_int(0)
        h = c_int(0)
        hr = ci.Nkcam_get_FinalSize(hcam, byref(w), byref(h))
        code = int(hr) & 0xFFFFFFFF
        if int(hr) != 0 or w.value <= 0 or h.value <= 0:
            print(f"[Backend] Nkcam_get_FinalSize failed: hr=0x{code:08X}")
            return None

        # bits は引数をそのまま信じる（8 or 16）
        bpl = w.value * (bits // 8)
        size = bpl * h.value

        return (w.value, h.value, bits, bpl, size)
    
    def get_current_bit_depth(self) -> int:
        """
        現在のカメラ設定のビット深度 (8 or 16) を返す。
        エラー時は 8bit とみなす。
        """
        pane = self._pane
        if pane is None or not hasattr(pane, "hcam"):
            return 8

        hcam = getattr(pane, "hcam", None)
        if not hcam:
            return 8

        ci = _ci()
        v = c_int(0)
        try:
            hr = ci.Nkcam_get_Option(
                hcam,
                c_uint(ci.NKCAM_OPTION_BITDEPTH),
                byref(v),
            )
        except Exception as e:
            print(f"[Backend] Nkcam_get_Option(NKCAM_OPTION_BITDEPTH) error: {e}")
            return 8

        code = int(hr) & 0xFFFFFFFF
        if int(hr) != 0:
            print(f"[Backend] Nkcam_get_Option failed: hr=0x{code:08X}")
            return 8

        # DS50M: 0=8bit, 1=16bit
        return 8 if v.value == 0 else 16




def get_backend_class():
    return NikonDS50MBackend   # そのファイル内の実クラスを返す
