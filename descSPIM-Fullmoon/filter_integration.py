# # -*- coding: utf-8 -*-
"""
filter_integration.py

Filter 用の UI / Integration 層（FilterPane）。
- Backend プラグイン (IFilterBackend) を 1 台だけ管理。
- 接続後は Backend 選択 UI を隠し、Slot UI + フォーカス補正 UI を同じパネル内で表示。
- フォーカス補正は FilterController が Stage (camera axis) を操作するが、
  実際に移動させるタイミングは main.py が決定する。
"""

from __future__ import annotations

import json
import importlib
import pkgutil
from typing import List, Dict, Optional, Tuple, Type

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QObject, Signal, Slot, QSettings, Qt

from filter_backends.filter_backend_base import IFilterBackend


SETTINGS_PREFIX_FOCUS = "Filters"
SETTINGS_PREFIX_PANE = "FilterPane"


# ============================================================
# 1) Stage フォーカス補正用 Controller（旧 FilterController）
# ============================================================
class FilterController(QObject):
    sig_positions_updated = Signal(dict)   # { "name": mm_value, ... } (外部向けは mm)
    sig_status = Signal(str)
    sig_error = Signal(str)

    def __init__(self, camera_device=None, profile: str = "default", parent=None):
        super().__init__(parent)
        self.camera = camera_device     # camera stage
        self.profile = profile
        self.settings = QSettings("LabSuite", "StageControl")
        self.wavelengths: List[str] = []
        self._positions_counts: Dict[str, int] = {}
        self._load_from_settings()

    # ----- persistence (保存は counts) -----
    def _settings_key(self, key: str) -> str:
        return f"{SETTINGS_PREFIX_FOCUS}/{self.profile}/{key}"

    def _save_to_settings(self):
        try:
            self.settings.setValue(
                self._settings_key("positions_json"),
                json.dumps(self._positions_counts),
            )
            self.settings.sync()
            self.sig_status.emit("filter positions saved")
        except Exception as e:
            self.sig_error.emit(f"save_settings: {e}")

    def _load_from_settings(self):
        try:
            raw = self.settings.value(self._settings_key("positions_json"), "")
            if raw:
                d = json.loads(raw)
                self._positions_counts = {k: int(v) for k, v in d.items()}
            else:
                self._positions_counts = {}
            self.sig_positions_updated.emit(self.get_positions_mm())
        except Exception as e:
            self.sig_error.emit(f"load_settings: {e}")

    # ----- configuration -----
    def set_camera_device(self, device):
        self.camera = device

    def set_wavelengths(self, wavelengths: List[str]):
        # ここでは単にキーとして使うだけなので、実際は「filter 名」
        self.wavelengths = wavelengths

    # ----- helpers: counter <-> mm -----
    def _get_current_count(self) -> int:
        if self.camera is None:
            raise RuntimeError("camera stage not set")
        try:
            from xa_sdk.shared.tlmc_type_structures import TLMC_Wait  # type: ignore
            return int(self.camera.get_position_counter(TLMC_Wait.TLMC_InfiniteWait))
        except Exception:
            try:
                return int(self.camera.get_position_counter())
            except Exception as e:
                raise RuntimeError(f"_get_current_count: unable to read counter: {e}")

    def _count_to_mm(self, count: int) -> Optional[float]:
        if self.camera is None:
            return None
        try:
            from xa_sdk.shared.tlmc_type_structures import TLMC_ScaleType  # type: ignore
            phys = self.camera.convert_from_device_units_to_physical(
                TLMC_ScaleType.TLMC_ScaleType_Distance, int(count)
            )
            return float(getattr(phys, "converted_value", phys))
        except Exception:
            try:
                phys = self.camera.convert_from_device_units_to_physical(int(count))
                return float(getattr(phys, "converted_value", phys))
            except Exception:
                return None

    def _mm_to_count(self, mm: float) -> int:
        if self.camera is None:
            raise RuntimeError("camera stage not set")
        try:
            from xa_sdk.shared.tlmc_type_structures import TLMC_ScaleType, TLMC_Unit  # type: ignore
            return int(
                round(
                    self.camera.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Distance,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        float(mm),
                    )
                )
            )
        except Exception:
            try:
                return int(round(self.camera.convert_from_physical_to_device(float(mm))))
            except Exception as e:
                raise RuntimeError(f"_mm_to_count: {e}")

    # ----- register / apply (外部は mm 単位 API) -----
    @Slot(str)
    def register_position_mm(
        self,
        wavelength: str,
        mm_override: Optional[float] = None,
        count_override: Optional[int] = None,
    ):
        try:
            if self.camera is None:
                raise RuntimeError("camera stage not set")
            if not wavelength:
                raise ValueError("wavelength required")

            if count_override is not None:
                cnt = int(count_override)
            elif mm_override is not None:
                cnt = int(self._mm_to_count(float(mm_override)))
            else:
                cnt = int(self._get_current_count())

            self._positions_counts[wavelength] = cnt
            self._save_to_settings()
            self.sig_positions_updated.emit(self.get_positions_mm())

            mm_val = self._count_to_mm(cnt)
            if mm_val is None:
                self.sig_status.emit(f"Registered position for {wavelength}: count={cnt}")
            else:
                self.sig_status.emit(
                    f"Registered position for {wavelength}: {mm_val:+.6f} mm"
                )
        except Exception as e:
            self.sig_error.emit(f"register_position_mm: {e}")

    @Slot(str)
    def apply_position_mm(self, wavelength: str):
        """
        「絶対位置へ寄せる」ための API（手動で使いたい場合用）。
        main.py からの同期制御では使用しない。
        """
        try:
            if self.camera is None:
                raise RuntimeError("camera stage not set")
            if wavelength not in self._positions_counts:
                raise RuntimeError(f"no registered position for {wavelength}")

            target_count = int(self._positions_counts[wavelength])
            current_count = int(self._get_current_count())
            delta = int(round(target_count - current_count))

            if delta == 0:
                self.sig_status.emit(
                    f"No move required for {wavelength} (already at registered position)."
                )
                return

            self._do_move_relative(delta, f"apply:{wavelength}", current_count, target_count)
        except Exception as e:
            self.sig_error.emit(f"apply_position_mm: {e}")

    def _do_move_relative(
        self,
        delta_counts: int,
        context_label: str,
        current_count: Optional[int] = None,
        target_count: Optional[int] = None,
    ):
        moved = False
        errs: List[str] = []

        try:
            from xa_sdk.shared.tlmc_type_structures import TLMC_MoveModes, TLMC_Wait  # type: ignore

            try:
                self.camera.move_relative(
                    TLMC_MoveModes.MoveMode_RelativeByProgrammed,
                    int(delta_counts),
                    TLMC_Wait.TLMC_InfiniteWait,
                )
                moved = True
            except Exception as e1:
                errs.append(f"RelByProg: {e1}")
                try:
                    self.camera.move_relative(
                        TLMC_MoveModes.MoveMode_Relative,
                        int(delta_counts),
                        TLMC_Wait.TLMC_InfiniteWait,
                    )
                    moved = True
                except Exception as e2:
                    errs.append(f"Rel: {e2}")
        except Exception as e:
            errs.append(f"enum-fallback: {e}")

        if not moved:
            try:
                try:
                    self.camera.move_relative(int(delta_counts))
                    moved = True
                except Exception:
                    self.camera.move_relative(int(delta_counts), 0xFFFFFFFF)
                    moved = True
            except Exception as e:
                errs.append(f"simple-fallbacks: {e}")

        if not moved:
            raise RuntimeError("move_relative failed; tried: " + " | ".join(errs))

        try:
            if current_count is None:
                current_count = int(self._get_current_count())
            if target_count is None:
                target_count = int(current_count + delta_counts)
            tgt_mm = self._count_to_mm(target_count)
            cur_mm = self._count_to_mm(current_count)
            if tgt_mm is not None and cur_mm is not None:
                self.sig_status.emit(
                    f"Moved camera by {delta_counts} counts "
                    f"({(tgt_mm - cur_mm):+.6f} mm) [{context_label}]"
                )
            else:
                self.sig_status.emit(
                    f"Moved camera by {delta_counts} counts [{context_label}]"
                )
        except Exception:
            self.sig_status.emit(
                f"Moved camera by {delta_counts} counts [{context_label}]"
            )

    @Slot(str, str)
    def apply_delta_mm(self, from_wl: str, to_wl: str):
        """
        「from フィルタ」と「to フィルタ」の登録位置の差分だけを動かす。
        - どちらか一方でも未登録なら、ステージは動かさずエラーだけ出す。
        """
        try:
            if self.camera is None:
                self.sig_error.emit("camera stage not set")
                return

            if from_wl not in self._positions_counts or to_wl not in self._positions_counts:
                self.sig_error.emit(
                    f"Focus position not registered for filter(s): {from_wl}, {to_wl}"
                )
                return

            c_from = int(self._positions_counts[from_wl])
            c_to = int(self._positions_counts[to_wl])
            delta = int(round(c_to - c_from))
            if delta == 0:
                # 差分が 0 の場合は「動かさない」だが、これは正常系として扱う
                self.sig_status.emit(
                    f"No adjustment needed: {from_wl} → {to_wl} (delta=0)."
                )
                return

            label = f"{from_wl}→{to_wl}"
            cur = int(self._get_current_count())

            from xa_sdk.shared.tlmc_type_structures import (  # type: ignore
                TLMC_ScaleType,
                TLMC_Unit,
            )

            v_orig = self.settings.value("stage_v2_mm_s", 0.01368, float)
            a_orig = self.settings.value("stage_a2_mm_s2", 1.5, float)

            V_FAST = 1.5   # mm/s
            A_FAST = 0.5   # mm/s^2

            fast_applied = False
            try:
                try:
                    v_fast_dev = int(
                        round(
                            self.camera.convert_from_physical_to_device(
                                TLMC_ScaleType.TLMC_ScaleType_Velocity,
                                TLMC_Unit.TLMC_Unit_Millimetres,
                                V_FAST,
                            )
                        )
                    )
                    a_fast_dev = int(
                        round(
                            self.camera.convert_from_physical_to_device(
                                TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                                TLMC_Unit.TLMC_Unit_Millimetres,
                                A_FAST,
                            )
                        )
                    )
                    self.camera.set_velocity_params(0, a_fast_dev, v_fast_dev)
                    fast_applied = True
                except Exception as ee:
                    self.sig_status.emit(
                        f"warning: failed to set fast filter speed: {ee}"
                    )

                self._do_move_relative(
                    delta,
                    label,
                    current_count=cur,
                    target_count=(cur + delta),
                )

            finally:
                if fast_applied:
                    try:
                        v_orig_dev = int(
                            round(
                                self.camera.convert_from_physical_to_device(
                                    TLMC_ScaleType.TLMC_ScaleType_Velocity,
                                    TLMC_Unit.TLMC_Unit_Millimetres,
                                    v_orig,
                                )
                            )
                        )
                        a_orig_dev = int(
                            round(
                                self.camera.convert_from_physical_to_device(
                                    TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                                    TLMC_Unit.TLMC_Unit_Millimetres,
                                    a_orig,
                                )
                            )
                        )
                        self.camera.set_velocity_params(0, a_orig_dev, v_orig_dev)
                    except Exception as ee:
                        self.sig_status.emit(
                            f"warning: failed to restore filter speed: {ee}"
                        )

        except Exception as e:
            self.sig_error.emit(f"apply_delta_mm: {e}")

    def get_positions_mm(self) -> Dict[str, Optional[float]]:
        out: Dict[str, Optional[float]] = {}
        for k, cnt in self._positions_counts.items():
            try:
                mm = self._count_to_mm(int(cnt))
            except Exception:
                mm = None
            out[k] = mm
        return out


