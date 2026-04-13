# -*- coding: utf-8 -*-
"""
Thorlabs_KST201NotTested.py
"""

import os
import sys
import time
from typing import Dict, Any

from PySide6 import QtWidgets
from PySide6.QtCore import QSettings

import clr
from System import Decimal

from filter_backends.filter_backend_base import IFilterBackend


KINESIS_ROOT = r"C:\Program Files\Thorlabs\Kinesis"

DeviceManagerCLI = None
DeviceConfiguration = None
KCubeStepper = None
_KINESIS_LOADED = False


def _log(msg: str) -> None:
    print(f"[Thorlabs_KST201Backend] {msg}")


def ensure_kinesis_loaded():
    global _KINESIS_LOADED, DeviceManagerCLI, DeviceConfiguration, KCubeStepper

    if _KINESIS_LOADED:
        return

    if not os.path.isdir(KINESIS_ROOT):
        raise RuntimeError(f"KINESIS_ROOT not found: {KINESIS_ROOT}")

    if KINESIS_ROOT not in sys.path:
        sys.path.append(KINESIS_ROOT)
    os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + KINESIS_ROOT

    try:
        os.add_dll_directory(KINESIS_ROOT)
    except Exception:
        pass

    clr.AddReference(os.path.join(KINESIS_ROOT, "Thorlabs.MotionControl.DeviceManagerCLI.dll"))
    clr.AddReference(os.path.join(KINESIS_ROOT, "Thorlabs.MotionControl.KCube.StepperMotorCLI.dll"))

    from Thorlabs.MotionControl.DeviceManagerCLI import (
        DeviceManagerCLI as _DM,
        DeviceConfiguration as _DC,
    )
    from Thorlabs.MotionControl.KCube.StepperMotorCLI import KCubeStepper as _KC

    DeviceManagerCLI = _DM
    DeviceConfiguration = _DC
    KCubeStepper = _KC

    _KINESIS_LOADED = True
    _log("Kinesis DLL loaded successfully")


def _to_decimal_deg(x: float) -> Decimal:
    return Decimal(int(round(x)))


