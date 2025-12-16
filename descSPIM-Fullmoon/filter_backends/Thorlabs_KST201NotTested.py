# -*- coding: utf-8 -*-
"""
Thorlabs_KST201.py

Thorlabs KST201 (KCube Stepper) を用いてフィルターホイールを回転させる
Filter 用 backend 実装。

- Kinesis (.NET) KCubeStepper を使用。
- 単純に 1 周 360° を num_slots で等分し、
  slot1 → 0 deg, slot2 → 360/num_slots deg, ... として扱う。

IFilterBackend の正式仕様:
query_status() は以下の dict を返す:
{
    "position": int,      # 現在位置 (1..N) または 0（未設定）
    "num_slots": int,     # 総スロット数
    "slot_names": {       # スロット番号 → 表示名
        1: "slot1",
        2: "slot2",
        ...
    },
    "busy": bool          # 移動中かどうか
}
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from contextlib import contextmanager
from typing import Dict, Any

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QSettings

import clr
from System import Decimal as SysDecimal
from System.Globalization import CultureInfo

from filter_backends.filter_backend_base import IFilterBackend


# ---- Kinesis (.NET) 用設定 ----
KINESIS_ROOT = r"C:\Program Files\Thorlabs\Kinesis"
KINESIS_LIBDIR = KINESIS_ROOT  # DLL がここにある前提

if os.path.isdir(KINESIS_LIBDIR):
    try:
        os.add_dll_directory(KINESIS_LIBDIR)
    except Exception:
        # 古い Python / Windows の場合は PATH にある前提
        pass
else:
    print(f"[ThorlabsKST201Backend] warning: KINESIS_LIBDIR not found: {KINESIS_LIBDIR}")

_KINESIS_LOADED = False

# ensure_kinesis_loaded() 内でセットされるグローバル参照
DeviceManagerCLI = None
KCubeStepper = None
VelocityParameters = None
MotorDirection = None


@contextmanager
def pushd(p: str):
    cur = os.getcwd()
    os.chdir(p)
    try:
        yield
    finally:
        os.chdir(cur)


def _mkdec(x) -> SysDecimal:
    """Decimal.Parse + InvariantCulture で Real Units (deg 等) を渡す。"""
    return SysDecimal.Parse(str(x), CultureInfo.InvariantCulture)


def ensure_kinesis_loaded():
    """
    Kinesis の .NET DLL をプロセス全体で一度だけ読み込む。
    複数 backend インスタンスから呼ばれても安全。
    """
    global _KINESIS_LOADED
    global DeviceManagerCLI, KCubeStepper, VelocityParameters, MotorDirection

    if _KINESIS_LOADED:
        return

    if not os.path.isdir(KINESIS_LIBDIR):
        raise RuntimeError(f"KINESIS_LIBDIR not found: {KINESIS_LIBDIR}")

    kdir = Path(KINESIS_LIBDIR)

    # --- 実際に存在する CLI DLL をフルパス指定で読み込む ---
    clr.AddReference(str(kdir / "Thorlabs.MotionControl.DeviceManagerCLI.dll"))
    clr.AddReference(str(kdir / "Thorlabs.MotionControl.GenericMotorCLI.dll"))
    clr.AddReference(str(kdir / "Thorlabs.MotionControl.KCube.StepperMotorCLI.dll"))

    # .NET 側の型を import
    from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI as _DM
    from Thorlabs.MotionControl.KCube.StepperMotorCLI import KCubeStepper as _KC

    try:
        from Thorlabs.MotionControl.GenericMotorCLI.ControlParameters import (
            VelocityParameters as _VP,
        )
    except Exception as e:
        raise RuntimeError(
            "VelocityParameters not found in GenericMotorCLI.ControlParameters. "
            "Check Kinesis installation."
        ) from e

    try:
        from Thorlabs.MotionControl.GenericMotorCLI import MotorDirection as _MD
    except Exception as e:
        raise RuntimeError(
            "MotorDirection not found in GenericMotorCLI. Check Kinesis installation."
        ) from e

    DeviceManagerCLI = _DM
    KCubeStepper = _KC
    VelocityParameters = _VP
    MotorDirection = _MD

    _KINESIS_LOADED = True


class ThorlabsKST201Backend(IFilterBackend):
    """
    Thorlabs KST201 (KCube Stepper) を用いたフィルターホイール backend。

    - 1 デバイス = 1 軸回転フィルターホイールとみなす。
    - 単位は Kinesis 側で「度 (deg)」に設定されている前提。
    """

    SETTINGS_GROUP_BASE = "FilterBackend/Thorlabs_KST201"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.serial: str = ""
        self.device = None  # type: ignore[assignment]

        self._connected: bool = False
        self._busy: bool = False

        # スロット関連
        self._num_slots: int = 6
        self._slot_names: Dict[int, str] = {i: f"slot{i}" for i in range(1, self._num_slots + 1)}
        self._position: int = 0  # 0 = 未設定

        # 設定読み込み
        self._load_settings()

    # ------------------------------------------------------------------
    # 設定の保存 / 読み込み
    # ------------------------------------------------------------------
    def _load_settings(self):
        settings = QSettings("LabSuite", "FilterControl")
        settings.beginGroup(self.SETTINGS_GROUP_BASE)

        self.serial = settings.value("serial", self.serial, str)

        num_slots = settings.value("num_slots", self._num_slots, int)
        if isinstance(num_slots, str):
            try:
                num_slots = int(num_slots)
            except ValueError:
                num_slots = self._num_slots
        self._num_slots = max(1, num_slots)

        # スロット名
        slot_names: Dict[int, str] = {}
        for i in range(1, self._num_slots + 1):
            key = f"slot_name_{i}"
            default = f"slot{i}"
            name = settings.value(key, default, str)
            slot_names[i] = name or default
        self._slot_names = slot_names

        settings.endGroup()

    def _save_settings(self):
        settings = QSettings("LabSuite", "FilterControl")
        settings.beginGroup(self.SETTINGS_GROUP_BASE)

        settings.setValue("serial", self.serial)
        settings.setValue("num_slots", self._num_slots)
        for i in range(1, self._num_slots + 1):
            settings.setValue(f"slot_name_{i}", self._slot_names.get(i, f"slot{i}"))

        settings.endGroup()
        settings.sync()

    # ------------------------------------------------------------------
    # IFilterBackend: 接続前設定
    # ------------------------------------------------------------------
    def show_setup_dialog(self, parent=None) -> bool:
        """
        KST201 用設定ダイアログ:
        - Serial
        - Slot 数
        - 各 slot 名
        """
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("Thorlabs KST201 filter wheel setup")

        layout = QtWidgets.QVBoxLayout(dlg)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        # Serial
        ed_serial = QtWidgets.QLineEdit()
        ed_serial.setPlaceholderText("2600xxxx")
        ed_serial.setText(self.serial or "")
        form.addRow("Serial:", ed_serial)

        # Slot 数
        spin_slots = QtWidgets.QSpinBox()
        spin_slots.setRange(1, 24)
        spin_slots.setValue(self._num_slots)
        form.addRow("Number of slots:", spin_slots)

        # Slot 名編集エリア
        group_names = QtWidgets.QGroupBox("Slot names")
        names_layout = QtWidgets.QFormLayout(group_names)
        layout.addWidget(group_names)

        slot_edits: Dict[int, QtWidgets.QLineEdit] = {}

        def rebuild_slot_rows(n: int):
            # 既存 row をクリア
            while names_layout.rowCount() > 0:
                names_layout.removeRow(0)
            slot_edits.clear()
            # n 個の行を再構築
            for i in range(1, n + 1):
                label = QtWidgets.QLabel(f"Slot {i}:")
                edit = QtWidgets.QLineEdit()
                edit.setText(self._slot_names.get(i, f"slot{i}"))
                names_layout.addRow(label, edit)
                slot_edits[i] = edit

        rebuild_slot_rows(self._num_slots)

        def on_slots_changed(value: int):
            rebuild_slot_rows(value)

        spin_slots.valueChanged.connect(on_slots_changed)

        # ボタン
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dlg,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False

        serial = ed_serial.text().strip()
        if not serial:
            self.sig_error.emit("serial is required")
            return False

        self.serial = serial
        self._num_slots = spin_slots.value()

        # スロット名を反映
        new_names: Dict[int, str] = {}
        for i in range(1, self._num_slots + 1):
            edit = slot_edits.get(i)
            if edit is not None:
                name = edit.text().strip() or f"slot{i}"
            else:
                name = f"slot{i}"
            new_names[i] = name
        self._slot_names = new_names

        # 設定保存
        self._save_settings()

        # 接続を試みる
        ok = self.connect()
        return ok

    # ------------------------------------------------------------------
    # KST201 接続 / 切断
    # ------------------------------------------------------------------
    def _connect_device(self):
        if not self.serial:
            raise ValueError("serial not set")

        ensure_kinesis_loaded()

        last_err = None
        self._connected = False
        self.device = None

        for i in range(5):
            try:
                DeviceManagerCLI.BuildDeviceList()
                dev = KCubeStepper.CreateKCubeStepper(self.serial)
                if dev is None:
                    raise RuntimeError(
                        f"KCubeStepper.CreateKCubeStepper({self.serial}) returned None"
                    )

                dev.Connect(self.serial)

                try:
                    dev.WaitForSettingsInitialized(5000)
                except Exception:
                    pass

                time.sleep(0.2)
                dev.StartPolling(250)
                time.sleep(0.2)
                dev.EnableDevice()
                time.sleep(0.3)

                try:
                    dev.LoadMotorConfiguration(self.serial)
                except Exception:
                    pass

                # Home 実行（タイムアウト 60 s）
                try:
                    dev.Home(60000)
                except Exception:
                    # Home が未設定の構成でもそのまま続行
                    pass

                self.device = dev
                self._connected = True
                break

            except Exception as e_try:
                last_err = e_try
                time.sleep(1.0)

        if not self._connected or self.device is None:
            raise RuntimeError(f"failed to connect to KST201 ({self.serial}): {last_err}")

        # Home 後は slot1 にいるものとみなす
        self._position = 1

    # ------------------------------------------------------------------
    # IFilterBackend: 接続 / 切断
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        try:
            self._connect_device()
            self.sig_connected.emit(True)
            self.sig_state_changed.emit(self.query_status())
            return True
        except Exception as e:
            self.sig_error.emit(f"connect: {e}")
            self._connected = False
            self.device = None
            self.sig_connected.emit(False)
            return False

    def disconnect(self) -> None:
        try:
            if self.device is not None:
                try:
                    self.device.StopPolling()
                except Exception:
                    pass
                try:
                    self.device.Disconnect()
                except Exception:
                    pass
                self.device = None
            self._connected = False
            self._busy = False
            self.sig_connected.emit(False)
            self.sig_state_changed.emit(self.query_status())
        except Exception as e:
            self.sig_error.emit(f"disconnect: {e}")

    # ------------------------------------------------------------------
    # IFilterBackend: 構造取得
    # ------------------------------------------------------------------
    def get_num_slots(self) -> int:
        return self._num_slots

    def get_slot_names(self) -> Dict[int, str]:
        return dict(self._slot_names)

    # ------------------------------------------------------------------
    # 内部: スロット → 角度変換
    # ------------------------------------------------------------------
    def _slot_to_angle_deg(self, slot: int) -> float:
        """
        slot (1..N) を 0..360° に割り当てる。
        slot1: 0°, slot2: 360/N°, ...
        """
        if self._num_slots <= 0:
            return 0.0
        # slot1 を 0°, slot2 を 360/N°, ...
        return 360.0 * (slot - 1) / float(self._num_slots)

    # ------------------------------------------------------------------
    # IFilterBackend: 位置制御
    # ------------------------------------------------------------------
    def set_position(self, slot: int) -> None:
        if not self._connected or self.device is None:
            self.sig_error.emit("set_position: not connected")
            return

        if slot < 1 or slot > self._num_slots:
            self.sig_error.emit(f"set_position: invalid slot {slot}")
            return

        angle = self._slot_to_angle_deg(slot)
        self._busy = True
        self.sig_state_changed.emit(self.query_status())

        try:
            # Real Units が deg に設定されている前提で、絶対角度へ移動
            target = _mkdec(angle)
            try:
                self.device.MoveTo(target, 60000)
            except Exception:
                self.device.MoveTo(target)

            self._position = slot
        except Exception as e:
            self.sig_error.emit(f"set_position: {e}")
        finally:
            self._busy = False
            self.sig_state_changed.emit(self.query_status())

    def get_position(self) -> int:
        return self._position

    # ------------------------------------------------------------------
    # IFilterBackend: 状態取得
    # ------------------------------------------------------------------
    def query_status(self) -> Dict[str, Any]:
        return {
            "position": int(self._position),
            "num_slots": int(self._num_slots),
            "slot_names": dict(self._slot_names),
            "busy": bool(self._busy),
        }

    # ------------------------------------------------------------------
    # IFilterBackend: 安全系
    # ------------------------------------------------------------------
    def emergency_shutdown(self) -> None:
        if not self._connected or self.device is None:
            return
        try:
            try:
                self.device.StopProfiled()
            except Exception:
                pass
        except Exception as e:
            self.sig_error.emit(f"emergency_shutdown: {e}")
        finally:
            self._busy = False
            self.sig_state_changed.emit(self.query_status())

    # ------------------------------------------------------------------
    # IFilterBackend: スロット名更新 (FilterPane から呼ばれる)
    # ------------------------------------------------------------------
    def update_slot_name(self, slot: int, name: str) -> None:
        if slot < 1 or slot > self._num_slots:
            return
        self._slot_names[slot] = name or f"slot{slot}"
        self._save_settings()
        self.sig_state_changed.emit(self.query_status())


def get_backend_class():
    """FilterPane から呼ばれるファクトリ用フック。"""
    return ThorlabsKST201Backend
