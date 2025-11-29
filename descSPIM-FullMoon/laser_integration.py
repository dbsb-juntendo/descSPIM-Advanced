# laser_integration.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Optional, Any
import logging
import importlib
import pkgutil
import pathlib

from PySide6 import QtWidgets, QtCore

from laser_backends.laser_backend_base import ILaserBackend

# 互換性のため: もし他のモジュールから CoboltSkyra をインポートしていた場合に備えて
try:
    from laser_backends.Cobolt_Skyra import CoboltSkyra  # type: ignore
except Exception:
    CoboltSkyra = None  # type: ignore

logger = logging.getLogger(__name__)


# backend モジュール探索用ディレクトリ
LASER_BACKEND_MODULE_DIR = pathlib.Path(__file__).parent / "laser_backends"


def scan_laser_backends() -> Dict[str, Dict[str, Any]]:
    """
    laser_backends/ 以下を走査して、get_backend_class() を持つモジュールを列挙する。
    戻り値: { "Cobolt_Skyra": {"module": "...", "class": <cls>} }
    """
    backends: Dict[str, Dict[str, Any]] = {}
    pkg_name = "laser_backends"

    if not LASER_BACKEND_MODULE_DIR.exists():
        return backends

    for mi in pkgutil.iter_modules([str(LASER_BACKEND_MODULE_DIR)]):
        mod_name = f"{pkg_name}.{mi.name}"
        try:
            module = importlib.import_module(mod_name)
        except Exception as e:
            logger.warning("Failed to import laser backend module %s: %s", mod_name, e)
            continue

        get_cls = getattr(module, "get_backend_class", None)
        if not callable(get_cls):
            continue

        try:
            cls = get_cls()
        except Exception as e:
            logger.warning("get_backend_class() failed in %s: %s", mod_name, e)
            continue

        try:
            if not issubclass(cls, ILaserBackend):
                continue
        except Exception:
            continue

        backends[mi.name] = {"module": mod_name, "class": cls}

    return backends


@dataclass
class LaserDeviceEntry:
    backend: ILaserBackend
    backend_name: str      # "Cobolt_Skyra" など
    connection_key: str    # "COM5", "SN=12345", "ip=..." 等
    lines: List[Dict[str, Any]]   # backend.get_lines() の結果


class LaserLineControl(QtWidgets.QWidget):
    """
    1 line 分の ON/OFF + Power(mW) UI。
    backend と line_id に対して汎用的に動く。
    """
    sig_status = QtCore.Signal(str)

    def __init__(self, entry: LaserDeviceEntry, line: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._settings = QtCore.QSettings("LabSuite", "LaserPane")
        self._entry = entry
        self._backend = entry.backend
        self._line_id = str(line.get("id"))
        wl = line.get("wavelength_nm")
        name = line.get("name") or (f"{wl} nm" if wl is not None else self._line_id)
        dev_label = f"{entry.backend_name} ({entry.connection_key})"

        # widgets
        self.lbl_name = QtWidgets.QLabel(f"{dev_label} / {name}")
        self.chk_on = QtWidgets.QCheckBox("ON")
        self.spin_power = QtWidgets.QDoubleSpinBox()
        #self.spin_power.setRange(0.0, 1000.0)
        lo, hi = self._backend.get_power_range(self._line_id)
        self.spin_power.setRange(lo, hi)
        self.spin_power.setDecimals(1)
        self.spin_power.setSingleStep(0.5)
        self.spin_power.setSuffix(" mW")
        self.btn_set = QtWidgets.QPushButton("Set")

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)
        lay.addWidget(self.lbl_name, 3)
        lay.addWidget(self.chk_on, 0)
        lay.addWidget(self.spin_power, 1)
        lay.addWidget(self.btn_set, 0)

        self.chk_on.toggled.connect(self._on_toggled)
        self.btn_set.clicked.connect(self._on_set_clicked)
        self.spin_power.editingFinished.connect(self._on_set_clicked)

        self.refresh()
        self._load_saved_power()

    def refresh(self):
        """
        backend から状態を読んで UI に反映。
        """
        try:
            on = bool(self._backend.get_enabled(self._line_id))
        except Exception:
            on = False
        try:
            p = float(self._backend.get_power_mw(self._line_id))
        except Exception:
            p = 0.0

        self.chk_on.blockSignals(True)
        self.chk_on.setChecked(on)
        self.chk_on.blockSignals(False)

        self.spin_power.blockSignals(True)
        self.spin_power.setValue(p)
        self.spin_power.blockSignals(False)

    def _settings_key_power(self) -> str:
        """
        QSettings 用のキー:
        例: "Cobolt_Skyra/COM5/488/power_mw"
        """
        return f"{self._entry.backend_name}/{self._entry.connection_key}/{self._line_id}/power_mw"

    def _load_saved_power(self) -> None:
        """
        保存されている power 値があれば SpinBox に反映する。
        （ハードには書き込まず、あくまで初期値としてだけ使う）
        """
        try:
            val = self._settings.value(self._settings_key_power(), None, float)
        except TypeError:
            val = None

        if val is None:
            return

        try:
            lo, hi = self._backend.get_power_range(self._line_id)
        except Exception:
            lo, hi = 0.0, 1000.0

        p = max(lo, min(hi, float(val)))  # レンジ内にクリップ

        self.spin_power.blockSignals(True)
        self.spin_power.setValue(p)
        self.spin_power.blockSignals(False)

    @QtCore.Slot(bool)
    def _on_toggled(self, checked: bool):
        try:
            self._backend.set_enabled(self._line_id, checked)
            self.sig_status.emit(
                f"{self._entry.backend_name} {self._line_id}: {'ON' if checked else 'OFF'}"
            )
        except Exception as e:
            self.sig_status.emit(f"ON/OFF error ({self._line_id}): {e}")
            # 失敗したら状態を戻す
            self.refresh()

    @QtCore.Slot()
    def _on_set_clicked(self):
        try:
            lo, hi = self._backend.get_power_range(self._line_id)

            p = float(self.spin_power.value())
            self._backend.set_power_mw(self._line_id, p)

            # QSettings に保存
            try:
                self._settings.setValue(self._settings_key_power(), p)
            except Exception:
                pass

            # ステータスに Max を付けて表示
            self.sig_status.emit(
                f"{self._entry.backend_name} {self._line_id}: power = {p:.3f} mW (Max: {hi:.1f} mW)"
            )
        except Exception as e:
            self.sig_status.emit(f"Set power error ({self._line_id}): {e}")
            self.refresh()