class ThorlabsKST201Backend(IFilterBackend):
    SETTINGS_GROUP_BASE = "FilterBackend/Thorlabs_KST201"

    def __init__(self, parent=None):
        super().__init__(parent)

        self.serial: str = ""
        self.device = None

        self._connected: bool = False
        self._busy: bool = False
        self._position: int = 0
        self._num_slots: int = 6
        self._slot_names: Dict[int, str] = {
            i: f"slot{i}" for i in range(1, self._num_slots + 1)
        }
        self._last_error: str = ""

        self._load_settings()

    # --------------------------------------------------------
    # settings
    # --------------------------------------------------------
    def _load_settings(self):
        settings = QSettings("LabSuite", "FilterControl")
        settings.beginGroup(self.SETTINGS_GROUP_BASE)

        self.serial = str(settings.value("serial", self.serial, str) or "").strip()

        num_slots = settings.value("num_slots", self._num_slots, int)
        if isinstance(num_slots, str):
            try:
                num_slots = int(num_slots)
            except ValueError:
                num_slots = self._num_slots
        self._num_slots = max(1, int(num_slots))

        slot_names = {}
        for i in range(1, self._num_slots + 1):
            key = f"slot_name_{i}"
            default = f"slot{i}"
            slot_names[i] = settings.value(key, default, str) or default
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

    # --------------------------------------------------------
    # setup dialog
    # --------------------------------------------------------
    def show_setup_dialog(self, parent=None) -> bool:
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("Thorlabs KST201 filter wheel setup")

        layout = QtWidgets.QVBoxLayout(dlg)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        ed_serial = QtWidgets.QLineEdit()
        ed_serial.setPlaceholderText("2600xxxx")
        ed_serial.setText(self.serial or "")
        form.addRow("Serial:", ed_serial)

        spin_slots = QtWidgets.QSpinBox()
        spin_slots.setRange(1, 24)
        spin_slots.setValue(self._num_slots)
        form.addRow("Number of slots:", spin_slots)

        group_names = QtWidgets.QGroupBox("Slot names")
        names_layout = QtWidgets.QFormLayout(group_names)
        layout.addWidget(group_names)

        slot_edits: Dict[int, QtWidgets.QLineEdit] = {}

        def rebuild_slot_rows(n: int):
            while names_layout.rowCount() > 0:
                names_layout.removeRow(0)
            slot_edits.clear()
            for i in range(1, n + 1):
                edit = QtWidgets.QLineEdit()
                edit.setText(self._slot_names.get(i, f"slot{i}"))
                names_layout.addRow(f"Slot {i}:", edit)
                slot_edits[i] = edit

        rebuild_slot_rows(self._num_slots)
        spin_slots.valueChanged.connect(rebuild_slot_rows)

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
            self._last_error = "serial is required"
            try:
                self.sig_error.emit(self._last_error)
            except Exception:
                pass
            return False

        self.serial = serial
        self._num_slots = spin_slots.value()

        new_names: Dict[int, str] = {}
        for i in range(1, self._num_slots + 1):
            name = slot_edits[i].text().strip() if i in slot_edits else ""
            new_names[i] = name or f"slot{i}"
        self._slot_names = new_names

        self._save_settings()

        # ここが重要:
        # 接続はここではしない。FilterPane 側に任せる。
        return True

    # --------------------------------------------------------
    # connection helpers
    # --------------------------------------------------------
    def _is_alive(self) -> bool:
        return self._connected and (self.device is not None)

    def _connect_device(self):
        if not self.serial:
            raise ValueError("serial not set")

        ensure_kinesis_loaded()

        last_err = None

        for _ in range(3):
            try:
                _log(f"Building device list for serial={self.serial}")
                DeviceManagerCLI.BuildDeviceList()
                time.sleep(0.2)

                dev = KCubeStepper.CreateKCubeStepper(self.serial)
                if dev is None:
                    raise RuntimeError(
                        f"KCubeStepper.CreateKCubeStepper({self.serial}) returned None"
                    )

                _log("Connecting device")
                dev.Connect(self.serial)
                time.sleep(0.5)

                use_file_settings = (
                    DeviceConfiguration.DeviceSettingsUseOptionType.UseFileSettings
                )
                _log("Loading motor configuration with UseFileSettings")
                dev.LoadMotorConfiguration(self.serial, use_file_settings)

                _log("StartPolling")
                dev.StartPolling(250)
                time.sleep(0.5)

                _log("EnableDevice")
                dev.EnableDevice()
                time.sleep(0.5)

                _log("Home start")
                dev.Home(60000)
                time.sleep(0.5)
                _log("Home finished")

                self.device = dev
                self._connected = True
                self._position = 1
                self._last_error = ""
                return

            except Exception as e:
                last_err = e
                _log(f"connect attempt failed: {e}")
                time.sleep(1.0)

        raise RuntimeError(f"failed to connect to KST201 ({self.serial}): {last_err}")

    # --------------------------------------------------------
    # connect/disconnect
    # --------------------------------------------------------
    def connect(self) -> bool:
        # すでに接続済みなら、そのまま成功扱いにする
        if self._is_alive():
            _log("connect() called but device is already connected; returning True")
            try:
                self.sig_connected.emit(True)
                self.sig_state_changed.emit(self.query_status())
            except Exception:
                pass
            return True

        try:
            self._connect_device()
            try:
                self.sig_connected.emit(True)
                self.sig_state_changed.emit(self.query_status())
            except Exception:
                pass
            return True

        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            self.device = None
            try:
                self.sig_error.emit(f"connect: {e}")
                self.sig_connected.emit(False)
                self.sig_state_changed.emit(self.query_status())
            except Exception:
                pass
            return False

    def disconnect(self) -> None:
        dev = self.device
        self.device = None
        self._connected = False
        self._busy = False

        if dev is not None:
            try:
                dev.StopPolling()
            except Exception:
                pass
            try:
                dev.Disconnect()
            except Exception:
                pass

        try:
            self.sig_connected.emit(False)
            self.sig_state_changed.emit(self.query_status())
        except Exception:
            pass

    # --------------------------------------------------------
    # backend api
    # --------------------------------------------------------
    def get_num_slots(self) -> int:
        return self._num_slots

    def get_slot_names(self) -> Dict[int, str]:
        return dict(self._slot_names)

    def _slot_to_angle_deg(self, slot: int) -> float:
        if self._num_slots <= 0:
            return 0.0
        return 360.0 * (slot - 1) / float(self._num_slots)

    def set_position(self, slot: int) -> None:
        if not self._is_alive():
            try:
                self.sig_error.emit("set_position: not connected")
            except Exception:
                pass
            return

        if slot < 1 or slot > self._num_slots:
            try:
                self.sig_error.emit(f"set_position: invalid slot {slot}")
            except Exception:
                pass
            return

        angle = self._slot_to_angle_deg(slot)

        self._busy = True
        try:
            self.sig_state_changed.emit(self.query_status())
        except Exception:
            pass

        try:
            target = _to_decimal_deg(angle)
            _log(f"Move filter to slot={slot}, angle={angle}")
            self.device.SetMoveAbsolutePosition(target)
            self.device.MoveAbsolute(60000)
            self._position = slot
            self._last_error = ""

        except Exception as e:
            self._last_error = str(e)
            try:
                self.sig_error.emit(f"set_position: {e}")
            except Exception:
                pass

        finally:
            self._busy = False
            try:
                self.sig_state_changed.emit(self.query_status())
            except Exception:
                pass

    def get_position(self) -> int:
        return self._position

    def query_status(self) -> Dict[str, Any]:
        return {
            "position": int(self._position),
            "num_slots": int(self._num_slots),
            "slot_names": dict(self._slot_names),
            "busy": bool(self._busy),
            "connected": bool(self._connected),
            "last_error": self._last_error,
        }

    def emergency_shutdown(self) -> None:
        if not self._is_alive():
            return
        try:
            try:
                self.device.StopImmediate()
            except Exception:
                pass
        except Exception as e:
            try:
                self.sig_error.emit(f"emergency_shutdown: {e}")
            except Exception:
                pass
        finally:
            self._busy = False
            try:
                self.sig_state_changed.emit(self.query_status())
            except Exception:
                pass

    def update_slot_name(self, slot: int, name: str) -> None:
        if slot < 1 or slot > self._num_slots:
            return
        self._slot_names[slot] = name or f"slot{slot}"
        self._save_settings()
        try:
            self.sig_state_changed.emit(self.query_status())
        except Exception:
            pass


def get_backend_class():
    return ThorlabsKST201Backend