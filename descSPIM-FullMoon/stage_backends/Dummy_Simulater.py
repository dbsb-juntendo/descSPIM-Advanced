# stage_backends/Dummy_Simulater.py
# -*- coding: utf-8 -*-

from __future__ import annotations

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Slot

from .stage_backend_base import IStageBackend


class DummyStageBackend(IStageBackend):
    """
    ハードウェアなしで動作確認するためのダミー backend。
    - ポジションは単なる float で管理
    - 各種メソッドは status メッセージを出すだけ
    """

    FINE_STEP_MM = 0.005  # 5 µm 相当

    def __init__(self, timing_logger=None, parent=None):
        super().__init__(timing_logger=timing_logger, parent=parent)

        # StagePanel 側から axis_name = "Sample"/"Camera" が設定される想定
        self.axis_name: str = getattr(self, "axis_name", "Dummy")

        self._connected: bool = False
        self._pos_mm: float = 0.0
        self._start_mm: float | None = None

        self._v_mm_s: float = 0.04
        self._a_mm_s2: float = 1.5
        self._dir_index: int = 0  # 0 = Forward, 1 = Reverse

        self._moving: bool = False
        self._jog_active: bool = False

    # ---------------- IStageBackend API ----------------

    def show_setup_dialog(self, parent=None) -> bool:
        """
        Dummy 用の簡単なダイアログ:
        - 「Connect」ボタンを押すだけで接続完了とみなす
        - 実機は無いので設定項目は無し
        """
        dlg = QtWidgets.QDialog(parent)
        axis = getattr(self, "axis_name", "Dummy")
        dlg.setWindowTitle(f"Dummy stage setup ({axis})")

        layout = QtWidgets.QVBoxLayout(dlg)
        lbl = QtWidgets.QLabel(
            f"Dummy stage backend for axis '{axis}'.\n"
            "This does not control real hardware."
        )
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dlg,
        )
        layout.addWidget(buttons)

        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            # キャンセルされた場合は何もしない
            return False

        # 接続処理をここで擬似的に実行
        self.connect_device()
        return True

    @Slot()
    def connect_device(self):
        """
        実機は無いので、即座に connected=True にして signal を出すだけ。
        """
        if self._connected:
            return

        self._connected = True
        self.sig_connected.emit(True)
        axis = getattr(self, "axis_name", "Dummy")
        self.sig_status.emit(f"[{axis}] Dummy connected.")
        # 実機のように「対応製品列挙」をする代わりに、適当な名前を 1 個だけ通知
        try:
            self.sig_supported_products.emit([f"Dummy-{axis}"])
        except Exception:
            # base によってはこの signal が無い可能性もあるので一応ガード
            pass

    @Slot()
    def shutdown(self):
        """
        切断処理。内部フラグを落として status を出すだけ。
        """
        if not self._connected:
            return

        axis = getattr(self, "axis_name", "Dummy")
        self._connected = False
        self.sig_connected.emit(False)
        self.sig_status.emit(f"[{axis}] Dummy disconnected.")

    @Slot(float, float, int)
    def apply_params(self, v_mm_s: float, a_mm_s2: float, dir_index: int):
        """
        速度・加速度・方向を保存するだけ。
        """
        self._v_mm_s = float(v_mm_s)
        self._a_mm_s2 = float(a_mm_s2)
        self._dir_index = int(dir_index)
        axis = getattr(self, "axis_name", "Dummy")
        self.sig_status.emit(
            f"[{axis}] params applied "
            f"(v={self._v_mm_s:.5f} mm/s, a={self._a_mm_s2:.3f} mm/s², dir={self._dir_index})"
        )

    @Slot()
    def home(self):
        """
        原点に戻した体にする。
        """
        if not self._connected:
            self.sig_error.emit("home: not connected (dummy)")
            return
        axis = getattr(self, "axis_name", "Dummy")
        self._pos_mm = 0.0
        if self.timing:
            self.timing.log_event(f"{axis}_HOME_DUMMY")
        self.sig_status.emit(f"[{axis}] homed (dummy pos=0.0 mm).")

    @Slot()
    def register_start_point(self):
        """
        現在位置を start position として保存。
        """
        if not self._connected:
            self.sig_error.emit("register_start_point: not connected (dummy)")
            return
        axis = getattr(self, "axis_name", "Dummy")
        self._start_mm = self._pos_mm
        self.sig_startpos_updated.emit(self._start_mm)
        self.sig_status.emit(
            f"[{axis}] Start pos registered (dummy): {self._start_mm:.6f} mm"
        )

    @Slot()
    def go_to_start_position(self):
        """
        登録された start position にジャンプしたことにする。
        """
        if not self._connected:
            self.sig_error.emit("go_to_start_position: not connected (dummy)")
            return
        if self._start_mm is None:
            self.sig_error.emit("go_to_start_position: start position not registered (dummy)")
            return
        axis = getattr(self, "axis_name", "Dummy")
        self._pos_mm = self._start_mm
        if self.timing:
            self.timing.log_event(f"{axis}_GOTO_START_DUMMY")
        self.sig_status.emit(
            f"[{axis}] at start position (dummy): {self._pos_mm:.6f} mm"
        )

    @Slot()
    def start_continuous(self):
        """
        連続移動開始（フラグだけ立てる）
        """
        if not self._connected:
            self.sig_error.emit("start_continuous: not connected (dummy)")
            return
        if self._moving:
            return
        axis = getattr(self, "axis_name", "Dummy")
        self._moving = True
        if self.timing:
            self.timing.log_event(f"{axis}_STAGE_START_DUMMY")
        self.sig_status.emit(f"[{axis}] continuous move started (dummy).")

    @Slot()
    def stop_only(self):
        """
        連続移動停止（フラグだけ落とす）
        """
        if not self._connected:
            self.sig_error.emit("stop_only: not connected (dummy)")
            return
        if not self._moving and not self._jog_active:
            return
        axis = getattr(self, "axis_name", "Dummy")
        self._moving = False
        self._jog_active = False
        if self.timing:
            self.timing.log_event(f"{axis}_STAGE_STOP_CMD_DUMMY")
        self.sig_status.emit(f"[{axis}] stopped (dummy).")

    @Slot(int)
    def start_jog(self, direction_index: int):
        """
        Jog 開始（方向だけ記録して status を出す）。
        """
        if not self._connected:
            self.sig_error.emit("start_jog: not connected (dummy)")
            return
        if self._jog_active:
            self.sig_status.emit("jog already running (dummy)")
            return

        self._jog_active = True
        axis = getattr(self, "axis_name", "Dummy")
        d_label = "Forward" if direction_index == 0 else "Reverse"
        if self.timing:
            self.timing.log_event(f"{axis}_JOG_START_{d_label}_DUMMY")
        self.sig_status.emit(f"[{axis}] jog started ({d_label}, dummy)")

    @Slot()
    def stop_jog(self):
        """
        Jog 停止。
        """
        if not self._connected:
            self.sig_error.emit("stop_jog: not connected (dummy)")
            return
        if not self._jog_active:
            return
        axis = getattr(self, "axis_name", "Dummy")
        self._jog_active = False
        if self.timing:
            self.timing.log_event(f"{axis}_JOG_STOP_DUMMY")
        self.sig_status.emit(f"[{axis}] jog stopped (dummy)")

    @Slot(int)
    def step(self, direction_sign: int):
        """
        単ステップ移動（5 µm を前後に動かしたことにする）。
        """
        if not self._connected:
            self.sig_error.emit("step: not connected (dummy)")
            return

        if direction_sign > 0:
            d_label = "Forward"
        else:
            d_label = "Reverse"

        self._pos_mm += direction_sign * self.FINE_STEP_MM
        axis = getattr(self, "axis_name", "Dummy")
        if self.timing:
            self.timing.log_event(f"{axis}_STEP_{d_label}_DUMMY")
        self.sig_status.emit(
            f"[{axis}] fine step {d_label} {self.FINE_STEP_MM*1e3:.1f} µm "
            f"(dummy pos={self._pos_mm:.6f} mm)"
        )

    @Slot(str)
    def start_home_return_async(self, save_dir_for_log: str):
        """
        本物はスレッドで Home→Return をやるが、
        Dummy では単に log を出してホーム／スタート位置へ戻したことにする。
        """
        if not self._connected:
            self.sig_error.emit("start_home_return_async: not connected (dummy)")
            return

        axis = getattr(self, "axis_name", "Dummy")

        def _do_return():
            try:
                if self.timing:
                    self.timing.log_event(f"{axis}_STOP_CMD_BEFORE_RETURN_DUMMY")
                self.sig_status.emit(f"[{axis}] (dummy) stopping before return...")
                # home → start に戻す
                self.home()
                if self._start_mm is not None:
                    self._pos_mm = self._start_mm
                    if self.timing:
                        self.timing.log_event(f"{axis}_RETURN_DONE_DUMMY")
                    self.sig_status.emit(
                        f"[{axis}] returned to start position (dummy): {self._pos_mm:.6f} mm"
                    )
                else:
                    self.sig_status.emit(
                        f"[{axis}] no start position registered (dummy)."
                    )
                # ログの flush は timing_logger 側に任せる（ここでは何もしない）
            except Exception as e:
                self.sig_error.emit(f"start_home_return_async (dummy): {e}")

        # 疑似的に「非同期」にしたいだけなので singleShot(0) で投げる
        QtCore.QTimer.singleShot(0, _do_return)


def get_backend_class():
    """
    StagePanel から参照されるファクトリ。
    ファイル名 Dummy_Simulater.py がコンボボックスにそのまま出る。
    """
    return DummyStageBackend
