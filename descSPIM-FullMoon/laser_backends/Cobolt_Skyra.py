# laser_backends/Cobolt_Skyra.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional, Dict, List, Any
import logging
import time
import re

import serial
from serial.tools import list_ports
from serial.serialutil import SerialException

from PySide6 import QtWidgets
from PySide6.QtCore import Slot

from laser_backends.laser_backend_base import ILaserBackend

logger = logging.getLogger(__name__)


# ===== 低レベル Cobolt 通信クラス（元 laser_integration から移動） =====


class CoboltLaser:
    """Creates a laser object using either COM-port or serial number to connect to laser."""

    def __init__(
        self,
        port: str | None = None,
        serialnumber: str | None = None,
        baudrate: int = 115200,
    ):
        self.msg_timer = time.perf_counter()
        self.serialnumber = str(serialnumber) if serialnumber else None
        self.port = port
        self.modelnumber = None
        self.baudrate = baudrate
        self.address = None
        self.connect()

    def __repr__(self):
        try:
            return (
                f'Serial number: {self.serialnumber}, '
                f'Model number: {self.modelnumber}, '
                f'Wavelength: {"{:.0f}".format(float(self.modelnumber[0:4]))} nm, '
                f'Type: {self.__class__.__name__} Port: {self.port}'
            )
        except Exception:
            return f"Serial number: {self.serialnumber}, Model number: {self.modelnumber}, Port: {self.port}"

    def connect(self):
        if self.port is not None:
            try:
                self.address = serial.Serial(self.port, self.baudrate, timeout=1)
            except Exception as err:
                self.address = None
                raise SerialException(f"{self.port} not accesible.") from err

        elif self.serialnumber is not None:
            ports = [x for x in list_ports.comports() if "USB" in (x.hwid or "")]
            try:
                port = next([item for item in ports if self.serialnumber in (item.serial_number or "")])
                self.port = port.device
                self.address = serial.Serial(self.port, self.baudrate, timeout=1)
            except StopIteration:
                for port in ports:
                    try:
                        self.address = serial.Serial(port.device, baudrate=self.baudrate, timeout=1)
                        sn = self.send_cmd("sn?")
                        self.address.close()
                        if sn == self.serialnumber:
                            self.port = port.device
                            self.address = serial.Serial(self.port, baudrate=self.baudrate)
                            break
                    except Exception:
                        pass
            if self.port is None:
                raise RuntimeError("No laser found")
        if self.address is not None:
            self._identify_()
        if self.__class__ == CoboltLaser:
            self._classify_()

    def _identify_(self):
        try:
            firmware = self.send_cmd("gfv?")
            if "error" in firmware.lower():
                self.disconnect()
                raise RuntimeError("Not a Cobolt laser")
            self.serialnumber = self.send_cmd("sn?")
            if "." not in firmware:
                if "0" in self.serialnumber:
                    self.modelnumber = f"0{self.serialnumber.partition(str(0))[0]}-04-XX-XXXX-XXX"
                    self.serialnumber = self.serialnumber.partition("0")[2]
                    while self.serialnumber and self.serialnumber[0] == "0":
                        self.serialnumber = self.serialnumber[1:]
            else:
                self.modelnumber = self.send_cmd("glm?")
        except Exception:
            self.disconnect()
            raise RuntimeError("Not a Cobolt laser")

    def _classify_(self):
        try:
            if re.search(r"-06-.*-(1\d{3})(|-C)$", str(self.modelnumber)):
                self.__class__ = Cobolt06  # type: ignore[name-defined]
            elif re.search(r"-06-0.*(|-C)$", str(self.modelnumber)):
                self.__class__ = Cobolt06MLD  # type: ignore[name-defined]
            elif re.search(r"-06-(5|9).*-(\d{3})(|-C)$", str(self.modelnumber)):
                self.__class__ = Cobolt06DPL  # type: ignore[name-defined]
        except Exception:
            pass

    def is_connected(self):
        try:
            if self.address and self.address.is_open:
                try:
                    test = self.send_cmd("?")
                    return test == "OK"
                except Exception:
                    return False
            return False
        except Exception:
            return False

    def disconnect(self):
        if self.address is not None:
            try:
                self.address.close()
            except Exception:
                pass
            self.serialnumber = None
            self.modelnumber = None

    def turn_on(self):
        logger.info("Turning on laser")
        return self.send_cmd("@cob1")

    def turn_off(self):
        logger.info("Turning off laser")
        return self.send_cmd("l0")

    def is_on(self):
        answer = self.send_cmd("l?")
        return answer == "1"

    def interlock(self):
        return self.send_cmd("ilk?")

    def get_fault(self):
        return self.send_cmd("f?")

    def clear_fault(self):
        return self.send_cmd("cf")

    def get_mode(self):
        return self.send_cmd("gam?")

    def get_state(self):
        return self.send_cmd("gom?")

    def constant_current(self, current=None):
        if current is not None:
            if not ("-08-" in (self.modelnumber or "") or "-06-" in (self.modelnumber or "")):
                self.send_cmd(f"slc {current/1000}")
            else:
                self.send_cmd(f"slc {current}")
            logger.info(f"Entering constant current mode with I = {current} mA")
        else:
            logger.info("Entering constant current mode")
        return self.send_cmd("ci")

    def set_current(self, current: float):
        logger.info(f"Setting I = {current} mA")
        if not ("-08-" in (self.modelnumber or "") or "-06-" in (self.modelnumber or "")):
            current = current / 1000
        return self.send_cmd(f"slc {current}")

    def get_current(self):
        return float(self.send_cmd("i?"))

    def get_current_setpoint(self):
        return float(self.send_cmd("glc?"))

    def constant_power(self, power: float | None = None):
        if power is not None:
            self.send_cmd(f"p {float(power)/1000}")
            logger.info(f"Entering constant power mode with P = {power} mW")
        else:
            logger.info("Entering constant power mode")
        return self.send_cmd("cp")

    def set_power(self, power: float):
        logger.info(f"Setting P = {power} mW")
        return self.send_cmd(f"p {float(power)/1000}")

    def get_power(self):
        return float(self.send_cmd("pa?")) * 1000

    def get_power_setpoint(self):
        return float(self.send_cmd("p?")) * 1000

    def get_ophours(self):
        return self.send_cmd("hrs?")

    def send_cmd(self, message, timeout: int | None = None):
        if timeout:
            self.address.timeout = timeout
        message += "\r"
        while time.perf_counter() - self.msg_timer < 0.100:
            continue
        try:
            utf8_msg = message.encode()
            self.address.write(utf8_msg)
            logger.debug(f"sent laser [{self}] message [{utf8_msg}]")
        except Exception as e:
            raise RuntimeError("Error: write failed") from e

        try:
            received_string = self.address.readline().decode().rstrip()
            self.msg_timer = time.perf_counter()
            if len(received_string) < 1:
                logger.error(f"No response received for {message}")
                raise SerialException
        except serial.SerialException:
            raise RuntimeError(f"Syntax Error: No response on {message}")
        else:
            logger.debug(f"received from laser [{self}] message [{received_string}]")
        return received_string

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            self.turn_off()
        except Exception:
            pass
        self.disconnect()