# ============================================================
# 2) 登録ダイアログ
# ============================================================
class FilterRegisterDialog(QtWidgets.QDialog):
    """
    Dialog to register camera mm-position for a selected filter name.
    Options: use current camera position, or enter manual mm.
    """

    def __init__(self, controller: FilterController, name: str, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.name = name
        self.setWindowTitle(f"Register camera position for {name}")
        self.resize(460, 160)

        self.lbl_msg = QtWidgets.QLabel(
            "Place camera to the same focal plane for this filter, "
            "then choose how to register."
        )
        self.lbl_msg.setWordWrap(True)

        self.lbl_current = QtWidgets.QLabel("Current counter: (reading...)")
        self.lbl_current.setWordWrap(True)
        self.lbl_mm = QtWidgets.QLabel("Current (mm): (reading...)")
        self.lbl_mm.setWordWrap(True)

        self.rb_use_current = QtWidgets.QRadioButton("Use current camera position")
        self.rb_manual_mm = QtWidgets.QRadioButton("Enter manual mm value (mm)")
        self.rb_group = QtWidgets.QButtonGroup(self)
        self.rb_group.addButton(self.rb_use_current)
        self.rb_group.addButton(self.rb_manual_mm)

        self.le_mm = QtWidgets.QLineEdit()
        self.le_mm.setPlaceholderText("e.g. 0.012 (mm)")
        self.le_mm.setEnabled(False)

        self.rb_use_current.toggled.connect(lambda v: self.le_mm.setEnabled(False))
        self.rb_manual_mm.toggled.connect(lambda v: self.le_mm.setEnabled(v))

        self.btn_ok = QtWidgets.QPushButton("OK")
        self.btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_ok)
        btn_row.addWidget(self.btn_cancel)

        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(self.lbl_msg)
        v.addWidget(self.lbl_current)
        v.addWidget(self.lbl_mm)
        v.addWidget(self.rb_use_current)
        v.addWidget(self.rb_manual_mm)
        v.addWidget(self.le_mm)
        v.addLayout(btn_row)

        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)

        self._populate_readings()
        self.rb_use_current.setChecked(True)

    def _populate_readings(self):
        try:
            try:
                c = int(self.controller._get_current_count())
            except Exception:
                c = None
            if c is None:
                self.lbl_current.setText("Current counter: (unable to read)")
                self.lbl_mm.setText("Current (mm): (unable to read)")
                return
            mm = self.controller._count_to_mm(c)
            self.lbl_current.setText(f"Current counter: {c}")
            self.lbl_mm.setText(
                f"Current (mm): {mm:.6f} mm" if mm is not None else "Current (mm): (unknown)"
            )
        except Exception as e:
            self.lbl_current.setText(f"Read error: {e}")

    def get_result(self) -> Tuple[Optional[str], Optional[int]]:
        if self.result() != QtWidgets.QDialog.Accepted:
            return None, None

        if self.rb_use_current.isChecked():
            c = int(self.controller._get_current_count())
            return "use_current", int(c)

        if self.rb_manual_mm.isChecked():
            try:
                mm = float(self.le_mm.text().strip())
                cnt = self.controller._mm_to_count(mm)
                return "manual_mm", int(cnt)
            except Exception as e:
                raise ValueError(f"invalid manual mm value: {e}")

        return None, None


