# filter_backends/Thorlabs_EEL9.py
# -*- coding: utf-8 -*-

#---------------
# NOT TESTED!!!
#---------------

"""
Thorlabs Elliptec (ELLx 系) を用いた 4 スロット固定フィルターチェンジャー Backend.

- スロット数は常に 4。
- Home 位置を Slot 1 とみなす。
- JogForward / JogBackward によって Slot 間を移動する。
- Slot ボタン押下時には、現在位置との「差分回数」だけ Jog を発行する。
- 1 ステップごとに 1 秒待機する（応答が遅い前提の安全マージン）。

フィルター名は ManualChangeBackend と同様に FilterPane 側から
update_slot_name(...) で上書きされる想定。
"""

from __future__ import annotations

from typing import Dict
import time
import threading

from PySide6 import QtWidgets, QtSerialPort

from filter_backends.filter_backend_base import IFilterBackend

import clr

# 必要に応じてパスは環境に合わせて修正してください。
ELL_DLL_PATH = r"C:\Program Files\Thorlabs\Elliptec\Thorlabs.Elliptec.ELLO_DLL.dll"

_ELL_LOADED = False
_ELL_TYPES = None  # (ELLDevicePort, ELLDevices, ELLBaseDevice)


def _ensure_ell_loaded():
    """
    Elliptec の DLL と型を一度だけロードするヘルパ。
    """
    print("Start ensure load")    # Debug
    global _ELL_LOADED, _ELL_TYPES
    if not _ELL_LOADED:
        clr.AddReference(ELL_DLL_PATH)
        from Thorlabs.Elliptec.ELLO_DLL import ELLDevicePort, ELLDevices, ELLBaseDevice
        _ELL_TYPES = (ELLDevicePort, ELLDevices, ELLBaseDevice)
        _ELL_LOADED = True
        print("finish ensure load")    # Debug
    return _ELL_TYPES