class LaserPane(QtWidgets.QGroupBox):
    """
    Laser backend マネージャ。
    - backend 選択コンボ + Connect ボタンで 1 デバイスずつ追加
    - 複数デバイスを self._devices で管理
    - 全 line を縦に並べて ON/OFF + power を制御
    - 全 line の wavelength を sig_lines / get_all_wavelengths で提供
    """

    sig_status = QtCore.Signal(str)
    sig_lines = QtCore.Signal(list)  # list of wavelength (nm) / string

    def __init__(self, parent=None):
        super().__init__("Laser", parent=parent)

        self._backend_defs: Dict[str, Dict[str, Any]] = {}
        self._devices: List[LaserDeviceEntry] = []
        self._used_keys: set[str] = set()
        self._line_controls: List[LaserLineControl] = []
        self._settings = QtCore.QSettings("LabSuite", "LaserPane")

        # top controls
        self.lbl_backend = QtWidgets.QLabel("Laser backend:")
        self.cmb_backend = QtWidgets.QComboBox()
        self.btn_refresh = QtWidgets.QPushButton("Refresh States")
        self.btn_connect = QtWidgets.QPushButton("Connect")
        self.lbl_status = QtWidgets.QLabel("Status: No devices connected")

        top_h = QtWidgets.QHBoxLayout()
        top_h.setContentsMargins(4, 4, 4, 4)
        top_h.setSpacing(6)
        top_h.addWidget(self.lbl_backend)
        top_h.addWidget(self.cmb_backend, 1)
        top_h.addWidget(self.btn_connect)
        top_h.addWidget(self.btn_refresh)

        # line controls layout
        self._lines_layout = QtWidgets.QVBoxLayout()
        self._lines_layout.setContentsMargins(4, 4, 4, 4)
        self._lines_layout.setSpacing(4)
        self._lines_layout.addStretch(1)

        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(top_h)
        lay.addLayout(self._lines_layout)
        lay.addWidget(self.lbl_status)

        self.btn_connect.clicked.connect(self._on_connect_clicked)
        self.btn_refresh.clicked.connect(self.refresh_states)

        self._reload_backends()

    # ---- backend スキャン ----
    def _reload_backends(self):
        self._backend_defs = scan_laser_backends()
        self.cmb_backend.clear()
        for name in sorted(self._backend_defs.keys()):
            self.cmb_backend.addItem(name, name)

        has_backends = self.cmb_backend.count() > 0
        self.btn_connect.setEnabled(has_backends)
        if not has_backends:
            self._set_status("No laser backend found in laser_backends/")
        else:
            self._set_status("Select backend and press Connect.")
        
        last = self._settings.value("last_backend", "", str)
        if last:
            idx = self.cmb_backend.findText(last)
            if idx >= 0:
                self.cmb_backend.setCurrentIndex(idx)        

    # ---- line UI ----
    def _clear_line_controls(self):
        while self._lines_layout.count():
            item = self._lines_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        self._line_controls.clear()
        # stretch を戻す
        self._lines_layout.addStretch(1)

    def _rebuild_lines_ui(self):
        self._clear_line_controls()

        # 全デバイス・全ラインを一括で集めて wavelength_nm でソート
        pairs: list[tuple[float, LaserDeviceEntry, Dict[str, Any]]] = []
        for entry in self._devices:
            for line in entry.lines:
                wl = line.get("wavelength_nm")
                # None や不正値は後ろに回すため大きな値に
                if isinstance(wl, (int, float)):
                    key = float(wl)
                else:
                    key = 999999.0
                pairs.append((key, entry, line))

        pairs.sort(key=lambda t: t[0])

        for _, entry, line in pairs:
            ctrl = LaserLineControl(entry, line, parent=self)
            ctrl.sig_status.connect(self._set_status)
            # stretch の手前に挿入
            idx = max(0, self._lines_layout.count() - 1)
            self._lines_layout.insertWidget(idx, ctrl)
            self._line_controls.append(ctrl)

        self._emit_lines()


    # ---- wavelength 集約 ----
    def _emit_lines(self):
        wls: List[Any] = []
        for entry in self._devices:
            for line in entry.lines:
                wl = line.get("wavelength_nm")
                if wl is not None:
                    wls.append(wl)
        self.sig_lines.emit(wls)

    def get_all_wavelengths(self) -> List[Any]:
        """
        MainWindow から呼ぶための helper。
        現在接続されている全 line の wavelength を返す。
        """
        wls: List[Any] = []
        for entry in self._devices:
            for line in entry.lines:
                wl = line.get("wavelength_nm")
                if wl is not None:
                    wls.append(wl)
        return wls

    # ---- connect 処理 ----
    def _on_connect_clicked(self):
        idx = self.cmb_backend.currentIndex()
        if idx < 0:
            self._set_status("No backend selected.")
            return
        key = self.cmb_backend.itemData(idx)
        if not key:
            self._set_status("No backend selected.")
            return

        # ここで記憶する
        self._settings.setValue("last_backend", key)

        info = self._backend_defs.get(key)
        if not info:
            self._set_status(f"Backend '{key}' not found.")
            return

        cls = info["class"]
        try:
            backend: ILaserBackend = cls(parent=self)
        except Exception as e:
            self._set_status(f"Failed to instantiate backend '{key}': {e}")
            return

        backend.sig_error.connect(self._set_status)
        backend.sig_connected.connect(
            lambda ok, name=key: self._on_backend_connected(name, ok)
        )

        # setup dialog
        if not backend.show_setup_dialog(parent=self):
            backend.deleteLater()
            return

        # connection key 取得
        try:
            conn_key = backend.get_connection_key()
        except Exception as e:
            self._set_status(f"get_connection_key() failed: {e}")
            backend.deleteLater()
            return

        if not conn_key:
            self._set_status("Backend returned empty connection key.")
            backend.deleteLater()
            return

        if conn_key in self._used_keys:
            self._set_status(f"Device with key '{conn_key}' is already connected.")
            backend.deleteLater()
            return

        # 実際の接続
        self._set_status(f"Connecting {key} ({conn_key}) ...")
        QtWidgets.QApplication.processEvents()

        if not backend.connect():
            # backend 側で sig_error が emit されている想定
            backend.deleteLater()
            return

        # line 情報取得
        try:
            lines = backend.get_lines()
        except Exception as e:
            self._set_status(f"get_lines() failed: {e}")
            backend.disconnect()
            backend.deleteLater()
            return

        if not lines:
            self._set_status("No lines reported by backend.")
            backend.disconnect()
            backend.deleteLater()
            return

        entry = LaserDeviceEntry(
            backend=backend,
            backend_name=str(key),
            connection_key=str(conn_key),
            lines=list(lines),
        )
        self._devices.append(entry)
        self._used_keys.add(str(conn_key))

        self._rebuild_lines_ui()
        self._update_status_devices()

    def _on_backend_connected(self, name: str, ok: bool):
        if ok:
            self._update_status_devices()
        else:
            self._set_status(f"Backend '{name}' disconnected.")
            # disconnect 側から on_shutdown 相当で整理される想定（ここでは何もしない）

    def _update_status_devices(self):
        n = len(self._devices)
        self._set_status(f"{n} device(s) connected.")

    # ---- public helpers ----
    def refresh_states(self):
        """
        全 line の状態を backend から読み直して UI を更新する。
        """
        for ctrl in self._line_controls:
            ctrl.refresh()
        self._set_status("States refreshed.")

    def _set_status(self, s: str):
        self.lbl_status.setText(f"Status: {s}")
        self.sig_status.emit(s)

    def on_shutdown(self):
        """
        MainWindow.on_shutdown から呼ばれる。
        全 backend を安全に停止する。
        """
        for entry in self._devices:
            try:
                entry.backend.emergency_shutdown()
            except Exception:
                pass
            try:
                entry.backend.disconnect()
            except Exception:
                pass
        self._devices.clear()
        self._used_keys.clear()
        self._clear_line_controls()
        self._set_status("Shutdown.")
