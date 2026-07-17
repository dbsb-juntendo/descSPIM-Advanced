# galvo_integration.py
# -*- coding: utf-8 -*-
# Copyright © 2026 Kiyotada Naitou
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0


from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Type
import logging
import importlib
import inspect
import pathlib
import pkgutil

from PySide6 import QtWidgets, QtCore

from galvo_backends.galvo_backend_base import IGalvoBackend

logger = logging.getLogger(__name__)

BACKENDS_PACKAGE = "galvo_backends"


# ===== backend 自動検出 =====

def scan_galvo_backends() -> Dict[str, Type[IGalvoBackend]]:
    """
    Scan galvo_backends/ and return {filename(UI name): BackendClass}.
    """
    result: Dict[str, Type[IGalvoBackend]] = {}

    try:
        pkg = importlib.import_module(BACKENDS_PACKAGE)
    except ImportError:
        logger.warning("galvo_backends package not found.")
        return result

    pkg_paths: List[str] = []
    try:
        if hasattr(pkg, "__path__"):
            pkg_paths = [str(p) for p in pkg.__path__]
        elif getattr(pkg, "__file__", None):
            pkg_paths = [str(pathlib.Path(pkg.__file__).parent)]
        else:
            logger.warning("galvo_backends has neither __path__ nor __file__.")
            return result
    except Exception as e:
        logger.exception("Failed to resolve galvo_backends path: %s", e)
        return result

    for info in pkgutil.iter_modules(pkg_paths):
        name = info.name
        if name.startswith("_") or name == "galvo_backend_base":
            continue

        module_name = f"{BACKENDS_PACKAGE}.{name}"
        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            logger.exception("Failed to import galvo backend module %s: %s", module_name, e)
            continue

        backend_cls: Optional[Type[IGalvoBackend]] = None

        # Prefer get_backend_class()
        if hasattr(module, "get_backend_class"):
            try:
                backend_cls = module.get_backend_class()
            except Exception as e:
                logger.exception("get_backend_class() failed in %s: %s", module_name, e)

        # Fallback: find subclass of IGalvoBackend
        if backend_cls is None:
            for obj in module.__dict__.values():
                if inspect.isclass(obj) and issubclass(obj, IGalvoBackend) and obj is not IGalvoBackend:
                    backend_cls = obj
                    break

        if backend_cls is None:
            continue

        display_name = name
        result[display_name] = backend_cls

    return result


# ===== GalvoPane 内部モデル =====

@dataclass
class GalvoDeviceEntry:
    backend: IGalvoBackend
    backend_name: str
    connection_key: str
    channels: List[Dict[str, Any]]  # [{"id": "CH1", "name": "CH1"}, ...]


@dataclass
class ChannelWidgetEntry:
    device: GalvoDeviceEntry
    ch_id: str
    widget: QtWidgets.QWidget
    wave_combo: QtWidgets.QComboBox
    freq_spin: QtWidgets.QDoubleSpinBox
    amp_spin: QtWidgets.QDoubleSpinBox
    offset_spin: QtWidgets.QDoubleSpinBox
    enable_check: QtWidgets.QPushButton  # toggle button (CH On/Off)


