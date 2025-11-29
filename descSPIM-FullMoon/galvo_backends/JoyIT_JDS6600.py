# galvo_backends/JDS6600.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Any, Tuple, Optional

import logging

from PySide6 import QtCore, QtWidgets
from serial.tools import list_ports

from .galvo_backend_base import IGalvoBackend

logger = logging.getLogger(__name__)

try:
    import jds6600  # pip install jds6600
except ImportError:
    jds6600 = None


def _ch_id_to_index(ch_id: str) -> Optional[int]:
    """'CH1' / '1' → 1, 'CH2' / '2' → 2"""
    s = str(ch_id).strip().upper()
    if s == "CH1" or s == "1":
        return 1
    if s == "CH2" or s == "2":
        return 2
    return None


class JDS6600PortDialog(QtWidgets.QDialog):
    """JDS6600 の COM ポート選択ダイアログ"""

    def __init__(
        self,
        settings: QtCore.QSettings,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._selected_port: str = ""

        self.setWindowTitle("Select JDS6600 Port")

        self.cmb_port = QtWidgets.QComboBox()
        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self._refresh_ports)

        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self,
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        lay_top = QtWidgets.QHBoxLayout()
        lay_top.addWidget(QtWidgets.QLabel("Port:"))
        lay_top.addWidget(self.cmb_port, 1)
        lay_top.addWidget(self.btn_refresh)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(lay_top)
        lay.addWidget(btn_box)

        self._refresh_ports()
        self._restore_last_port()

    def _refresh_ports(self) -> None:
        self.cmb_port.clear()
        for p in list_ports.comports():
            self.cmb_port.addItem(p.device, p.device)
        if self.cmb_port.count() == 0:
            self.cmb_port.addItem("(no ports found)", "")

    def _restore_last_port(self) -> None:
        last_port = self._settings.value("port", "", str)
        if not last_port:
            return
        idx = self.cmb_port.findData(last_port)
        if idx >= 0:
            self.cmb_port.setCurrentIndex(idx)

    @property
    def selected_port(self) -> str:
        return self._selected_port

    def accept(self) -> None:
        data = self.cmb_port.currentData()
        if data:
            self._selected_port = str(data)
            self._settings.setValue("port", self._selected_port)
        super().accept()


