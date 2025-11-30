# galvo_backends/Rigol_DG800.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Any, Optional, List
import logging

from PySide6 import QtCore, QtWidgets

from .galvo_backend_base import IGalvoBackend

logger = logging.getLogger(__name__)

try:
    import pyvisa  # pip install pyvisa
except ImportError:
    pyvisa = None


def _ch_id_to_index(ch_id: str) -> Optional[int]:
    """
    'CH1' / '1' -> 1, 'CH2' / '2' -> 2
    """
    s = str(ch_id).strip().upper()
    if s in ("CH1", "1"):
        return 1
    if s in ("CH2", "2"):
        return 2
    return None


class RigolDG800VisaDialog(QtWidgets.QDialog):
    """
    Rigol DG8xx/DG9xx の VISA アドレス選択ダイアログ
    """

    def __init__(
        self,
        settings: QtCore.QSettings,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._selected_resource: str = ""

        self.setWindowTitle("Select Rigol DG800/DG900 VISA Resource")

        self.cmb_resource = QtWidgets.QComboBox()
        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_refresh.clicked.connect(self._refresh_resources)

        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self,
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)

        lay_top = QtWidgets.QHBoxLayout()
        lay_top.addWidget(QtWidgets.QLabel("Resource:"))
        lay_top.addWidget(self.cmb_resource, 1)
        lay_top.addWidget(self.btn_refresh)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(lay_top)
        lay.addWidget(btn_box)

        self._refresh_resources()
        self._restore_last_resource()

    def _refresh_resources(self) -> None:
        self.cmb_resource.clear()
        if pyvisa is None:
            self.cmb_resource.addItem("(pyvisa not available)", "")
            return

        try:
            rm = pyvisa.ResourceManager()
            resources = list(rm.list_resources())
        except Exception as e:
            logger.exception("VISA resource scan error: %s", e)
            resources = []

        if not resources:
            self.cmb_resource.addItem("(no VISA resources found)", "")
        else:
            for r in resources:
                # 表示とデータ両方に同じ文字列を持たせる
                self.cmb_resource.addItem(str(r), str(r))

    def _restore_last_resource(self) -> None:
        last_res = self._settings.value("visa_resource", "", str)
        if not last_res:
            return
        idx = self.cmb_resource.findData(last_res)
        if idx >= 0:
            self.cmb_resource.setCurrentIndex(idx)

    @property
    def selected_resource(self) -> str:
        return self._selected_resource

    def accept(self) -> None:
        data = self.cmb_resource.currentData()
        if data:
            self._selected_resource = str(data)
            self._settings.setValue("visa_resource", self._selected_resource)
        super().accept()


