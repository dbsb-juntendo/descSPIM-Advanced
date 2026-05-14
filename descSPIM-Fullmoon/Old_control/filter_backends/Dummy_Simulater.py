# -*- coding: utf-8 -*-
"""
filter_backends/Dummy_Simulater.py

ダミーの電動フィルターチェンジャー用 Backend。
- IFilterBackend を実装し、スロットを持つ。
- set_position() すると busy=True になり、一定時間後に移動完了。
- 実際のハードウェアは一切制御しないテスト用 backend。
"""

from __future__ import annotations

from typing import Dict

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QObject, QTimer

from filter_backends.filter_backend_base import IFilterBackend


class DummySimulatedFilterBackend(IFilterBackend):
    """
    スロットを持つダミー filter backend。
    """

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._connected: bool = False
        self._num_slots: int = 6
        self._position: int = 1
        self._slot_names: Dict[int, str] = {}
        self._busy: bool = False

        self._move_time_ms: int = 400    # スロット移動にかかる擬似時間
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_move_finished)

        self._slot_names = {i: f"Slot {i}" for i in range(1, self._num_slots + 1)}

    # ---- 接続前設定 ----
    def show_setup_dialog(self, parent=None) -> bool:
        """
        スロット数と移動時間を設定する簡単なダイアログ。
        """

        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("Dummy filter simulator setup")

        lbl_slots = QtWidgets.QLabel("Number of slots:", dlg)
        spin_slots = QtWidgets.QSpinBox(dlg)
        spin_slots.setRange(1, 12)
        spin_slots.setValue(self._num_slots)

        lbl_time = QtWidgets.QLabel("Move time per step (ms):", dlg)
        spin_time = QtWidgets.QSpinBox(dlg)
        spin_time.setRange(10, 5000)
        spin_time.setSingleStep(50)
        spin_time.setValue(self._move_time_ms)

        btn_ok = QtWidgets.QPushButton("OK", dlg)
        btn_cancel = QtWidgets.QPushButton("Cancel", dlg)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)

        layout = QtWidgets.QFormLayout(dlg)
        layout.addRow(lbl_slots, spin_slots)
        layout.addRow(lbl_time, spin_time)
        layout.addRow(btn_layout)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False

        self._num_slots = int(spin_slots.value())
        self._move_time_ms = int(spin_time.value())
        if self._position > self._num_slots:
            self._position = self._num_slots
        self._slot_names = {i: f"Slot {i}" for i in range(1, self._num_slots + 1)}
        return True

    # ---- connect / disconnect ----
    def connect(self) -> bool:
        self._connected = True
        self._busy = False
        self.sig_connected.emit(True)
        self.sig_state_changed.emit(self.query_status())
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._busy = False
        if self._timer.isActive():
            self._timer.stop()
        self.sig_connected.emit(False)

    # ---- 構造 ----
    def get_num_slots(self) -> int:
        return int(self._num_slots)

    def get_slot_names(self) -> Dict[int, str]:
        return dict(self._slot_names)

    # ---- パラメータ設定 ----
    def set_position(self, slot: int) -> None:
        """
        指定スロットへ移動を開始（ダミーなので QTimer で busy を再現）。
        """
        if not self._connected:
            self.sig_error.emit("DummySimulatedFilterBackend: not connected")
            return

        slot = int(slot)
        if slot < 1 or slot > self._num_slots:
            self.sig_error.emit(f"DummySimulatedFilterBackend: invalid slot {slot}")
            return

        if slot == self._position:
            # すでにそのスロットなので何もしないが、状態だけ通知
            self._busy = False
            self.sig_state_changed.emit(self.query_status())
            return

        # 擬似移動開始
        self._busy = True
        self._target_position = slot  # type: ignore[attr-defined]
        self.sig_state_changed.emit(self.query_status())

        if self._timer.isActive():
            self._timer.stop()
        self._timer.start(self._move_time_ms)

    def _on_move_finished(self):
        # タイマー終了で位置更新
        target = getattr(self, "_target_position", self._position)
        self._position = int(target)
        self._busy = False
        self.sig_state_changed.emit(self.query_status())

    def get_position(self) -> int:
        return int(self._position)

    # ---- 状態取得 ----
    def query_status(self) -> dict:
        return {
            "position": int(self._position),
            "num_slots": int(self._num_slots),
            "slot_names": dict(self._slot_names),
            "busy": bool(self._busy),
        }

    # ---- 安全系 ----
    def emergency_shutdown(self) -> None:
        if self._timer.isActive():
            self._timer.stop()
        self._busy = False
        self.sig_state_changed.emit(self.query_status())

    # ---- スロット名更新（FilterPane から呼ばれる想定）----
    def update_slot_name(self, slot: int, name: str) -> None:
        slot = int(slot)
        if 1 <= slot <= self._num_slots:
            self._slot_names[slot] = str(name)
            self.sig_state_changed.emit(self.query_status())


def get_backend_class():
    """
    FilterPane 側から動的ロードされるエントリポイント。
    """
    return DummySimulatedFilterBackend