class JDS6600Backend(IGalvoBackend):
    """
    JDS6600 用 backend 実装

    ・2 チャンネル（CH1, CH2）を想定
    ・waveform: "sine", "square", "triangle", "sawtooth"
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._dev: Optional["jds6600.JDS6600"] = None
        self._port: str = ""
        self._settings = QtCore.QSettings("LabSuite", "JDS6600")

    # ---- 接続系 ----

    def show_setup_dialog(self, parent=None) -> bool:
        if jds6600 is None:
            QtWidgets.QMessageBox.warning(
                parent,
                "JDS6600",
                "The 'jds6600' package was not found.\nPlease run 'pip install jds6600'.",
            )

            return False

        dlg = JDS6600PortDialog(self._settings, parent=parent)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False

        port = dlg.selected_port
        if not port:
            QtWidgets.QMessageBox.warning(
                parent,
                "JDS6600",
                "No valid port selected.",
            )
            return False

        self._port = port
        return True

    def connect(self) -> bool:
        if jds6600 is None:
            self.sig_error.emit(
                "The 'jds6600' package was not found. Please run 'pip install jds6600'."
            )
            self.sig_connected.emit(False)
            return False

        if not self._port:
            self.sig_error.emit("Connection port is not set.")
            self.sig_connected.emit(False)
            return False

        # 既存接続をクリーンアップ
        self.disconnect()

        try:
            dev = jds6600.JDS6600(port=self._port)
            dev.connect()
            self._dev = dev
            self.sig_connected.emit(True)
            return True
        except Exception as e:
            self._dev = None
            msg = f"JDS6600 connection error: {e}"
            logger.exception(msg)
            self.sig_error.emit(msg)
            self.sig_connected.emit(False)
            return False

    def disconnect(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            except Exception:
                pass
        self._dev = None
        self.sig_connected.emit(False)

    def get_connection_key(self) -> str:
        return self._port or ""

    # ---- チャンネル情報 ----

    def get_channels(self) -> list[dict]:
        # JDS6600 は CH1 / CH2 の 2ch を想定
        return [
            {"id": "CH1", "name": "CH1"},
            {"id": "CH2", "name": "CH2"},
        ]

    # ---- 内部ヘルパ ----

    def _get_channels_raw(self) -> Tuple[Optional[bool], Optional[bool]]:
        if self._dev is None:
            return None, None
        try:
            ch1, ch2 = self._dev.get_channels()
            return bool(ch1), bool(ch2)
        except Exception as e:
            self.sig_error.emit(f"get_channels error: {e}")
            return None, None

    def _call_dev(self, func_name: str, *args, **kwargs) -> None:
        if self._dev is None:
            return
        try:
            func = getattr(self._dev, func_name, None)
            if func is None:
                raise AttributeError(func_name)
            func(*args, **kwargs)
        except Exception as e:
            self.sig_error.emit(f"{func_name} error: {e}")

    # ---- パラメータ設定 ----

    def set_freq(self, ch_id: str, value_hz: float) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None:
            return
        self._call_dev("set_frequency", channel=idx, value=float(value_hz))
        self._emit_state_changed()

    def set_amp(self, ch_id: str, value_vpp: float) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None:
            return
        self._call_dev("set_amplitude", channel=idx, value=float(value_vpp))
        self._emit_state_changed()

    def set_offset(self, ch_id: str, value_v: float) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None:
            return
        self._call_dev("set_offset", channel=idx, value=float(value_v))
        self._emit_state_changed()

    def set_waveform(self, ch_id: str, wave: str) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None:
            return
        # JDS6600 ライブラリは小文字 wave を想定（既存コードに合わせる）
        self._call_dev("set_waveform", channel=idx, value=str(wave))
        self._emit_state_changed()

    # ---- ON/OFF ----

    def set_enabled(self, ch_id: str, enabled: bool) -> None:
        if self._dev is None:
            return

        ch_index = _ch_id_to_index(ch_id)
        if ch_index is None:
            return

        ch1, ch2 = self._get_channels_raw()
        if ch1 is None and ch2 is None:
            return

        if ch_index == 1:
            ch1 = bool(enabled)
        elif ch_index == 2:
            ch2 = bool(enabled)

        try:
            self._dev.set_channels(channel1=ch1, channel2=ch2)
        except Exception as e:
            self.sig_error.emit(f"set_channels error: {e}")
            return

        self._emit_state_changed()

    def get_enabled(self, ch_id: str) -> bool:
        ch_index = _ch_id_to_index(ch_id)
        if ch_index is None:
            return False
        ch1, ch2 = self._get_channels_raw()
        if ch1 is None and ch2 is None:
            return False
        if ch_index == 1:
            return bool(ch1)
        if ch_index == 2:
            return bool(ch2)
        return False

    # ---- 状態問い合わせ / 安全系 ----

    def query_status(self) -> Dict[str, Any]:
        state: Dict[str, Any] = {"channels": {}}
        if self._dev is None:
            return state

        try:
            ch1_enabled, ch2_enabled = self._dev.get_channels()
            for idx, ch_id in ((1, "CH1"), (2, "CH2")):
                try:
                    wf = self._dev.get_waveform(channel=idx)
                except Exception:
                    wf = None
                try:
                    freq = float(self._dev.get_frequency(channel=idx))
                except Exception:
                    freq = None
                try:
                    amp = float(self._dev.get_amplitude(channel=idx))
                except Exception:
                    amp = None
                try:
                    offset = float(self._dev.get_offset(channel=idx))
                except Exception:
                    offset = None

                enabled = bool(ch1_enabled) if idx == 1 else bool(ch2_enabled)

                state["channels"][ch_id] = {
                    "enabled": enabled,
                    "waveform": wf,
                    "freq": freq,
                    "amp": amp,
                    "offset": offset,
                }
        except Exception as e:
            self.sig_error.emit(f"query_status error: {e}")
        return state

    def emergency_shutdown(self) -> None:
        if self._dev is None:
            return
        try:
            # 両チャンネル OFF
            self._dev.set_channels(channel1=False, channel2=False)
        except Exception as e:
            self.sig_error.emit(f"emergency_shutdown error: {e}")
        self._emit_state_changed()

    # ---- 内部 ----

    def _emit_state_changed(self) -> None:
        try:
            self.sig_state_changed.emit(self.query_status())
        except Exception:
            pass


def get_backend_class():
    """GalvoPane から呼ばれるファクトリ"""
    return JDS6600Backend