def list_lasers() -> List[CoboltLaser]:
    lasers: List[CoboltLaser] = []
    ports = list_ports.comports()
    for port in ports:
        try:
            laser = CoboltLaser(port=port.device)
            if laser.serialnumber is None or str(laser.serialnumber).startswith("Syntax"):
                del laser
            else:
                lasers.append(laser)
        except Exception:
            pass
    return lasers


class CoboltSkyra(CoboltLaser):
    def __init__(self, port: str | None = None, serialnumber: str | None = None, baudrate: int = 115200):
        super().__init__(port, serialnumber, baudrate)
        self.wlen: Dict[int, str] = {}
        for i in range(1, 5):
            try:
                resp = self.send_cmd(f"{i}glw?", timeout=1)
                self.wlen[i] = resp.strip()
            except Exception:
                self.wlen[i] = "0"

    def get_laser_active_state(self, wlenId):
        answer = self.send_cmd(f"{wlenId}gla?")
        return answer == "1"

    def set_laser_active_state(self, wlenId, active: int):
        self.send_cmd(f"{wlenId}sla {active}", timeout=1)
        logger.info(f"{'Activate' if active else 'Inactivate'} laser {wlenId}")

    def turn_laser_line_ON(self, wlenId):
        logger.info(f"Turning on laser {wlenId}")
        return self.send_cmd(f"{wlenId}l1")

    def turn_laser_line_OFF(self, wlenId):
        logger.info(f"Turning off laser {wlenId}")
        return self.send_cmd(f"{wlenId}l0")

    def get_laser_ON_OFF_state(self, wlenId):
        answer = self.send_cmd(f"{wlenId}l?")
        return answer == "1"

    def enter_constant_current_mode(self, wlenId):
        self.send_cmd(f"{wlenId}ci")
        logger.info("Entering constant current mode")

    def set_laser_current(self, wlenId, current: float):
        self.send_cmd(f"{wlenId}slc {current}")
        logger.info(f"Setting I = {current} mA")

    def read_laser_current(self, wlenId):
        return float(self.send_cmd(f"{wlenId}i?"))

    def get_laser_current(self, wlenId):
        return float(self.send_cmd(f"{wlenId}glc?"))

    def enter_constant_power_mode(self, wlenId):
        self.send_cmd(f"{wlenId}cp")
        logger.info("Entering constant power mode")

    def set_laser_power(self, wlenId, power: float):
        self.send_cmd(f"{wlenId}p {float(power)/1000}")
        logger.info(f"Setting P = {power} mW")

    def read_laser_power(self, wlenId):
        return float(self.send_cmd(f"{wlenId}pa?")) * 1000

    def get_laser_power(self, wlenId):
        return float(self.send_cmd(f"{wlenId}p?")) * 1000

    def get_key_switch_state(self):
        answer = self.send_cmd("@cobasks?")
        return answer == "1"

    def set_autostart_off(self):
        return self.send_cmd("abort")

    def set_autostart_on(self):
        return self.send_cmd("restart")


