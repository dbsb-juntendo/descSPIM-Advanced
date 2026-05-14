# Manual_Change.py
# -*- coding: utf-8 -*-
"""
filter_backends/Manual_Change.py

手動フィルタ交換用 Backend（フィルターチェンジャー非接続）。
- スロット数だけを持つ「論理的なフィルターチェンジャー」。
- 実ハードウェアは一切制御せず、set_position() しても内部状態を更新するだけ。
- FilterPane 側から見ると「num_slots > 0」で、
  スロット名は FilterPane のダイアログで入力・保存される。
"""

from __future__ import annotations

from typing import Dict

from PySide6 import QtWidgets

from filter_backends.filter_backend_base import IFilterBackend


class ManualChangeBackend(IFilterBackend):
    """
    フィルターチェンジャーが存在しない構成で使用するバックエンド。

    - スロット数だけを管理（num_slots >= 1）。
    - get_slot_names() は単純なデフォルト名を返す（"Filter 1", ...）。
      実際の表示名は FilterPane 側のダイアログで上書きされる。
    - set_position(slot) ではハードを動かさず、内部 position を更新して
      sig_state_changed を emit するだけ。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected: bool = False
        self._busy: bool = False

        self._num_slots: int = 0
        self._position: int = 1
        self._slot_names: Dict[int, str] = {}

    # ---- 接続前設定 ----
    def show_setup_dialog(self, parent=None) -> bool:
        """
        ・マニュアルで使うフィルタ（スロット）の数だけを聞く。
        ・名前入力は FilterPane 側のダイアログで行う。
        """
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("Manual filter change setup")

        lbl_info = QtWidgets.QLabel(
            "This backend does not control any motorized filter changer.\n"
            "You will change filters manually.\n\n"
            "Please specify how many filters (slots) you will use.",
            dlg,
        )
        lbl_info.setWordWrap(True)

        lbl_slots = QtWidgets.QLabel("Number of filters (slots):", dlg)
        spin_slots = QtWidgets.QSpinBox(dlg)
        spin_slots.setRange(1, 12)
        # 初回は 4 をデフォルト値にする（好みで変更可）
        spin_slots.setValue(self._num_slots if self._num_slots >= 1 else 4)

        btn_ok = QtWidgets.QPushButton("OK", dlg)
        btn_cancel = QtWidgets.QPushButton("Cancel", dlg)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)

        layout = QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(lbl_info)
        form = QtWidgets.QFormLayout()
        form.addRow(lbl_slots, spin_slots)
        layout.addLayout(form)
        layout.addLayout(btn_layout)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False

        self._num_slots = int(spin_slots.value())
        if self._num_slots < 1:
            self._num_slots = 1
        if self._position > self._num_slots:
            self._position = self._num_slots

        # デフォルト名を更新（FilterPane 側で上書きされる前提）
        self._slot_names = {
            i: f"Filter {i}" for i in range(1, self._num_slots + 1)
        }
        return True

    # ---- connect / disconnect ----
    def connect(self) -> bool:
        """
        実ハードは無いのでフラグ更新と状態通知だけ。
        """
        if self._num_slots < 1:
            # 念のため 1 スロットだけ確保
            self._num_slots = 1
            self._slot_names = {1: "Filter 1"}

        self._connected = True
        self._busy = False
        self.sig_connected.emit(True)
        self.sig_state_changed.emit(self.query_status())
        return True

    def disconnect(self) -> None:
        self._connected = False
        self._busy = False
        self.sig_connected.emit(False)

    # ---- 構造 ----
    def get_num_slots(self) -> int:
        return int(self._num_slots)

    def get_slot_names(self) -> Dict[int, str]:
        # FilterPane 側の _ensure_slot_names で上書きされるので、
        # ここではデフォルト名だけ返す。
        if not self._slot_names and self._num_slots >= 1:
            self._slot_names = {
                i: f"Filter {i}" for i in range(1, self._num_slots + 1)
            }
        return dict(self._slot_names)

    # ---- パラメータ設定 ----
    def set_position(self, slot: int) -> None:
        """
        指定スロットを「選択されたことにする」だけで、
        実際のフィルタ移動はユーザーが手で行う想定。
        """
        if not self._connected:
            self.sig_error.emit("ManualChangeBackend: not connected")
            return

        slot = int(slot)
        if slot < 1 or slot > self._num_slots:
            self.sig_error.emit(f"ManualChangeBackend: invalid slot {slot}")
            return

        # ハードを動かさず、内部状態だけ更新して通知
        self._position = slot
        self._busy = False
        self.sig_state_changed.emit(self.query_status())

    def get_position(self) -> int:
        return int(self._position)

    # ---- 状態取得 ----
    def query_status(self) -> dict:
        return {
            "position": int(self._position) if self._num_slots >= 1 else 0,
            "num_slots": int(self._num_slots),
            "slot_names": dict(self._slot_names),
            "busy": bool(self._busy),
        }

    # ---- 安全系 ----
    def emergency_shutdown(self) -> None:
        self._busy = False
        # 状態だけ再通知しておく
        self.sig_state_changed.emit(self.query_status())

    # ---- FilterPane からのスロット名更新 ----
    def update_slot_name(self, slot: int, name: str) -> None:
        slot = int(slot)
        if slot < 1 or slot > self._num_slots:
            return
        if not name:
            return
        self._slot_names[slot] = str(name)
        # 名称変更後の状態を通知（UI を更新させるため）
        self.sig_state_changed.emit(self.query_status())


def get_backend_class():
    """
    FilterPane 側から動的ロードされるエントリポイント。
    """
    return ManualChangeBackend
