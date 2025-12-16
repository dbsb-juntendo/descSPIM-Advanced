# laser_backends/Dummy_Simulated.py
# -*- coding: utf-8 -*-

from typing import Optional, Dict, Any, List
from PySide6.QtWidgets import QWidget, QDialog, QVBoxLayout, QLabel, QPushButton
from PySide6.QtCore import QObject, Signal

from .laser_backend_base import ILaserBackend


class DummySimulatedBackend(ILaserBackend):
    """
    どの PC でも動作する仮想レーザー。
    405, 488, 561, 640 nm の4ラインを持つ。
    set_enabled, set_power_mw は内部変数を書き換えるだけ。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 仮想ライン設定
        self._lines = [
            {"id": "405", "wavelength_nm": 405, "name": "405 nm"},
            {"id": "488", "wavelength_nm": 488, "name": "488 nm"},
            {"id": "561", "wavelength_nm": 561, "name": "561 nm"},
            {"id": "640", "wavelength_nm": 640, "name": "640 nm"},
        ]
        self._enabled: Dict[str, bool] = {L["id"]: False for L in self._lines}
        self._power: Dict[str, float] = {L["id"]: 0.0 for L in self._lines}

        self._connected = False

    # ---- 必須 API ----
    def show_setup_dialog(self, parent: Optional[QWidget] = None) -> bool:
        # ダイアログ不要 → 即 True
        return True

    def get_capabilities(self) -> dict:
        return {"dummy": True}

    def get_lines(self) -> list:
        return self._lines

    def connect(self) -> bool:
        self._connected = True
        self.sig_connected.emit(True)
        return True

    def disconnect(self) -> None:
        self._connected = False
        self.sig_connected.emit(False)

    def get_connection_key(self) -> str:
        return "dummy"

    def set_enabled(self, line_id: str, enabled: bool) -> None:
        self._enabled[line_id] = enabled

    def get_enabled(self, line_id: str) -> bool:
        return self._enabled.get(line_id, False)

    def set_power_mw(self, line_id: str, power_mw: float) -> None:
        lo, hi = self.get_power_range(line_id)
        if power_mw < lo or power_mw > hi:
            raise ValueError(f"Power must be in {lo}–{hi} mW")
        self._power[line_id] = power_mw

    def get_power_mw(self, line_id: str) -> float:
        return self._power.get(line_id, 0.0)

    def get_power_range(self, line_id: str) -> tuple:
        """
        仮想レンジ：0–500 mW
        """
        return (0.0, 500.0)

    def set_master_enable(self, enabled: bool) -> None:
        for k in self._enabled:
            self._enabled[k] = enabled

    def emergency_shutdown(self) -> None:
        for k in self._enabled:
            self._enabled[k] = False

    def query_status(self) -> dict:
        return {
            "connected": self._connected,
            "enabled": dict(self._enabled),
            "power": dict(self._power),
        }


def get_backend_class():
    return DummySimulatedBackend