# ===== ILaserBackend 実装: CoboltSkyraBackend =====


class CoboltSkyraBackend(ILaserBackend):
    """
    Cobolt Skyra 用 backend。
    - COM ポート選択ダイアログ
    - 接続時に 1〜4 スロットの wavelength を取得
    - line_id は「波長 (nm) の文字列」（例: "488", "561"）
    """

    def __init__(self, parent: Optional[ILaserBackend] = None) -> None:
        super().__init__(parent)
        self._device: Optional[CoboltSkyra] = None
        self._lines: List[Dict[str, Any]] = []
        self._line_map: Dict[str, Dict[str, Any]] = {}
        self._port: Optional[str] = None
        self._connection_key: str = ""

    # ---- ILaserBackend ----

    def show_setup_dialog(self, parent: Optional[QtWidgets.QWidget] = None) -> bool:  # type: ignore[override]
        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("Cobolt Skyra Setup")

        layout = QtWidgets.QVBoxLayout(dlg)
        form = QtWidgets.QFormLayout()
        cmb_port = QtWidgets.QComboBox()

        ports = list_ports.comports()
        for p in ports:
            cmb_port.addItem(p.device, p.device)

        if cmb_port.count() == 0:
            cmb_port.addItem("(no ports found)", "")

        form.addRow("Port:", cmb_port)
        layout.addLayout(form)

        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        layout.addWidget(btns)

        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)

        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return False

        port = cmb_port.currentData()
        if not port:
            QtWidgets.QMessageBox.warning(dlg, "Cobolt Skyra", "Valid COM port not selected.")
            return False

        self._port = str(port)
        self._connection_key = self._port
        return True

    def connect(self) -> bool:  # type: ignore[override]
        if not self._port:
            self.sig_error.emit("CoboltSkyraBackend: Port is not set. Call show_setup_dialog() first.")
            return False

        # 既存接続があれば一度切断
        try:
            self.disconnect()
        except Exception:
            pass

        try:
            dev = CoboltSkyra(port=self._port, baudrate=115200)
            if not dev.is_connected():
                raise RuntimeError("Connection failed.")
            self._device = dev

            # wavelength 情報取得
            self._lines.clear()
            self._line_map.clear()
            for slot in range(1, 5):
                wl = dev.wlen.get(slot, "0")
                if wl in ("0", "", None):
                    continue
                # 数値だけ抜き出して nm として扱う
                digits = "".join(ch for ch in str(wl) if ch.isdigit())
                if not digits:
                    continue
                wl_nm = int(digits)
                line_id = digits  # "488" など
                line_info = {
                    "id": line_id,
                    "wavelength_nm": wl_nm,
                    "name": f"{wl_nm} nm",
                    "slot": slot,
                }
                self._lines.append(line_info)
                self._line_map[line_id] = line_info

            if not self._lines:
                raise RuntimeError("CoboltSkyraBackend: No active lines reported by device.")

            # 接続時は全ライン OFF / inactive にそろえる
            for line_info in self._lines:
                slot = int(line_info["slot"])
                try:
                    dev.set_laser_active_state(slot, 0)
                except Exception as e:
                    logger.warning("Failed to inactivate line %s: %s", slot, e)
                try:
                    dev.turn_laser_line_OFF(slot)
                except Exception as e:
                    logger.warning("Failed to force OFF line %s: %s", slot, e)

            self.sig_connected.emit(True)
            self.sig_state_changed.emit(self.query_status())
            return True

        except Exception as e:
            self.sig_error.emit(f"CoboltSkyraBackend connect error: {e}")
            try:
                self.disconnect()
            except Exception:
                pass
            return False

    def disconnect(self) -> None:  # type: ignore[override]
        dev = self._device
        self._device = None
        if dev is not None:
            try:
                # 可能なら全ライン OFF
                try:
                    for slot in range(1, 5):
                        try:
                            dev.set_laser_active_state(slot, 0)
                        except Exception:
                            pass
                        try:
                            dev.turn_laser_line_OFF(slot)
                        except Exception:
                            pass
                except Exception:
                    pass
            finally:
                try:
                    dev.disconnect()
                except Exception:
                    pass
        self.sig_connected.emit(False)

    def get_capabilities(self) -> Dict[str, Any]:  # type: ignore[override]
        return {
            "type": "CoboltSkyra",
            "multi_line": True,
            "max_lines": 4,
        }

    def get_lines(self) -> List[Dict[str, Any]]:  # type: ignore[override]
        return list(self._lines)

    def _ensure_device(self) -> CoboltSkyra:
        if self._device is None:
            raise RuntimeError("CoboltSkyraBackend: device not connected.")
        return self._device

    def set_power_mw(self, line_id: str, power_mw: float) -> None:  # type: ignore[override]
        dev = self._ensure_device()
        info = self._line_map.get(line_id)
        if info is None:
            raise KeyError(f"Unknown line_id: {line_id}")
        slot = int(info["slot"])
        dev.enter_constant_power_mode(slot)
        dev.set_laser_power(slot, float(power_mw))
        self.sig_state_changed.emit(self.query_status())

    def get_power_mw(self, line_id: str) -> float:  # type: ignore[override]
        dev = self._ensure_device()
        info = self._line_map.get(line_id)
        if info is None:
            raise KeyError(f"Unknown line_id: {line_id}")
        slot = int(info["slot"])
        return float(dev.get_laser_power(slot))

    def get_power_range(self, line_id: str) -> tuple:  # type: ignore[override]
        """
        modelnumber = "MF-AAA-BBB-CCC-DDD-XXX-YYY-ZZZ-QQQ-WWW" という形式を仮定し、
        AAA,BBB,CCC,DDD を波長、XXX,YYY,ZZZ,QQQ をそれぞれの max power(mW) として、
        該当 line の max power を返す。

        うまくパースできない場合は (0.0, 500.0) を返す。
        """
        min_p = 0.0
        fallback_max = 500.0
        max_p = fallback_max

        try:
            dev = self._ensure_device()
            model = getattr(dev, "modelnumber", None)
            info = self._line_map.get(line_id)
            if not model or info is None:
                return (min_p, max_p)

            parts = str(model).split("-")
            # 期待形式: MF-AAA-BBB-CCC-DDD-XXX-YYY-ZZZ-QQQ-WWW
            # インデックス: 0  1   2   3   4   5    6    7    8    9
            if len(parts) < 9:
                return (min_p, max_p)

            wl_tokens = parts[1:5]   # AAA, BBB, CCC, DDD
            pw_tokens = parts[5:9]   # XXX, YYY, ZZZ, QQQ

            # 数値だけ抜き出して int / float にする
            wl_list: List[Optional[int]] = []
            pw_list: List[float] = []

            for t in wl_tokens:
                digits = "".join(ch for ch in t if ch.isdigit())
                try:
                    wl_list.append(int(digits))
                except Exception:
                    wl_list.append(None)

            for t in pw_tokens:
                digits = "".join(ch for ch in t if ch.isdigit())
                try:
                    pw_list.append(float(digits))
                except Exception:
                    pw_list.append(fallback_max)

            target_wl = int(info.get("wavelength_nm"))

            for wl, pw in zip(wl_list, pw_list):
                if wl is not None and wl == target_wl:
                    max_p = pw
                    break

            return (min_p, max_p)
        except Exception:
            return (min_p, fallback_max)


    def set_enabled(self, line_id: str, enabled: bool) -> None:  # type: ignore[override]
        dev = self._ensure_device()
        info = self._line_map.get(line_id)
        if info is None:
            raise KeyError(f"Unknown line_id: {line_id}")
        slot = int(info["slot"])

        # キー OFF のときは ON 要求を拒否
        if enabled:
            try:
                if not dev.get_key_switch_state():
                    raise RuntimeError("Key is OFF. Please turn ON the physical key.")
            except Exception as e:
                self.sig_error.emit(str(e))
                self.sig_state_changed.emit(self.query_status())
                raise

        if enabled:
            try:
                dev.set_laser_active_state(slot, 1)
            except Exception:
                pass
            dev.turn_laser_line_ON(slot)
        else:
            try:
                dev.turn_laser_line_OFF(slot)
            except Exception:
                pass
            try:
                dev.set_laser_active_state(slot, 0)
            except Exception:
                pass

        self.sig_state_changed.emit(self.query_status())

    def get_enabled(self, line_id: str) -> bool:  # type: ignore[override]
        dev = self._ensure_device()
        info = self._line_map.get(line_id)
        if info is None:
            raise KeyError(f"Unknown line_id: {line_id}")
        slot = int(info["slot"])
        return dev.get_laser_ON_OFF_state(slot)

    def set_master_enable(self, enabled: bool) -> None:  # type: ignore[override]
        dev = self._device
        if dev is None:
            return
        for line_id in list(self._line_map.keys()):
            try:
                self.set_enabled(line_id, enabled)
            except Exception:
                pass

    def emergency_shutdown(self) -> None:  # type: ignore[override]
        dev = self._device
        if dev is None:
            return
        for line_id in list(self._line_map.keys()):
            try:
                self.set_enabled(line_id, False)
            except Exception:
                pass

    def query_status(self) -> Dict[str, Any]:  # type: ignore[override]
        dev = self._device
        status: Dict[str, Any] = {
            "connected": dev.is_connected() if dev is not None else False,
            "port": self._port,
        }
        if dev is not None:
            try:
                status["serial"] = dev.serialnumber
            except Exception:
                status["serial"] = None
            try:
                status["fault"] = dev.get_fault()
            except Exception:
                status["fault"] = None
        return status

    def get_connection_key(self) -> str:  # type: ignore[override]
        return self._connection_key or (self._port or "")


def get_backend_class():
    """
    LaserPane の scan_laser_backends() から呼ばれるエントリーポイント。
    """
    return CoboltSkyraBackend
