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
    （実際に何 ch 使えるかは Backend 側の _num_channels で制御）
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

    ・pyvisa 経由で SCPI 制御
    ・IDN 応答から 1ch/2ch 判定
      - DG811 / DG821 / DG831 -> 1ch
      - DG812 / DG822 / DG832 -> 2ch
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rm: Optional["pyvisa.ResourceManager"] = None
        self._inst: Optional[Any] = None
        self._resource: str = ""

        self._model: str = ""          # 例: "DG822"
        self._num_channels: int = 2    # デフォルトは 2ch 想定

        self._settings = QtCore.QSettings("LabSuite", "RigolDG800")

        # UI 用ローカル状態（DEF 相当の初期値）
        self._state: Dict[str, Dict[str, Any]] = {}
        self._init_state_for_channels()

    # ---- 内部: チャンネル数に応じた状態初期化 ----

    def _init_state_for_channels(self) -> None:
        state: Dict[str, Dict[str, Any]] = {}
        for idx in range(1, self._num_channels + 1):
            ch_id = f"CH{idx}"
            state[ch_id] = {
                "enabled": False,
                "waveform": "sine",  # 見かけ上のデフォルト
                "freq": 1000.0,
                "amp": 1.0,
                "offset": 0.0,
            }
        self._state = state

    def _detect_num_channels_from_model(self, model: str) -> int:
        """
        DG811/821/831 -> 1ch
        DG812/822/832 -> 2ch
        それ以外は 2ch と仮定（フォールバック）
        """
        m = model.upper().strip()
        if m in ("DG811", "DG821", "DG831"):
            return 1
        if m in ("DG812", "DG822", "DG832"):
            return 2
        return 2

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
            inst.timeout = 5000  # ms

            # IDN 取得（ここで機種判定）
            inst.write("*IDN?")
            idn = inst.read()
            logger.info("Rigol DG800 IDN: %s", idn)

            parts = [p.strip() for p in idn.split(",")]
            if len(parts) >= 2:
                self._model = parts[1]  # "DG822" など
                self._num_channels = self._detect_num_channels_from_model(self._model)
            else:
                self._model = ""
                self._num_channels = 2

            # チャンネル数に応じて状態リセット
            self._init_state_for_channels()

            # 出力条件の初期設定:
            # ・インピーダンス 50 Ω 固定
            # ・電圧単位 VPP
            for idx in range(1, self._num_channels + 1):
                try:
                    inst.write(f":OUTPut{idx}:LOAD 50")
                except Exception as e:
                    logger.warning("Failed to set OUTPut%d:LOAD 50: %s", idx, e)
                try:
                    inst.write(f":SOURce{idx}:VOLTage:UNIT VPP")
                except Exception as e:
                    logger.warning("Failed to set SOURce%d:VOLTage:UNIT VPP: %s", idx, e)

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
            {"id": f"CH{idx}", "name": f"CH{idx}"}
            for idx in range(1, self._num_channels + 1)
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

    def _query(self, cmd: str) -> Optional[str]:
        """
        SCPI クエリ送信ヘルパ（write+read をまとめる）
        失敗時は None を返し、sig_error に流す。
        """
        if self._inst is None:
            self.sig_error.emit(f"not connected (query='{cmd}')")
            return None
        try:
            logger.debug("RigolDG800 QUERY: %s", cmd)
            # pyvisa の query() を使う方が安全
            resp = self._inst.query(cmd)
            return str(resp).strip()
        except Exception as e:
            msg = f"SCPI query error ({cmd}): {e}"
            logger.exception(msg)
            self.sig_error.emit(msg)
            return None


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
        if idx is None or idx > self._num_channels:
            return

        # :SOURce[<n>]:FREQuency <freq>
        cmd = f":SOURce{idx}:FREQuency {float(value_hz)}"
        self._send(cmd)

        self._update_state(ch_id, "freq", float(value_hz))
        self._emit_state_changed()

    def set_amp(self, ch_id: str, value_vpp: float) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None or idx > self._num_channels:
            return

        # 単位は VPP（接続時に :VOLTage:UNIT VPP 済み）
        # :SOURce[<n>]:VOLTage <amp>
        cmd = f":SOURce{idx}:VOLTage {float(value_vpp)}"
        self._send(cmd)

        self._update_state(ch_id, "amp", float(value_vpp))
        self._emit_state_changed()

    def set_offset(self, ch_id: str, value_v: float) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None or idx > self._num_channels:
            return

        # オフセット: 一般的には :SOURce[<n>]:VOLTage:OFFSet <offset>
        # マニュアルで要確認ポイントだが、暫定で使用。
        cmd = f":SOURce{idx}:VOLTage:OFFSet {float(value_v)}"
        self._send(cmd)

        self._update_state(ch_id, "offset", float(value_v))
        self._emit_state_changed()

    def set_waveform(self, ch_id: str, wave: str) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None or idx > self._num_channels:
            return

        wave_l = str(wave).strip().lower()

        # IGalvoBackend の想定:
        #   "sine", "square", "triangle", "sawtooth" など
        # DG800 の :FUNCtion[:SHAPe] の <name> のうち、
        # 代表的なものだけマッピングしておく。
        mapping = {
            "sine": "SINusoid",
            "sin": "SINusoid",
            "square": "SQUare",
            "squ": "SQUare",
            # 「きっちり三角波」が必要な場合は TRIANG を使う
            "triangle": "TRIANG",
            "tri": "TRIANG",
            # sawtooth は RAMP（対称は 50%、RAMP:SYMMetry で変更可能）
            "sawtooth": "RAMP",
            "saw": "RAMP",
            # fallback 用
            "ramp": "RAMP",
        }

        func_name = mapping.get(wave_l, "SINusoid")

        # :SOURce[<n>]:FUNCtion[:SHAPe] <name>
        cmd = f":SOURce{idx}:FUNCtion {func_name}"
        self._send(cmd)

        self._update_state(ch_id, "waveform", wave_l)
        self._emit_state_changed()

    # ---- ON/OFF ----

    def set_enabled(self, ch_id: str, enabled: bool) -> None:
        idx = _ch_id_to_index(ch_id)
        if idx is None or idx > self._num_channels:
            return

        state_str = "ON" if enabled else "OFF"
        # :OUTPut[<n>][:STATe] {ON|OFF}
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
        """
        実機から :SOURceN:APPLy? / :OUTPutN? を読んで _state を更新し、返す。

        :SOURceN:APPLy? の戻り値（例）:
            "SQU,1.000000E+03,2.000000E+00,3.000000E+00,4.000000E+00"
            → waveform, freq[Hz], amp[Vpp], offset[V], phase[deg]
        :OUTPutN? の戻り値:
            ON / OFF
        """
        # 接続されていない場合はローカルキャッシュをそのまま返す
        if self._inst is None:
            return {"channels": {ch_id: dict(v) for ch_id, v in self._state.items()}}

        # APPLy? の波形名 → UI 用波形名へのマップ
        # ここではガルボ UI の 4 種類に落とす
        wave_map = {
            "SIN": "sine",
            "SQU": "square",
            # RAMP は triangle/sawtooth 両方の元なので、とりあえず triangle に寄せる
            "RAMP": "triangle",
            # その他 (PULSE, NOISE, DC, USER, ...) は既存値を維持する
        }

        for idx in (1, 2):
            # 1ch 機のときは CH2 を読み飛ばす
            if idx > self._num_channels:
                continue

            ch_id = f"CH{idx}"
            ch_state = self._state.get(ch_id, {})
            if not isinstance(ch_state, dict):
                ch_state = {}
                self._state[ch_id] = ch_state

            # ---- 出力 ON/OFF ----
            out_resp = self._query(f":OUTPut{idx}?")
            if out_resp is not None:
                s = out_resp.strip().upper()
                if s.startswith("ON") or s.startswith("1"):
                    ch_state["enabled"] = True
                elif s.startswith("OFF") or s.startswith("0"):
                    ch_state["enabled"] = False
                # それ以外の値は無視して既存値を保持

            # ---- 波形 / 周波数 / 振幅 / オフセット ----
            appl_resp = self._query(f":SOURce{idx}:APPLy?")
            if appl_resp is not None:
                try:
                    txt = appl_resp.strip()
                    if txt.startswith('"') and txt.endswith('"') and len(txt) >= 2:
                        txt = txt[1:-1]
                    parts = [p.strip() for p in txt.split(",")]
                    # parts[0] = waveform 名 (SIN/SQU/RAMP/...)
                    if len(parts) >= 1 and parts[0]:
                        wf_raw = parts[0].upper()
                        wf_ui = wave_map.get(wf_raw)
                        if wf_ui is not None:
                            ch_state["waveform"] = wf_ui
                        else:
                            # 未対応の波形は既存値を維持
                            pass

                    # parts[1] = freq [Hz]
                    if len(parts) >= 2 and parts[1] and parts[1].upper() != "DEF":
                        try:
                            ch_state["freq"] = float(parts[1])
                        except ValueError:
                            pass

                    # parts[2] = amp [Vpp]
                    if len(parts) >= 3 and parts[2] and parts[2].upper() != "DEF":
                        try:
                            ch_state["amp"] = float(parts[2])
                        except ValueError:
                            pass

                    # parts[3] = offset [V]
                    if len(parts) >= 4 and parts[3] and parts[3].upper() != "DEF":
                        try:
                            ch_state["offset"] = float(parts[3])
                        except ValueError:
                            pass

                    # phase (parts[4]) は現状使わないので無視
                except Exception as e:
                    self.sig_error.emit(f"query_status parse error (CH{idx}): {e}")

        # 更新済み _state のコピーを返す
        return {
            "channels": {ch_id: dict(v) for ch_id, v in self._state.items()}
        }


    def emergency_shutdown(self) -> None:
        # 全チャネルの出力 OFF
        for idx in range(1, self._num_channels + 1):
            ch_id = f"CH{idx}"
            cmd = f":OUTPut{idx} OFF"
            self._send(cmd)
            self._update_state(ch_id, "enabled", False)
        self._emit_state_changed()


def get_backend_class():
    """GalvoPane から呼ばれるファクトリ"""
    return RigolDG800Backend