class GalvoPane(QtWidgets.QGroupBox):
    """
    GalvoPane = manager of all Galvo devices.

    Top   : backend combo + Rescan + Connect
    Center: per-device card (1 device = 1 card)
            - 1st row in card: header (On/Off, Waveform, Frequency, Amplitude, Offset)
            - 2nd+ rows      : each channel (CH1, CH2, ...)
    Bottom: status label

    Multiple backends / multiple devices can be connected simultaneously.
    """

    FREQ_LIMITS = {
        "sine": 250.0,      # DC–250 Hz
        "square": 100.0,    # DC–100 Hz
        "triangle": 175.0,  # DC–175 Hz
        "sawtooth": 175.0,  # DC–175 Hz
    }

    sig_status = QtCore.Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__("Galvo Control", parent=parent)

        self.settings = QtCore.QSettings("LabSuite", "GalvoControl")
        self._backend_classes: Dict[str, Type[IGalvoBackend]] = {}
        self._devices: List[GalvoDeviceEntry] = []
        self._channels: List[ChannelWidgetEntry] = []
        self._used_keys: set[str] = set()

        # ---- top row: backend selection ----
        self.cmb_backend = QtWidgets.QComboBox()
        self.btn_rescan = QtWidgets.QPushButton("Rescan")
        self.btn_connect = QtWidgets.QPushButton("Connect")
        self.lbl_status = QtWidgets.QLabel("Status: No backend connected")

        top_h = QtWidgets.QHBoxLayout()
        top_h.setContentsMargins(4, 4, 4, 4)
        top_h.setSpacing(6)
        top_h.addWidget(QtWidgets.QLabel("Backend:"))
        top_h.addWidget(self.cmb_backend, 1)
        top_h.addWidget(self.btn_rescan)
        top_h.addWidget(self.btn_connect)

        # ---- center: container for per-device cards ----
        self.channel_container = QtWidgets.QWidget(self)
        self.channel_layout = QtWidgets.QVBoxLayout(self.channel_container)
        self.channel_layout.setContentsMargins(4, 4, 4, 4)
        self.channel_layout.setSpacing(6)
        self.channel_layout.addStretch(1)

        # ---- whole layout ----
        lay = QtWidgets.QVBoxLayout(self)
        lay.addLayout(top_h)
        lay.addWidget(self.channel_container)
        lay.addWidget(self.lbl_status)

        # ---- wiring ----
        self.btn_rescan.clicked.connect(self._rescan_backends)
        self.btn_connect.clicked.connect(self._on_connect_clicked)

        self._rescan_backends()

    # ===== backend scan =====

    def _rescan_backends(self) -> None:
        self._backend_classes = scan_galvo_backends()
        self.cmb_backend.clear()

        for name in sorted(self._backend_classes.keys()):
            self.cmb_backend.addItem(name)

        if not self._backend_classes:
            self.btn_connect.setEnabled(False)
            self._set_status("No galvo backends found. Please check galvo_backends/.")
        else:
            self.btn_connect.setEnabled(True)
            self._set_status("Select a backend and press Connect.")
            # ← ここで最後に選んだ backend を復帰
            self._load_last_backend()

    def _load_last_backend(self) -> None:
        """Restore last selected backend into combo box."""
        last = self.settings.value("last_backend", "", str)
        if not last:
            return
        idx = self.cmb_backend.findText(last)
        if idx >= 0:
            self.cmb_backend.setCurrentIndex(idx)

    # ===== device connection =====

    @QtCore.Slot()
    def _on_connect_clicked(self) -> None:
        backend_name = self.cmb_backend.currentText()
        if not backend_name:
            self._set_status("No backend selected.")
            return

        backend_cls = self._backend_classes.get(backend_name)
        if backend_cls is None:
            self._set_status(f"Backend '{backend_name}' not found.")
            return

        backend: IGalvoBackend = backend_cls(self)

        # 1) setup dialog (e.g., COM port)
        if not backend.show_setup_dialog(self):
            backend.deleteLater()
            self._set_status("Connection canceled.")
            return

        # 2) connection_key for duplicate prevention
        key = backend.get_connection_key()
        if not key:
            backend.deleteLater()
            self._set_status("Backend did not return a connection_key.")
            return

        if key in self._used_keys:
            backend.deleteLater()
            self._set_status(f"{backend_name} ({key}) is already connected.")
            return

        # 3) connect()
        if not backend.connect():
            backend.deleteLater()
            self._set_status(f"Failed to connect to {backend_name} ({key}).")
            return

        # 4) channel info
        try:
            channels = backend.get_channels() or []
        except Exception as e:
            self._set_status(f"get_channels() error: {e}")
            backend.disconnect()
            backend.deleteLater()
            return

        if not channels:
            self._set_status(f"{backend_name} ({key}) has no channels.")
            backend.disconnect()
            backend.deleteLater()
            return

        device_entry = GalvoDeviceEntry(
            backend=backend,
            backend_name=backend_name,
            connection_key=key,
            channels=channels,
        )
        self._devices.append(device_entry)
        self._used_keys.add(key)

        backend.sig_error.connect(self._set_status)
        backend.sig_connected.connect(self._on_backend_connected_state)
        backend.sig_state_changed.connect(self._on_backend_state_changed)

        # add per-device card
        self._add_device_channels(device_entry)

        # remember this backend as last used
        self.settings.setValue("last_backend", backend_name)
        self.settings.sync()
        
        self._set_status(f"Connected: {backend_name} ({key})")

    # ===== per-device card generation =====

    def _add_device_channels(self, device: GalvoDeviceEntry) -> None:
        """
        Add one device card:
        - row 0: header (On/Off, Waveform, Frequency, Amplitude, Offset)
        - row 1+: one row per channel
        """
        try:
            state = device.backend.query_status() or {}
        except Exception:
            state = {}
        channels_state = state.get("channels", {}) if isinstance(state, dict) else {}

        # remove trailing stretch temporarily
        if self.channel_layout.count() > 0:
            last_item = self.channel_layout.itemAt(self.channel_layout.count() - 1)
            if last_item and last_item.spacerItem():
                self.channel_layout.takeAt(self.channel_layout.count() - 1)

        # device card = QGroupBox with device title
        card = QtWidgets.QGroupBox(self.channel_container)
        card.setTitle(f"{device.backend_name} ({device.connection_key})")

        grid = QtWidgets.QGridLayout(card)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        # header row (row 0)
        header_onoff = QtWidgets.QLabel("On/Off")
        header_wave = QtWidgets.QLabel("Waveform")
        header_freq = QtWidgets.QLabel("Frequency")
        header_amp = QtWidgets.QLabel("Amplitude")
        header_off = QtWidgets.QLabel("Offset")

        for lbl in (header_onoff, header_wave, header_freq, header_amp, header_off):
            lbl.setAlignment(QtCore.Qt.AlignCenter)

        grid.addWidget(header_onoff, 0, 0)
        grid.addWidget(header_wave,  0, 1)
        grid.addWidget(header_freq,  0, 2)
        grid.addWidget(header_amp,   0, 3)
        grid.addWidget(header_off,   0, 4)

        # channel rows (row 1+)
        for row_offset, ch_info in enumerate(device.channels, start=1):
            ch_id = str(ch_info.get("id") or ch_info.get("name"))
            ch_name = str(ch_info.get("name") or ch_id)

            # On/Off toggle button
            enable_btn = QtWidgets.QPushButton()
            # default false; will be updated later by state/settings
            self._update_enable_button_appearance(enable_btn, False, ch_name)

            # waveform
            wave_combo = QtWidgets.QComboBox()
            wave_combo.addItems(["sine", "square", "triangle", "sawtooth"])

            # frequency
            freq_spin = QtWidgets.QDoubleSpinBox()
            freq_spin.setDecimals(3)
            freq_spin.setRange(0.0, 250.0)
            freq_spin.setValue(100.0)
            freq_spin.setSuffix(" Hz")

            # amplitude
            amp_spin = QtWidgets.QDoubleSpinBox()
            amp_spin.setDecimals(3)
            amp_spin.setRange(0.0, 10.0)  # ±12.5° × 0.8 V/deg ≒ 10 V peak
            amp_spin.setValue(5.0)
            amp_spin.setSuffix(" V")

            # offset
            offset_spin = QtWidgets.QDoubleSpinBox()
            offset_spin.setDecimals(3)
            offset_spin.setRange(-10.0, 10.0)
            offset_spin.setValue(0.0)
            offset_spin.setSuffix(" V")

            grid.addWidget(enable_btn,  row_offset, 0)
            grid.addWidget(wave_combo,  row_offset, 1)
            grid.addWidget(freq_spin,   row_offset, 2)
            grid.addWidget(amp_spin,    row_offset, 3)
            grid.addWidget(offset_spin, row_offset, 4)

            entry = ChannelWidgetEntry(
                device=device,
                ch_id=ch_id,
                widget=card,
                wave_combo=wave_combo,
                freq_spin=freq_spin,
                amp_spin=amp_spin,
                offset_spin=offset_spin,
                enable_check=enable_btn,
            )
            self._channels.append(entry)

            # 1) apply backend state
            ch_state = channels_state.get(ch_id, {})
            self._apply_state_to_channel_from_backend(entry, ch_state)

            # 2) override with QSettings (if any)
            self._restore_channel_settings(entry)

            # 3) adjust freq limit to current waveform
            self._update_freq_limit(entry, entry.wave_combo.currentText())

            # 4) update ON/OFF button appearance to final state
            enabled_now = bool(entry.enable_check.isChecked())
            self._update_enable_button_appearance(entry.enable_check, enabled_now, ch_name)

            # 5) connect signals
            wave_combo.currentTextChanged.connect(
                lambda wave, e=entry: self._on_waveform_changed(e, wave)
            )
            freq_spin.valueChanged.connect(
                lambda val, e=entry: self._on_freq_changed(e, float(val))
            )
            amp_spin.valueChanged.connect(
                lambda val, e=entry: self._on_amp_changed(e, float(val))
            )
            offset_spin.valueChanged.connect(
                lambda val, e=entry: self._on_offset_changed(e, float(val))
            )
            enable_btn.toggled.connect(
                lambda checked, e=entry: self._on_enable_toggled(e, bool(checked))
            )

            # 6) apply final state to backend (initial auto-apply)
            self._apply_channel_to_backend(entry, emit_status=False)

        # add device card to layout
        self.channel_layout.addWidget(card)

        # restore stretch at bottom
        self.channel_layout.addStretch(1)

        # save settings
        self._save_settings()

    # ===== backend state -> channel widgets =====

    def _apply_state_to_channel_from_backend(
        self,
        entry: ChannelWidgetEntry,
        ch_state: Dict[str, Any],
    ) -> None:
        if not isinstance(ch_state, dict):
            return

        wave = ch_state.get("waveform")
        if isinstance(wave, str):
            idx = entry.wave_combo.findText(wave)
            if idx >= 0:
                entry.wave_combo.setCurrentIndex(idx)

        freq = ch_state.get("freq")
        if isinstance(freq, (int, float)):
            entry.freq_spin.setValue(float(freq))

        amp = ch_state.get("amp")
        if isinstance(amp, (int, float)):
            entry.amp_spin.setValue(float(amp))

        offset = ch_state.get("offset")
        if isinstance(offset, (int, float)):
            entry.offset_spin.setValue(float(offset))

        enabled = ch_state.get("enabled")
        if isinstance(enabled, bool):
            entry.enable_check.setCheckable(True)
            entry.enable_check.setChecked(enabled)

    # ===== QSettings (per connection_key + ch_id) =====

    def _settings_key_for_channel(self, entry: ChannelWidgetEntry, suffix: str) -> str:
        return f"{entry.device.connection_key}/{entry.ch_id}/{suffix}"

    def _restore_channel_settings(self, entry: ChannelWidgetEntry) -> None:
        keys = ("wave", "freq", "amp", "offset", "enabled")
        has_any = any(
            self.settings.contains(self._settings_key_for_channel(entry, k))
            for k in keys
        )
        if not has_any:
            return

        wave = self.settings.value(
            self._settings_key_for_channel(entry, "wave"), None, str
        )
        if wave:
            idx = entry.wave_combo.findText(wave)
            if idx >= 0:
                entry.wave_combo.setCurrentIndex(idx)

        freq = self.settings.value(
            self._settings_key_for_channel(entry, "freq"), None, float
        )
        if freq is not None:
            entry.freq_spin.setValue(float(freq))

        amp = self.settings.value(
            self._settings_key_for_channel(entry, "amp"), None, float
        )
        if amp is not None:
            entry.amp_spin.setValue(float(amp))

        offset = self.settings.value(
            self._settings_key_for_channel(entry, "offset"), None, float
        )
        if offset is not None:
            entry.offset_spin.setValue(float(offset))

        enabled = self.settings.value(
            self._settings_key_for_channel(entry, "enabled"), None, bool
        )
        if enabled is not None:
            entry.enable_check.setCheckable(True)
            entry.enable_check.setChecked(bool(enabled))

    def _save_settings(self) -> None:
        for entry in self._channels:
            self.settings.setValue(
                self._settings_key_for_channel(entry, "wave"),
                entry.wave_combo.currentText(),
            )
            self.settings.setValue(
                self._settings_key_for_channel(entry, "freq"),
                float(entry.freq_spin.value()),
            )
            self.settings.setValue(
                self._settings_key_for_channel(entry, "amp"),
                float(entry.amp_spin.value()),
            )
            self.settings.setValue(
                self._settings_key_for_channel(entry, "offset"),
                float(entry.offset_spin.value()),
            )
            self.settings.setValue(
                self._settings_key_for_channel(entry, "enabled"),
                bool(entry.enable_check.isChecked()),
            )
        self.settings.sync()

    # ===== UI -> backend apply =====

    def _apply_channel_to_backend(self, entry: ChannelWidgetEntry, emit_status: bool = True) -> None:
        backend = entry.device.backend
        ch_id = entry.ch_id

        wave = entry.wave_combo.currentText()
        freq = float(entry.freq_spin.value())
        amp = float(entry.amp_spin.value())
        offset = float(entry.offset_spin.value())
        enabled = bool(entry.enable_check.isChecked())

        try:
            backend.set_waveform(ch_id, wave)
            backend.set_freq(ch_id, freq)
            backend.set_amp(ch_id, amp)
            backend.set_offset(ch_id, offset)
            backend.set_enabled(ch_id, enabled)
        except Exception as e:
            self._set_status(f"{ch_id}: apply error: {e}")
            return

        if emit_status:
            self._set_status(
                f"{ch_id}: "
                f"{wave} / {freq:.3f} Hz / {amp:.3f} Vpp / offset={offset:.3f} V / "
                f"{'ON' if enabled else 'OFF'}"
            )

    # ===== frequency limit =====

    def _update_freq_limit(self, entry: ChannelWidgetEntry, wave: str) -> None:
        max_f = float(self.FREQ_LIMITS.get(wave, 100.0))
        spin = entry.freq_spin
        current = spin.value()
        spin.setRange(0.0, max_f)
        if current > max_f:
            spin.setValue(max_f)

    # ===== UI signal handlers =====

    def _on_waveform_changed(self, entry: ChannelWidgetEntry, wave: str) -> None:
        self._update_freq_limit(entry, wave)
        self._apply_channel_to_backend(entry, emit_status=True)
        self._save_settings()

    def _on_freq_changed(self, entry: ChannelWidgetEntry, value: float) -> None:
        self._apply_channel_to_backend(entry, emit_status=True)
        self._save_settings()

    def _on_amp_changed(self, entry: ChannelWidgetEntry, value: float) -> None:
        self._apply_channel_to_backend(entry, emit_status=True)
        self._save_settings()

    def _on_offset_changed(self, entry: ChannelWidgetEntry, value: float) -> None:
        self._apply_channel_to_backend(entry, emit_status=True)
        self._save_settings()

    def _on_enable_toggled(self, entry: ChannelWidgetEntry, checked: bool) -> None:
        # first apply to backend & save
        self._apply_channel_to_backend(entry, emit_status=True)
        self._save_settings()
        # then update button appearance
        ch_name = entry.ch_id
        self._update_enable_button_appearance(entry.enable_check, checked, ch_name)

    # ===== backend signals =====

    def _on_backend_connected_state(self, connected: bool) -> None:
        # currently unused; reserved for future
        _ = connected

    def _on_backend_state_changed(self, state: object) -> None:
        # currently unused; reserved for future
        _ = state

    # ===== common utils =====

    def _update_enable_button_appearance(
        self,
        button: QtWidgets.QPushButton,
        enabled: bool,
        ch_name: str,
    ) -> None:
        """
        Update text and background color of CH On/Off toggle button.
        """
        button.setCheckable(True)
        button.setChecked(enabled)
        button.setText(f"{ch_name} {'ON' if enabled else 'OFF'}")

        pal = button.palette()
        role = button.backgroundRole()
        pal.setColor(
            role,
            QtCore.Qt.GlobalColor.green if enabled else QtCore.Qt.GlobalColor.red,
        )
        button.setAutoFillBackground(True)
        button.setPalette(pal)

    def _set_status(self, s: str) -> None:
        self.lbl_status.setText(f"Status: {s}")
        self.sig_status.emit(s)

    # ===== external API =====

    def emergency_shutdown_all(self) -> None:
        """
        Emergency stop from orchestrator:
        call emergency_shutdown() for all backends.
        """
        for dev in self._devices:
            try:
                dev.backend.emergency_shutdown()
            except Exception as e:
                self._set_status(f"{dev.backend_name}: emergency_shutdown error: {e}")

    def on_shutdown(self) -> None:
        """
        Called from MainWindow.on_shutdown():
        - save settings
        - emergency_shutdown + disconnect all Galvo devices
        """
        try:
            self._save_settings()
        except Exception:
            pass

        for dev in self._devices:
            try:
                dev.backend.emergency_shutdown()
            except Exception:
                pass
            try:
                dev.backend.disconnect()
            except Exception:
                pass

        self._devices.clear()
        self._channels.clear()
        self._used_keys.clear()