# ============================================================
# 3) Backend スキャン
# ============================================================
def scan_filter_backends() -> Dict[str, Type[IFilterBackend]]:
    backends: Dict[str, Type[IFilterBackend]] = {}

    package_name = "filter_backends"

    try:
        package = importlib.import_module(package_name)
    except ImportError:
        print("[FilterPane] filter_backends package not found.")
        return backends

    for _, name, ispkg in pkgutil.iter_modules(package.__path__):
        if ispkg or name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{package_name}.{name}")
            get_cls = getattr(module, "get_backend_class", None)
            if callable(get_cls):
                cls = get_cls()
                if isinstance(cls, type) and issubclass(cls, IFilterBackend):
                    backends[name] = cls
        except Exception as e:
            print(f"[FilterPane] failed to load backend '{name}': {e}")

    return backends


# ============================================================
# 4) FilterPane 本体（FocusCorrectionPanel を統合）
# ============================================================
class FilterPane(QtWidgets.QGroupBox):
    """
    Filter backend（1 台）とフォーカス補正 UI をまとめた pane。
    - Backend: IFilterBackend（Manual_Change, Dummy_Simulater など）
    - Focus: FilterController（Stage の camera 軸を操作）

    Filter 状態（position / busy / slot_names）は backend.query_status() を唯一の真実とし、
    FilterPane は Slot 名とフォーカス補正値だけを保持する。
    """

    sig_status = Signal(str)
    sig_error = Signal(str)

    # main.py 向け: フィルタ変更要求（Register OFF でボタンが押されたとき）
    sig_filter_change_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("Filter", parent)

        self.settings = QSettings("LabSuite", "FilterControl")
        self._backend_classes: Dict[str, Type[IFilterBackend]] = scan_filter_backends()
        self.backend: Optional[IFilterBackend] = None

        # 追加: 前回選択した backend 名を保持
        self._last_backend_name: str = self.settings.value(
            f"{SETTINGS_PREFIX_PANE}/last_backend_name", "", str
        )

        # スロット情報
        self._num_slots: int = 0
        self._slot_names: Dict[int, str] = {}
        self._slot_names_initialized: bool = False  # 接続ごとに 1 回だけダイアログ
        self._label_to_slot: Dict[str, int] = {}    # フィルタ名 → スロット番号

        # 最新の backend 状態を保持
        self._current_status: Dict[str, object] = {}

        # フォーカス補正用 Controller
        self._focus_controller = FilterController(
            camera_device=None, profile="default", parent=self
        )

        # 現在のフィルタ名リスト（スロット名）
        self._wavelengths: List[str] = []

        # フィルタボタン
        self._wl_buttons: Dict[str, QtWidgets.QPushButton] = {}

        # ---- UI 構築 ----
        self._build_ui()
        self._update_backend_ui_visibility()

        # Controller のメッセージを Pane のステータスに集約
        self._focus_controller.sig_status.connect(self._on_focus_status)
        self._focus_controller.sig_error.connect(self._on_focus_error)

    # --------------------------------------------------------
    # UI
    # --------------------------------------------------------
    def _build_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(4)

        # --- Connect セクション（上に細く）---
        self._conn_widget = QtWidgets.QWidget(self)
        conn_layout = QtWidgets.QHBoxLayout(self._conn_widget)
        conn_layout.setContentsMargins(0, 0, 0, 0)
        conn_layout.setSpacing(4)

        lbl_backend = QtWidgets.QLabel("Backend:", self._conn_widget)
        self.cmb_backend = QtWidgets.QComboBox(self._conn_widget)
        self.cmb_backend.setEditable(False)

        for name in sorted(self._backend_classes.keys()):
            self.cmb_backend.addItem(name)

        # 追加: 前回選んだ backend をコンボに反映
        if self._last_backend_name:
            idx = self.cmb_backend.findText(self._last_backend_name)
            if idx >= 0:
                self.cmb_backend.setCurrentIndex(idx)

        self.btn_connect = QtWidgets.QPushButton("Connect", self._conn_widget)
        self.btn_connect.setMaximumWidth(90)
        self.btn_connect.clicked.connect(self._on_connect_clicked)

        conn_layout.addWidget(lbl_backend)
        conn_layout.addWidget(self.cmb_backend, 1)
        conn_layout.addWidget(self.btn_connect)

        main_layout.addWidget(self._conn_widget)

        # --- Filter ボタン + チェックボックス 部分 ---
        self._focus_widget = QtWidgets.QWidget(self)
        self._focus_layout = QtWidgets.QVBoxLayout(self._focus_widget)
        self._focus_layout.setContentsMargins(0, 0, 0, 0)
        self._focus_layout.setSpacing(4)

        # 上段: フィルタボタン行
        self._buttons_row = QtWidgets.QHBoxLayout()
        self._buttons_row.setContentsMargins(0, 0, 0, 0)
        self._buttons_row.setSpacing(4)
        self._focus_layout.addLayout(self._buttons_row)

        # 中段: チェックボックス 2 個
        self.chk_register = QtWidgets.QCheckBox("Register focus position", self._focus_widget)
        self.chk_link_stage = QtWidgets.QCheckBox("Synchronize with camera stage", self._focus_widget)
        self.chk_register.setVisible(False)
        self.chk_link_stage.setVisible(False)

        # Register モード ON/OFF でハイライト挙動を切り替え
        self.chk_register.toggled.connect(self._on_register_toggled)

        self._checks_widget = QtWidgets.QWidget(self._focus_widget)
        self._checks_layout = QtWidgets.QHBoxLayout(self._checks_widget)
        self._checks_layout.setContentsMargins(0, 0, 0, 0)
        self._checks_layout.setSpacing(8)
        self._checks_layout.addWidget(self.chk_register)
        self._checks_layout.addWidget(self.chk_link_stage)
        self._checks_layout.addStretch(1)

        self._focus_layout.addWidget(self._checks_widget)

        main_layout.addWidget(self._focus_widget, 1)

        # 最下段: status line（1 行だけ）
        self.lbl_status = QtWidgets.QLabel("", self)
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setMinimumHeight(18)
        main_layout.addWidget(self.lbl_status)

    def _update_backend_ui_visibility(self):
        connected = self.backend is not None
        self._conn_widget.setVisible(not connected)

    # --------------------------------------------------------
    # フィルタボタン / チェックボックスの表示制御
    # --------------------------------------------------------
    def _update_current_filter_visual(self, label: Optional[str]):
        """
        現在選択中のフィルターを強調表示（枠線色＋太さ）する。
        ※ フィルター状態は backend.position のみをソースとし、
           このメソッドは query_status() に基づくラベルを引数に取る。
        """
        for name, btn in self._wl_buttons.items():
            if name == label:
                btn.setStyleSheet(
                    "QPushButton { "
                    "border: 3px solid #b7f3b0; "
                    "font-weight: bold;  background-color: #b7f3b0;"
                    "}"
                )
            else:
                btn.setStyleSheet("")

    @Slot(bool)
    def _on_register_toggled(self, checked: bool):
        """
        Register モード ON:
            - 全ボタンをデフォルト表示に戻す（ハイライトなし）
        Register モード OFF:
            - backend.position（= self._current_status['position']）に対応する
              ボタンだけを再ハイライトする
        """
        if checked:
            # Register ON → いったん全てデフォルト表示
            self._update_current_filter_visual(None)
            return

        # Register OFF → backend.position から現在のラベルを復元
        try:
            state = getattr(self, "_current_status", {}) or {}
            pos = state.get("position")
            label: Optional[str] = None
            if isinstance(pos, int) and 1 <= pos <= self._num_slots:
                label = self._slot_names.get(pos)
            self._update_current_filter_visual(label)
        except Exception:
            # 何かあっても安全側（ハイライトなし）
            self._update_current_filter_visual(None)

    def _set_register_visible(self, visible: bool):
        """
        Backend 接続状況に応じて、チェックボックスをまとめて表示 / 非表示。
        """
        self.chk_register.setVisible(visible)
        self.chk_link_stage.setVisible(visible)

    def _set_wavelengths(self, wavelengths: List[str]):
        # 既存ボタンをすべて削除
        while self._buttons_row.count():
            item = self._buttons_row.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        self._wl_buttons.clear()
        self._wavelengths = list(wavelengths)
        self._update_current_filter_visual(None)

        if not wavelengths:
            return

        for wl in wavelengths:
            btn = QtWidgets.QPushButton(wl, self._focus_widget)
            btn.setCheckable(False)  # 押し込みは使わない
            btn.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
            )
            btn.clicked.connect(
                lambda checked, _wl=wl: self._on_filter_button_clicked(_wl)
            )
            self._buttons_row.addWidget(btn)
            self._wl_buttons[wl] = btn

        self._focus_controller.set_wavelengths(self._wavelengths)

    # --------------------------------------------------------
    # フィルタボタンクリック時の挙動
    # --------------------------------------------------------
    def _on_filter_button_clicked(self, label: str):
        """
        フィルタボタンが押されたときの動作:

        - Register OFF:
            1) main.py に「label への変更要求」を先に通知
            2) backend.set_position(slot) を呼ぶ
            3) UI ハイライトは backend からの sig_state_changed / query_status()
               に完全に依存する（ここでは変更しない）

        - Register ON:
            1) backend.set_position() は呼ばない
            2) 登録ダイアログを開き、FilterController.register_position_mm(...) のみ実行
               （position / UI ハイライトは backend.position のまま）
        """
        # Register モード中は position を変えない
        is_register = self.chk_register.isVisible() and self.chk_register.isChecked()

        if is_register:
            # backend.set_position は呼ばない
            dlg = FilterRegisterDialog(self._focus_controller, label, parent=self)
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return

            try:
                action, count = dlg.get_result()
            except Exception as e:
                self._set_error_text(f"Registration failed: {e}")
                return

            try:
                if action is None:
                    self._set_error_text("No registration action")
                    return
                self._focus_controller.register_position_mm(label, count_override=count)
            except Exception as e:
                self._set_error_text(f"Register error: {e}")

            # Register モード中は UI ハイライトを変えない（backend.position のみが真実）
            return

        # ---- Register OFF（通常モード） ----

        # 1) 先に main.py に「これから label に変える」と伝える
        self.sig_filter_change_requested.emit(label)

        # 2) その後で実際に backend.set_position() を呼んで物理フィルタを動かす
        if self.backend is not None and self._label_to_slot:
            slot = self._label_to_slot.get(label)
            if slot:
                try:
                    self.backend.set_position(int(slot))
                except Exception as e:
                    self._set_error_text(f"set_position error: {e}")
                    return


    # --------------------------------------------------------
    # Backend 接続 / Slot 名ダイアログ
    # --------------------------------------------------------
    def _on_connect_clicked(self):

        # 既に接続済み → disconnect処理
        if self.backend is not None:
            try:
                self.backend.emergency_shutdown()
            except Exception:
                pass
            try:
                self.backend.disconnect()
            except Exception:
                pass
            self.backend = None
            self._num_slots = 0
            self._slot_names = {}
            self._label_to_slot = {}
            self._slot_names_initialized = False
            self._wavelengths = []
            # Focus 側のリストもクリア
            self._focus_controller.set_wavelengths([])
            self._set_wavelengths([])
            self._set_register_visible(False)
            self._update_backend_ui_visibility()
            self._set_status_text("Filter backend disconnected.")
            return

        # 新規接続
        name = self.cmb_backend.currentText().strip()
        backend_cls = self._backend_classes.get(name)
        if backend_cls is None:
            self._set_error_text(f"backend not found: {name}")
            return

        backend = backend_cls(parent=self)
        backend.sig_connected.connect(self._on_backend_connected)
        backend.sig_error.connect(self._on_backend_error)
        backend.sig_state_changed.connect(self._on_backend_state_changed)

        # ここで接続準備
        self.backend = backend
        self._slot_names_initialized = False
        self._num_slots = 0
        self._slot_names = {}
        self._label_to_slot = {}
        self._wavelengths = []

        # 接続設定（show_setup_dialog）
        ok = False
        try:
            ok = backend.show_setup_dialog(parent=self)
        except Exception as e:
            self._set_error_text(f"setup dialog error: {e}")
            self.backend = None
            return

        if not ok:
            # ユーザーキャンセル
            self.backend = None
            return

        # connect 実行
        try:
            if not backend.connect():
                self._set_error_text("backend.connect() returned False")
                self.backend = None
                return
        except Exception as e:
            self._set_error_text(f"backend.connect error: {e}")
            self.backend = None
            return

        # 追加: 今回選んだ backend 名を保存
        try:
            name = self.cmb_backend.currentText().strip()
            self._last_backend_name = name
            self.settings.setValue(
                f"{SETTINGS_PREFIX_PANE}/last_backend_name", name
            )
            self.settings.sync()
        except Exception:
            pass

        # backend が sig_connected を emit しない場合に備えて自前で呼ぶ
        self._on_backend_connected(True)

    @Slot(bool)
    def _on_backend_connected(self, ok: bool):
        if not ok:
            self._set_error_text("backend connection failed")
            self.backend = None
            return

        self._set_status_text("Filter backend connected.")
        self._update_backend_ui_visibility()

        # 初期状態で Slot UI を構築
        try:
            status = self.backend.query_status()
            self._on_backend_state_changed(status)
        except Exception as e:
            self._set_error_text(f"query_status error: {e}")

        # カメラステージがすでに設定されている場合だけ、ここでメッセージを出す
        if self._focus_controller.camera is not None:
            self._on_focus_status("camera stage set for filter controller")

    @Slot(object)
    def _on_backend_state_changed(self, state: object):
        if not isinstance(state, dict):
            return
        self._current_status = state    # ここで常に最新状態を保持

        pos = state.get("position")
        num_slots = state.get("num_slots")
        busy = state.get("busy")
        slot_names = state.get("slot_names") or {}

        try:
            self._num_slots = int(num_slots) if isinstance(num_slots, int) else 0
        except Exception:
            self._num_slots = 0

        if self._num_slots > 0:
            self._ensure_slot_names(self._num_slots, slot_names)
            labels: List[str] = [
                self._slot_names.get(i, f"Filter {i}") for i in range(1, self._num_slots + 1)
            ]
            self._wavelengths = labels
            self._label_to_slot = {name: idx for idx, name in enumerate(labels, start=1)}

            self._focus_controller.set_wavelengths(labels)
            self._set_wavelengths(labels)
            self._set_register_visible(True)

            # position が有効なら対応するラベルをハイライト
            current_label: Optional[str] = None
            if isinstance(pos, int) and 1 <= pos <= self._num_slots:
                current_label = self._slot_names.get(pos)
            self._update_current_filter_visual(current_label)

            self._set_status_text(
                f"{self._num_slots} filters ready. "
                f"Current pos: {pos if isinstance(pos, int) else '-'}; "
                f"Busy: {bool(busy)}"
            )
        else:
            # スロットがない backend（将来的にあり得る）→ Filter は空
            self._num_slots = 0
            self._slot_names = {}
            self._label_to_slot = {}
            self._wavelengths = []
            self._focus_controller.set_wavelengths([])
            self._set_wavelengths([])
            self._set_register_visible(False)

            # 枠線強調をクリア
            self._update_current_filter_visual(None)

            self._set_status_text("Filter backend connected (no slots).")

    def _ensure_slot_names(self, num_slots: int, backend_slot_names: Dict[int, str]):
        """
        スロット数 num_slots に対して、スロット名を 1 回だけダイアログで確定し、
        QSettings に保存・復元する。
        """
        if self._slot_names_initialized and self._slot_names and len(self._slot_names) == num_slots:
            return

        backend_key = self._current_backend_settings_key()
        saved_json = self.settings.value(
            f"{SETTINGS_PREFIX_PANE}/{backend_key}/slot_names_json", ""
        )
        saved_names: Dict[int, str] = {}
        if saved_json:
            try:
                tmp = json.loads(saved_json)
                saved_names = {int(k): str(v) for k, v in tmp.items()}
            except Exception:
                saved_names = {}

        # 既存保存名 → backend 既定名 → デフォルト "Filter i"
        names: Dict[int, str] = {}
        for i in range(1, num_slots + 1):
            base = (
                saved_names.get(i)
                or backend_slot_names.get(i)
                or f"Filter {i}"
            )
            names[i] = base

        # ダイアログで編集
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Filter names")
        form = QtWidgets.QFormLayout(dlg)

        edits: Dict[int, QtWidgets.QLineEdit] = {}
        for i in range(1, num_slots + 1):
            label = QtWidgets.QLabel(f"Slot {i}:", dlg)
            edit = QtWidgets.QLineEdit(names[i], dlg)
            edits[i] = edit
            form.addRow(label, edit)

        btn_ok = QtWidgets.QPushButton("OK", dlg)
        btn_cancel = QtWidgets.QPushButton("Cancel", dlg)
        h = QtWidgets.QHBoxLayout()
        h.addStretch(1)
        h.addWidget(btn_ok)
        h.addWidget(btn_cancel)
        form.addRow(h)

        btn_ok.clicked.connect(dlg.accept)
        btn_cancel.clicked.connect(dlg.reject)

        if dlg.exec() == QtWidgets.QDialog.Accepted:
            # OK のときだけ上書き・保存
            for i in range(1, num_slots + 1):
                text = edits[i].text().strip()
                if not text:
                    text = f"Filter {i}"
                names[i] = text

            try:
                self.settings.setValue(
                    f"{SETTINGS_PREFIX_PANE}/{backend_key}/slot_names_json",
                    json.dumps(names),
                )
                self.settings.sync()
            except Exception:
                pass

        # Cancel のときも、元の names をそのまま使う
        self._slot_names = names
        self._slot_names_initialized = True

        # backend 側に名前更新を伝える（対応していれば）
        if self.backend is not None and hasattr(self.backend, "update_slot_name"):
            for i, n in names.items():
                try:
                    self.backend.update_slot_name(i, n)  # type: ignore[attr-defined]
                except Exception:
                    pass

    @Slot(str)
    def _on_backend_error(self, msg: str):
        self._set_error_text(msg)

    # --------------------------------------------------------
    # Focus / Stage 関連 API（Main / main.py 向け）
    # --------------------------------------------------------
    @property
    def wavelengths(self) -> List[str]:
        # 外部からは「現在のフィルタ名リスト」として見える
        return list(self._wavelengths)

    def set_wavelengths(self, wavelengths: List[str]):
        """
        将来的に LaserPane から波長リストを受け取る場合用。
        現状は、接続後に決めたスロット名で上書きする想定。
        """
        self._wavelengths = list(wavelengths)
        self._focus_controller.set_wavelengths(self._wavelengths)
        self._set_wavelengths(self._wavelengths)

    def set_camera_device(self, device):
        """
        StagePanel から渡される camera 軸デバイスを設定。
        """
        self._focus_controller.set_camera_device(device)
        if self.backend is not None:
            self._on_focus_status("camera stage set for filter controller")

    def is_stage_sync_enabled(self) -> bool:
        """
        main.py が「カメラステージと同期させるべきか」を判断するためのフラグ。
        """
        return self.chk_link_stage.isVisible() and self.chk_link_stage.isChecked()

    def apply_focus_correction(self, label: str):
        """
        main.py から呼ばれることを想定したフォーカス補正 API。
        通常の同期制御では MainWindow 側から apply_delta_mm が使われるため、
        ここは「絶対位置へ寄せたい特別な場合」だけに使用できるように残しておく。
        """
        if not self.is_stage_sync_enabled():
            return
        self._focus_controller.apply_position_mm(label)

    def on_shutdown(self):
        """
        設定保存と backend の emergency_shutdown / disconnect。
        """
        try:
            self._focus_controller._save_to_settings()
        except Exception:
            pass

        if self.backend is not None:
            try:
                self.backend.emergency_shutdown()
            except Exception:
                pass
            try:
                self.backend.disconnect()
            except Exception:
                pass
            self.backend = None


    # STEP撮影ダイアログ用
    def get_filter_choices(self) -> list[str]:
        """
        ダイアログ用。
        現在接続されているフィルター名一覧を返す。
        """
        return list(self._wavelengths)


    # --------------------------------------------------------
    # Status helper / Controller メッセージ集約
    # --------------------------------------------------------
    def _current_backend_settings_key(self) -> str:
        if self.backend is None:
            return "none"
        return self.backend.__class__.__name__

    def _on_focus_status(self, msg: str):
        self._set_status_text(msg)

    def _on_focus_error(self, msg: str):
        self._set_error_text(msg)

    def _set_status_text(self, msg: str):
        self.lbl_status.setText(f"Status: {msg}")
        self.sig_status.emit(msg)

    def _set_error_text(self, msg: str):
        self.lbl_status.setText(f"Status: [ERROR] {msg}")
        self.sig_error.emit(msg)


    # STEP撮影時のフィルター変更用 API　（main.py から呼ばれる）
    def set_filter_by_label(self, label: str):
        if self.backend is None:
            raise RuntimeError("Filter backend is not connected")

        slot = self._label_to_slot.get(label)
        if slot is None:
            raise RuntimeError(f"Unknown filter label: {label}")

        try:
            self.backend.set_position(int(slot))
        except Exception as e:
            raise RuntimeError(f"set_position error: {e}")