# galvo_backends/Dummy_SimulatedGalvo.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Any, Optional
import logging

from PySide6 import QtCore

from .galvo_backend_base import IGalvoBackend

logger = logging.getLogger(__name__)


class DummySimulatedGalvoBackend(IGalvoBackend):
    """
    Dummy simulated galvo backend.

    - 2 channels (CH1, CH2)
    - No real hardware access
    - Used for UI / sequence testing
    """

    # インスタンスごとの connection_key を被らせないためのカウンタ
    _instance_counter: int = 0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        # connection_key は show_setup_dialog() 内で決める
        self._connection_key: str = ""

        # 内部状態: channels["CH1" or "CH2"] = {enabled, waveform, freq, amp, offset}
        self._channels: Dict[str, Dict[str, Any]] = {
            "CH1": {
                "enabled": False,
                "waveform": "sine",
                "freq": 100.0,
                "amp": 5.0,
                "offset": 0.0,
            },
            "CH2": {
                "enabled": False,
                "waveform": "sine",
                "freq": 100.0,
                "amp": 5.0,
                "offset": 0.0,
            },
        }

        self._connected: bool = False

    # ---- 接続系 ----

    def show_setup_dialog(self, parent=None) -> bool:
        """
        Dummy のため、ダイアログは出さずに自動で connection_key を割り当てて True を返す。
        """
        if not self._connection_key:
            type(self)._instance_counter += 1
            self._connection_key = f"DummySimulated-{type(self)._instance_counter}"
        return True

    def connect(self) -> bool:
        """
        実機は無いので、フラグだけ立てて sig_connected(True) を出す。
        """
        if not self._connection_key:
            # 通常は show_setup_dialog() が先に呼ばれる想定
            type(self)._instance_counter += 1
            self._connection_key = f"DummySimulated-{type(self)._instance_counter}"

        self._connected = True
        self.sig_connected.emit(True)
        # 初期状態を通知
        self._emit_state_changed()
        return True

    def disconnect(self) -> None:
        self._connected = False
        self.sig_connected.emit(False)

    def get_connection_key(self) -> str:
        return self._connection_key or "DummySimulated"

    # ---- チャンネル情報 ----

    def get_channels(self) -> list[dict]:
        # CH1 / CH2 の 2ch を固定で返す
        return [
            {"id": "CH1", "name": "CH1"},
            {"id": "CH2", "name": "CH2"},
        ]

    # ---- パラメータ設定 ----

    def set_freq(self, ch_id: str, value_hz: float) -> None:
        ch = self._channels.get(ch_id)
        if ch is None:
            return
        ch["freq"] = float(value_hz)
        self._emit_state_changed()

    def set_amp(self, ch_id: str, value_vpp: float) -> None:
        ch = self._channels.get(ch_id)
        if ch is None:
            return
        ch["amp"] = float(value_vpp)
        self._emit_state_changed()

    def set_offset(self, ch_id: str, value_v: float) -> None:
        ch = self._channels.get(ch_id)
        if ch is None:
            return
        ch["offset"] = float(value_v)
        self._emit_state_changed()

    def set_waveform(self, ch_id: str, wave: str) -> None:
        ch = self._channels.get(ch_id)
        if ch is None:
            return
        # wave は "sine", "square", "triangle", "sawtooth" 等を想定
        ch["waveform"] = str(wave)
        self._emit_state_changed()

    # ---- ON/OFF ----

    def set_enabled(self, ch_id: str, enabled: bool) -> None:
        ch = self._channels.get(ch_id)
        if ch is None:
            return
        ch["enabled"] = bool(enabled)
        self._emit_state_changed()

    def get_enabled(self, ch_id: str) -> bool:
        ch = self._channels.get(ch_id)
        if ch is None:
            return False
        return bool(ch.get("enabled", False))

    # ---- 状態問い合わせ / 安全系 ----

    def query_status(self) -> Dict[str, Any]:
        """
        現在の内部状態を dict で返す。
        GalvoPane 側は state["channels"][ch_id] を参照する前提。
        """
        state: Dict[str, Any] = {"channels": {}}
        for ch_id, ch_state in self._channels.items():
            state["channels"][ch_id] = {
                "enabled": bool(ch_state.get("enabled", False)),
                "waveform": ch_state.get("waveform"),
                "freq": float(ch_state.get("freq", 0.0)),
                "amp": float(ch_state.get("amp", 0.0)),
                "offset": float(ch_state.get("offset", 0.0)),
            }
        return state

    def emergency_shutdown(self) -> None:
        """
        全チャンネル OFF にするだけ。
        """
        for ch_state in self._channels.values():
            ch_state["enabled"] = False
        self._emit_state_changed()

    # ---- 内部 ----

    def _emit_state_changed(self) -> None:
        try:
            self.sig_state_changed.emit(self.query_status())
        except Exception:
            pass


def get_backend_class():
    """GalvoPane から呼ばれるファクトリ"""
    return DummySimulatedGalvoBackend