class ThorlabsEEL9Backend(IFilterBackend):
    """
    Thorlabs Elliptec (ELLx) ベースの 4 スロットフィルターチェンジャー backend。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._connected: bool = False
        self._busy: bool = False

        # 4 スロット固定
        self._num_slots: int = 4
        self._position: int = 1  # Home (= Slot 1)
        self._slot_names: Dict[int, str] = {
            i: f"Filter {i}" for i in range(1, self._num_slots + 1)
        }

        # 通信関連
        self._com_port: str = "COM4"  # デフォルト。ダイアログで変更可。
        self._ell_device_port = None
        self._ell_devices = None
        self._dev = None  # AddressedDevice
        self._move_thread: threading.Thread | None = None

    # ---- 接続前設定 ----
    """
    def show_setup_dialog(self, parent=None) -> bool:
        
        #COM ポートだけを設定するダイアログ。
        #スロット数は 4 固定なので、ユーザーには見せない。
        
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("Thorlabs Elliptec filter setup")

        lbl_info = QtWidgets.QLabel(
            "This backend controls a 4-position Thorlabs Elliptec filter slider.\n"
            "Home position is treated as Slot 1.\n\n"
            "Please specify the COM port where the Elliptec device is connected.",
            dlg,
        )
        lbl_info.setWordWrap(True)

        lbl_com = QtWidgets.QLabel("COM port:", dlg)
        edit_com = QtWidgets.QLineEdit(dlg)
        edit_com.setText(self._com_port or "COM4")

        btn_ok = QtWidgets.QPushButton("OK", dlg)
        btn_cancel = QtWidgets.QPushButton("Cancel", dlg)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)

        form = QtWidgets.QFormLayout()
        form.addRow(lbl_com, edit_com)

        layout = QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(lbl_info)
        layout.addLayout(form)
        layout.addLayout(btn_layout)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False

        text = edit_com.text().strip()
        if not text:
            self.sig_error.emit("ThorlabsEEL9Backend: COM port is empty.")
            return False

        self._com_port = text
        return True
    """
    def show_setup_dialog(self, parent=None) -> bool:
        """
        COM ポートだけを設定するダイアログ。
        スロット数は 4 固定なので、ユーザーには見せない。
        """
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("Thorlabs Elliptec filter setup")

        lbl_info = QtWidgets.QLabel(
            "This backend controls a 4-position Thorlabs Elliptec filter slider.\n"
            "Home position is treated as Slot 1.\n\n"
            "Please select the COM port where the Elliptec device is connected.",
            dlg,
        )
        lbl_info.setWordWrap(True)

        lbl_com = QtWidgets.QLabel("COM port:", dlg)
        combo_com = QtWidgets.QComboBox(dlg)

        ports = QtSerialPort.QSerialPortInfo.availablePorts()
        port_names = [p.portName() for p in ports]

        if port_names:
            combo_com.addItems(port_names)
        else:
            combo_com.addItem(self._com_port or "COM4")

        current_port = self._com_port or "COM4"
        idx = combo_com.findText(current_port)
        if idx >= 0:
            combo_com.setCurrentIndex(idx)
        elif port_names:
            combo_com.setCurrentIndex(0)

        btn_ok = QtWidgets.QPushButton("OK", dlg)
        btn_cancel = QtWidgets.QPushButton("Cancel", dlg)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch(1)
        btn_layout.addWidget(btn_ok)
        btn_layout.addWidget(btn_cancel)

        form = QtWidgets.QFormLayout()
        form.addRow(lbl_com, combo_com)

        layout = QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(lbl_info)
        layout.addLayout(form)
        layout.addLayout(btn_layout)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False

        text = combo_com.currentText().strip()
        if not text:
            #self.sig_error.emit("ThorlabsEEL9Backend: COM port is empty.")
            print("EEL9: COM port is empty.")    # Debug
            return False

        self._com_port = text
        return True

    # ---- connect / disconnect ----
    def connect(self) -> bool:
        """
        Elliptec デバイスに接続し、Home を実行して Slot 1 に合わせる。
        """
        print("EEL9: Start connect")    # Debug
        if self._connected:
            return True

        try:
            ELLDevicePort, ELLDevices, ELLBaseDevice = _ensure_ell_loaded()
        except Exception as e:
            #self.sig_error.emit(f"ThorlabsEEL9Backend: failed to load ELLO DLL: {e}")
            print("EEL9: Error 1 for debug")    # Debug
            return False

        try:
            #self.sig_message.emit(
            #    f"Connecting Elliptec on {self._com_port} (this may take a few seconds)..."
            #)
            print(f"EEL9_com_port: {self._com_port}, taking a few seconds")    # Debug
            ELLDevicePort.Connect(self._com_port)
        except Exception as e:
            #self.sig_error.emit(
            #    f"ThorlabsEEL9Backend: failed to connect to {self._com_port}: {e}"
            #)
            print("EEL9: Error 2 for debug")    # Debug
            return False

        self._ell_device_port = ELLDevicePort
        self._ell_devices = ELLDevices()

        try:
            devices = self._ell_devices.ScanAddresses("0", "F")
        except Exception as e:
            #self.sig_error.emit(
            #    f"ThorlabsEEL9Backend: failed to scan Elliptec addresses: {e}"
            #)
            print("EEL9: Error 3 for debug")    # Debug
            return False

        if not devices:
            #self.sig_error.emit("ThorlabsEEL9Backend: no Elliptec devices found.")
            print("EEL9: No Elliptec devices found.")    # Debug
            return False

        dev = None
        for d in devices:
            try:
                if self._ell_devices.Configure(d):
                    dev = self._ell_devices.AddressedDevice(d[0])
                    break
            except Exception:
                # 他のアドレスで失敗しても、とりあえず次へ
                continue

        if dev is None:
            #self.sig_error.emit("ThorlabsEEL9Backend: failed to configure any device.")
            print("EEL9: Error 4 for debug")    # Debug
            return False

        self._dev = dev

        # Home → Slot1
        try:
            #self.sig_message.emit("ThorlabsEEL9Backend: homing device (Slot 1)...")
            #print("EEL9: Error 5 for debug")    # Debug
            self._busy = True
            self.sig_state_changed.emit(self.query_status())
            print("EEL9: Homing device...")    # Debug
            self._dev.Home(ELLBaseDevice.DeviceDirection.Linear)
            time.sleep(1.0)  # デバイス応答待ち
        except Exception as e:
            self._busy = False
            self.sig_state_changed.emit(self.query_status())
            #self.sig_error.emit(f"ThorlabsEEL9Backend: failed to home device: {e}")
            print("EEL9: Error 6 for debug")    # Debug
            return False

        self._position = 1
        self._busy = False
        self._connected = True

        self.sig_connected.emit(True)
        self.sig_state_changed.emit(self.query_status())
        return True

    def disconnect(self) -> None:
        """
        DLL 側の明示的な Disconnect API はサンプルからは分からないので、
        ここではフラグのみを更新する。
        """
        self._connected = False
        self._busy = False
        self.sig_connected.emit(False)

    # ---- 構造 ----
    def get_num_slots(self) -> int:
        # 常に 4
        return 4

    def get_slot_names(self) -> Dict[int, str]:
        # FilterPane 側で上書きされる前提で、デフォルト名を返す。
        if not self._slot_names:
            self._slot_names = {i: f"Filter {i}" for i in range(1, 5)}
        return dict(self._slot_names)

    # ---- パラメータ設定 ----
    def set_position(self, slot: int) -> None:
        """
        指定スロットへ移動する。
        現在位置との差分だけ JogForward / JogBackward を発行する。
        1 ステップごとに 1 秒待つ。
        """
        if not self._connected or self._dev is None:
            #self.sig_error.emit("ThorlabsEEL9Backend: not connected.")
            print("EEL9: Not connected.")    # Debug
            return

        slot = int(slot)
        if slot < 1 or slot > 4:
            #self.sig_error.emit(f"ThorlabsEEL9Backend: invalid slot {slot}.")
            print(f"EEL9: Invalid slot {slot}.")    # Debug
            return

        if self._busy:
            #self.sig_error.emit("ThorlabsEEL9Backend: device is busy.")
            print("EEL9: Device is busy.")    # Debug
            return

        if slot == self._position:
            # すでに目的位置
            return

        current = self._position
        target = slot
        steps = abs(target - current)
        if steps == 0:
            return

        # どちら向きに Jog するか
        direction = "forward" if target > current else "backward"

        def worker():
            self._busy = True
            self.sig_state_changed.emit(self.query_status())

            try:
                if direction == "forward":
                    jog = self._dev.JogForward
                else:
                    jog = self._dev.JogBackward

                for _ in range(steps):
                    try:
                        jog()
                    except Exception as e_inner:
                        #self.sig_error.emit(
                        #    f"ThorlabsEEL9Backend: jog failed ({direction}): {e_inner}"
                        #)
                        print(f"EEL9: Jog failed ({direction}): {e_inner}")    # Debug
                        break
                    # 各ステップごとに 1 秒待つ
                    #time.sleep(0.5)

                # ここまで来たら論理位置を更新（失敗時の厳密な同期は割り切り）
                self._position = target
            finally:
                self._busy = False
                self.sig_state_changed.emit(self.query_status())

        t = threading.Thread(target=worker, daemon=True)
        self._move_thread = t
        t.start()

    def get_position(self) -> int:
        return int(self._position)

    # ---- 状態取得 ----
    def query_status(self) -> dict:
        return {
            "position": int(self._position),
            "num_slots": 4,
            "slot_names": dict(self._slot_names),
            "busy": bool(self._busy),
        }

    # ---- 安全系 ----
    def emergency_shutdown(self) -> None:
        """
        進行中の Jog を強制停止する手段は DLL 仕様が不明なため、
        ここでは busy フラグと状態通知のみクリアする。
        """
        self._busy = False
        self.sig_state_changed.emit(self.query_status())

    # ---- FilterPane からのスロット名更新 ----
    def update_slot_name(self, slot: int, name: str) -> None:
        slot = int(slot)
        if slot < 1 or slot > 4:
            return
        if not name:
            return
        self._slot_names[slot] = str(name)
        self.sig_state_changed.emit(self.query_status())


def get_backend_class():
    """
    FilterPane 側から動的ロードされるエントリポイント。
    """
    return ThorlabsEEL9Backend