class RigolDG800Backend(IGalvoBackend):
    """
    Rigol DG8xx / DG9xx (例: DG822) 用 Galvo backend

    ・2 チャンネル (CH1, CH2) を想定
    ・内部的には pyvisa を用いて SCPI 経由で制御する
    ・SCPI コマンドの詳細はプログラミングガイドに従って後で検証・調整する前提
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rm: Optional["pyvisa.ResourceManager"] = None
        self._inst: Optional[Any] = None
        self._resource: str = ""

        self._settings = QtCore.QSettings("LabSuite", "RigolDG800")

        # UI 用のローカル状態キャッシュ
        self._state: Dict[str, Dict[str, Any]] = {
            "CH1": {
                "enabled": False,
                "waveform": "sine",
                "freq": 1000.0,
                "amp": 1.0,
                "offset": 0.0,
            },
            "CH2": {
                "enabled": False,
                "waveform": "sine",
                "freq": 1000.0,
                "amp": 1.0,
                "offset": 0.0,
            },
        }

    # ---- 接続系 ----

    def show_setup_dialog(self, parent=None) -> bool:
        if pyvisa is None:
            QtWidgets.QMessageBox.warning(
                parent,
                "Rigol DG800",
                "The 'pyvisa' package was not found.\nPlease run 'pip install pyvisa'.",
            )
            return False

        dlg = RigolDG800VisaDialog(self._settings, parent=parent)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False

        res = dlg.selected_resource
        if not res:
            QtWidgets.QMessageBox.warning(
                parent,
                "Rigol DG800",
                "No valid VISA resource selected.",
            )
            return False

        self._resource = res
        return True

    def connect(self) -> bool:
        if pyvisa is None:
            self.sig_error.emit(
                "The 'pyvisa' package was not found. Please run 'pip install pyvisa'."
            )
            self.sig_connected.emit(False)
            return False

        if not self._resource:
            self.sig_error.emit("VISA resource is not set.")
            self.sig_connected.emit(False)
            return False

        # 既存接続をクリーンアップ
        self.disconnect()

        try:
            self._rm = pyvisa.ResourceManager()
            inst = self._rm.open_resource(self._resource)
            # タイムアウトなどは後で調整する前提
            inst.timeout = 5000

            # SCPI が通るか最低限確認（標準コマンドなのでここはほぼ確実）
            inst.write("*IDN?")
            idn = inst.read()
            logger.info("Rigol DG800 IDN: %s", idn)

            self._inst = inst
            self.sig_connected.emit(True)
            return True
        except Exception as e:
            self._inst = None
            msg = f"Rigol DG800 connection error: {e}"
            logger.exception(msg)
            self.sig_error.emit(msg)
            self.sig_connected.emit(False)
            return False

    def disconnect(self) -> None:
        if self._inst is not None:
            try:
                self._inst.close()
            except Exception:
                pass
        self._inst = None
        self.sig_connected.emit(False)

    def get_connection_key(self) -> str:
        return self._resource or ""

    # ---- チャンネル情報 ----

    def get_channels(self) -> List[Dict[str, Any]]:
        return [
            {"id": "CH1", "name": "CH1"},
            {"id": "CH2", "name": "CH2"},
        ]

    # ---- 内部ヘルパ ----

    def _send(self, cmd: str) -> None:
        """
        SCPI コマンド送信ヘルパ（write エラーを捕捉して sig_error に流す）
        """
        if self._inst is None:
            self.sig_error.emit(f"not connected (cmd='{cmd}')")
            return
        try:
            logger.debug("RigolDG800 SEND: %s", cmd)
            self._inst.write(cmd)
        except Exception as e:
            msg = f"SCPI write error ({cmd}): {e}"
            logger.exception(msg)
            self.sig_error.emit(msg)

    def _update_state(self, ch_id: str, key: str, value: Any) -> None:
        ch_state = self._state.get(ch_id)
        if ch_state is None:
            ch_state = {}
            self._state[ch_id] = ch_state
        ch_state[key] = value

    def _emit_state_changed(self) -> None:
        try:
            self.sig_state_changed.emit(self.query_status())
        except Exception:
            pass

    # ---- パラメータ設定 ----

    def set_freq(self, ch_id: str, value_hz: float) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None:
            return

        # TODO: DG800 Programming Guide の :SOURce:FREQuency の正確な書式を確認する
        cmd = f":SOURce{idx}:FREQuency {float(value_hz)}"
        self._send(cmd)

        self._update_state(ch_id, "freq", float(value_hz))
        self._emit_state_changed()

    def set_amp(self, ch_id: str, value_vpp: float) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None:
            return

        # 単位は VPP として扱う（サンプルコードでも :SOURx:VOLT:UNIT VPP を使用）
        # TODO: 必要なら最初に :SOURce{idx}:VOLTage:UNIT VPP を送るか検証する
        cmd = f":SOURce{idx}:VOLTage {float(value_vpp)}"
        self._send(cmd)

        self._update_state(ch_id, "amp", float(value_vpp))
        self._emit_state_changed()

    def set_offset(self, ch_id: str, value_v: float) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None:
            return

        # TODO: オフセット設定コマンド名 (:VOLTage:OFFSet? など) をマニュアルで確認する
        cmd = f":SOURce{idx}:VOLTage:OFFSet {float(value_v)}"
        self._send(cmd)

        self._update_state(ch_id, "offset", float(value_v))
        self._emit_state_changed()

    def set_waveform(self, ch_id: str, wave: str) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None:
            return

        # IGalvoBackend では "sine", "square", "triangle", "sawtooth" を想定
        # Rigol SCPI の FUNC 名とのマッピングは推測で置いておき、後でマニュアルで検証する。
        wave_l = str(wave).strip().lower()
        # TODO: マニュアルの :SOURce:FUNCtion での正式名称を確認する
        mapping = {
            "sine": "SIN",
            "sin": "SIN",
            "square": "SQU",
            "squ": "SQU",
            "triangle": "RAMP",   # 多くの AWG では TRI/RAMP のどちらかなので要確認
            "tri": "RAMP",
            "sawtooth": "RAMP",
            "saw": "RAMP",
        }
        func_name = mapping.get(wave_l, "SIN")

        cmd = f":SOURce{idx}:FUNCtion {func_name}"
        self._send(cmd)

        self._update_state(ch_id, "waveform", wave_l)
        self._emit_state_changed()

    # ---- ON/OFF ----

    def set_enabled(self, ch_id: str, enabled: bool) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None:
            return

        state_str = "ON" if enabled else "OFF"
        # サンプルコードの :OUTPUT%d ON/OFF をそのまま使用
        cmd = f":OUTPut{idx} {state_str}"
        self._send(cmd)

        self._update_state(ch_id, "enabled", bool(enabled))
        self._emit_state_changed()

    def get_enabled(self, ch_id: str) -> bool:
        ch_state = self._state.get(ch_id)
        if ch_state is None:
            return False
        return bool(ch_state.get("enabled", False))

    # ---- 状態問い合わせ / 安全系 ----

    def query_status(self) -> Dict[str, Any]:
        # 現時点では SCPI での問い合わせは行わず、
        # ローカルキャッシュした _state をそのまま返す。
        # （必要になれば :SOURce?, :OUTPut? 等で実測値を読む実装を追加する）
        return {"channels": {ch_id: dict(v) for ch_id, v in self._state.items()}}

    def emergency_shutdown(self) -> None:
        # 全チャネルの出力 OFF
        for ch_id in ("CH1", "CH2"):
            idx = _ch_id_to_index(ch_id)
            if idx is None:
                continue
            cmd = f":OUTPut{idx} OFF"
            self._send(cmd)
            self._update_state(ch_id, "enabled", False)
        self._emit_state_changed()


def get_backend_class():
    """GalvoPane から呼ばれるファクトリ"""
    return RigolDG800Backend
