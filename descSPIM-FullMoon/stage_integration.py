# stage_integration.py
# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import json
import importlib
import pkgutil
import pathlib

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QObject, Signal, Slot, QSettings

from stage_backends.stage_backend_base import IStageBackend
from timing_logger import TimingLogger

from enum import IntEnum
from stage_backends.stage_backend_base import IStageBackend, StepDirection
from timing_logger import TimingLogger


# stage_backends ディレクトリ
STAGE_BACKEND_MODULE_DIR = pathlib.Path(__file__).parent / "stage_backends"


def scan_stage_backends():
    """
    stage_backends/ 以下を走査して、get_backend_class を持つモジュールを列挙する。
    戻り値: { "Thorlabs_KDC101": {"module": "...", "class": <cls>} }
    ファイル名がそのままコンボボックスの選択肢になる。
    """
    backends = {}
    pkg_name = "stage_backends"

    for mi in pkgutil.iter_modules([str(STAGE_BACKEND_MODULE_DIR)]):
        mod_name = mi.name
        full_mod = f"{pkg_name}.{mod_name}"
        try:
            mod = importlib.import_module(full_mod)
            if hasattr(mod, "get_backend_class"):
                cls = mod.get_backend_class()
                backends[mod_name] = {
                    "module": full_mod,
                    "class": cls,
                }
        except Exception as e:
            print(f"[scan_stage_backends] failed importing {full_mod}: {e}")

    return backends


# ------------------------------
# Profile / Preset モデル
# ------------------------------
@dataclass
class StageProfile:
    mode: str = "Move"        # Acq 用: "Move" / "Step"
    v_move: float = 1.0       # Move 用 velocity (mm/s)
    acc_move: float = 1.5     # Move 用 accel (mm/s^2)
    v_step: float = 1.0       # Step 用 velocity (mm/s)
    acc_step: float = 1.5     # Step 用 accel (mm/s^2)
    step: float = 0.010       # Step size (mm)
    dir: str = "F"            # "F" or "R"


@dataclass
class StagePreset:
    name: str
    profile: StageProfile


@dataclass
class AxisState:
    axis_name: str
    backend: Optional[IStageBackend] = None

    # プロファイルは default_factory で生成（mutable default 回避）
    acq_profile: StageProfile = field(default_factory=StageProfile)
    ctl_profile: StageProfile = field(default_factory=StageProfile)

    # リスト類も default_factory=list で生成
    acq_presets: List[StagePreset] = field(default_factory=list)
    ctl_presets: List[StagePreset] = field(default_factory=list)
    acq_recent: List[StageProfile] = field(default_factory=list)
    ctl_recent: List[StageProfile] = field(default_factory=list)



def profile_to_dict(p: StageProfile) -> Dict:
    return {
        "mode": p.mode,
        "v_move": p.v_move,
        "acc_move": p.acc_move,
        "v_step": p.v_step,
        "acc_step": p.acc_step,
        "step": p.step,
        "dir": p.dir,
    }

def profile_from_dict(d: Dict, default: StageProfile) -> StageProfile:
    if not isinstance(d, dict):
        return default

    mode = d.get("mode", default.mode)
    if mode not in ("Move", "Step"):
        mode = default.mode

    dir_val = d.get("dir", default.dir)
    if dir_val not in ("F", "R"):
        dir_val = default.dir

    # 旧形式(v, acc, acc_step)も吸収
    def _get_float(key, fallback):
        try:
            return float(d.get(key, fallback))
        except Exception:
            return fallback

    # 旧: "v" / "acc" / "acc_step" があれば使う
    v_old = _get_float("v", default.v_move)
    acc_old = _get_float("acc", default.acc_move)
    acc_step_old = _get_float("acc_step", acc_old)

    v_move = _get_float("v_move", v_old)
    acc_move = _get_float("acc_move", acc_old)
    v_step = _get_float("v_step", v_old)
    acc_step = _get_float("acc_step", acc_step_old)
    step = _get_float("step", default.step)

    return StageProfile(
        mode=mode,
        v_move=v_move,
        acc_move=acc_move,
        v_step=v_step,
        acc_step=acc_step,
        step=step,
        dir=dir_val,
    )


def preset_to_dict(p: StagePreset) -> Dict:
    return {"name": p.name, "profile": profile_to_dict(p.profile)}


def preset_from_dict(d: Dict, default_name: str) -> StagePreset:
    if not isinstance(d, dict):
        return StagePreset(default_name, StageProfile())
    name = d.get("name", default_name)
    prof = profile_from_dict(d.get("profile", {}), StageProfile())
    return StagePreset(name, prof)


def axis_state_to_dict(axis: AxisState) -> Dict:
    return {
        "acq_profile": profile_to_dict(axis.acq_profile),
        "ctl_profile": profile_to_dict(axis.ctl_profile),
        "acq_presets": [preset_to_dict(p) for p in axis.acq_presets],
        "ctl_presets": [preset_to_dict(p) for p in axis.ctl_presets],
        "acq_recent": [profile_to_dict(p) for p in axis.acq_recent],
        "ctl_recent": [profile_to_dict(p) for p in axis.ctl_recent],
    }


def axis_state_from_dict(axis_name: str, d: Dict, default: AxisState) -> AxisState:
    if not isinstance(d, dict):
        return default
    acq_prof = profile_from_dict(d.get("acq_profile", {}), default.acq_profile)
    ctl_prof = profile_from_dict(d.get("ctl_profile", {}), default.ctl_profile)

    acq_presets = []
    for i, pd in enumerate(d.get("acq_presets", [])):
        acq_presets.append(preset_from_dict(pd, f"Acq{i+1}"))

    ctl_presets = []
    for i, pd in enumerate(d.get("ctl_presets", [])):
        ctl_presets.append(preset_from_dict(pd, f"Ctl{i+1}"))

    acq_recent = [profile_from_dict(r, default.acq_profile) for r in d.get("acq_recent", [])][:5]
    ctl_recent = [profile_from_dict(r, default.ctl_profile) for r in d.get("ctl_recent", [])][:5]

    axis = AxisState(
        axis_name=axis_name,
        backend=default.backend,
        acq_profile=acq_prof,
        ctl_profile=ctl_prof,
        acq_presets=acq_presets,
        ctl_presets=ctl_presets,
        acq_recent=acq_recent,
        ctl_recent=ctl_recent,
    )
    return axis


# ------------------------------
# Bridge signals（カメラ↔ステージ同期）
# ------------------------------
class StageLinkMode(IntEnum):
    STAGE_OFF       = 0
    MOVE_CONTINUOUS = 1
    STEP            = 2
    # 将来: MULTI_POSITION = 2 などを追加していく
    # TODO: OFF のときは Auto-return を強制 OFF + 無効化 にするようにコードを編集すること

class StageStopMode(IntEnum):
    STOP_ONLY = 0         # 止めるだけ
    STOP_AND_RETURN = 1   # Home/Return 付き
    #RETURN_ONLY = 2

#class StepDirection(IntEnum):
#    FORWARD = 0
#    REVERSE = 1

class StageBridge(QObject):
    """
    CameraPane と StagePanel の間の橋渡しクラス。

    - sig_stage_start:
        Move 連動開始（連続走査）

    - sig_stage_stop(direction, mode):
        連動停止指令 + 停止モード
        direction: str  ("F" / "R" / "" など)
        mode     : int (StageStopMode の value)

    - sig_step_once(reverse):
        Step 連動用の 1 ステップ要求
        reverse: bool

    - sig_recording_state:
        カメラ録画状態の通知（UI 色付け用）
    """

    sig_stage_start = Signal()            # 録画連動の開始（Move）
    sig_stage_stop = Signal(int, int)     
    sig_step_done = Signal()             # 使う場合のために残しておく
    sig_recording_state = Signal(bool)
    sig_step_once = Signal()
    sig_step_done = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # CameraPane 側の StageLinkMode
        self._link_mode: StageLinkMode = StageLinkMode.STAGE_OFF
        # 停止時のデフォルトモード
        self._stop_mode: StageStopMode = StageStopMode.STOP_ONLY

    @Slot(int, int)
    def set_link_config(self, link_mode: int, stop_mode: int):
        """
        CameraPane 側から「ステージ連動モード／停止モード」を設定する。

        link_mode : CameraPane 独自の StageLinkMode（0=Move, 1=Step など）
        stop_mode : StageStopMode の value
        """
        print(f"[StageBridge] set_link_config: mode={link_mode}, stop_mode={stop_mode}")
        self._link_mode = StageLinkMode(int(link_mode))
        self._stop_mode = StageStopMode(int(stop_mode))

        try:
            self.stop_mode = StageStopMode(int(stop_mode))
        except ValueError:
            self.stop_mode = StageStopMode.STOP_ONLY

    @Slot()
    def on_stage_stop(self):
        try:
            print(f"[StageBridge] on_stage_stop: link_mode={self._link_mode} stop_mode={self._stop_mode}")
            self.sig_stage_stop.emit(int(self._link_mode), int(self._stop_mode))
        except Exception as e:
            print(f"[StageBridge] on_stage_stop: failed: {e}")


# ------------------------------
# StageSettingsDialog
# ------------------------------
class StageSettingsDialog(QtWidgets.QDialog):
    """
    Sample / Camera × Acq / Ctl の StageProfile と
    プリセット / Recent を編集するダイアログ。
    backend には触らず、AxisState のみ編集する。
    """

    def __init__(self, sample_state: AxisState, camera_state: AxisState, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Stage Settings")
        self.setModal(True)

        # コピーを編集対象にする
        # （受け取る側で OK 時に AxisState を丸ごと差し替える）
        self.sample_state = axis_state_from_dict(
            "Sample", axis_state_to_dict(sample_state), sample_state
        )
        self.camera_state = axis_state_from_dict(
            "Camera", axis_state_to_dict(camera_state), camera_state
        )

        self._editors: Dict[Tuple[str, str], Dict[str, QtWidgets.QWidget]] = {}

        layout = QtWidgets.QGridLayout(self)

        # 上段: Acquisition (Sample / Camera)
        self._create_profile_block(layout, row=0, col=0, axis="Sample", kind="Acq")
        self._create_profile_block(layout, row=0, col=1, axis="Camera", kind="Acq")

        # 下段: Control (Sample / Camera)
        self._create_profile_block(layout, row=1, col=0, axis="Sample", kind="Ctl")
        self._create_profile_block(layout, row=1, col=1, axis="Camera", kind="Ctl")

        # ボタン
        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self,
        )
        btn_box.accepted.connect(self._on_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box, 2, 0, 1, 2)

        # 初期値を UI に反映
        self._load_state_into_editors()

    # ---- UI 構築 helpers ----
    def _create_profile_block(self, parent_layout: QtWidgets.QGridLayout,
                              row: int, col: int, axis: str, kind: str):
        """
        axis: "Sample" / "Camera"
        kind: "Acq" / "Ctl"
        """
        title = f"{axis} { 'Acquisition' if kind == 'Acq' else 'Control' }"
        gb = QtWidgets.QGroupBox(title, self)
        grid = QtWidgets.QGridLayout(gb)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        # Mode (Acq だけ表示、Ctl は非表示)
        lbl_mode = QtWidgets.QLabel("Mode for Start (test):", gb)
        cmb_mode = QtWidgets.QComboBox(gb)
        cmb_mode.addItems(["Move", "Step"])

        r = 0
        if kind == "Acq":
            grid.addWidget(lbl_mode, r, 0)
            grid.addWidget(cmb_mode, r, 1)
            r += 1
        else:
            lbl_mode.hide()
            cmb_mode.hide()

        # ---- Move 行 ----
        lbl_move = QtWidgets.QLabel("Move:", gb)
        lbl_move.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_move, r, 0, 1, 2)
        r += 1

        lbl_v_move = QtWidgets.QLabel("Velocity (mm/s):", gb)
        spin_v_move = QtWidgets.QDoubleSpinBox(gb)
        spin_v_move.setRange(0.0, 100.0)
        spin_v_move.setDecimals(5)

        lbl_acc_move = QtWidgets.QLabel("Acceleration (mm/s²):", gb)
        spin_acc_move = QtWidgets.QDoubleSpinBox(gb)
        spin_acc_move.setRange(0.0, 1000.0)
        spin_acc_move.setDecimals(3)

        grid.addWidget(lbl_v_move, r, 0)
        grid.addWidget(spin_v_move, r, 1)
        r += 1
        grid.addWidget(lbl_acc_move, r, 0)
        grid.addWidget(spin_acc_move, r, 1)
        r += 1

        # ---- Step 行 ----
        lbl_step_header = QtWidgets.QLabel("Step:", gb)
        lbl_step_header.setStyleSheet("font-weight: bold;")
        grid.addWidget(lbl_step_header, r, 0, 1, 2)
        r += 1

        lbl_v_step = QtWidgets.QLabel("Velocity (mm/s):", gb)
        spin_v_step = QtWidgets.QDoubleSpinBox(gb)
        spin_v_step.setRange(0.0, 100.0)
        spin_v_step.setDecimals(5)

        lbl_acc_step = QtWidgets.QLabel("Acceleration (mm/s²):", gb)
        spin_acc_step = QtWidgets.QDoubleSpinBox(gb)
        spin_acc_step.setRange(0.0, 1000.0)
        spin_acc_step.setDecimals(3)

        lbl_step = QtWidgets.QLabel("Step size (mm):", gb)
        spin_step = QtWidgets.QDoubleSpinBox(gb)
        spin_step.setRange(0.0, 10.0)
        spin_step.setDecimals(6)

        grid.addWidget(lbl_v_step, r, 0)
        grid.addWidget(spin_v_step, r, 1)
        r += 1
        grid.addWidget(lbl_acc_step, r, 0)
        grid.addWidget(spin_acc_step, r, 1)
        r += 1
        grid.addWidget(lbl_step, r, 0)
        grid.addWidget(spin_step, r, 1)
        r += 1

        # Direction (共通)
        lbl_dir = QtWidgets.QLabel("Direction:", gb)
        cmb_dir = QtWidgets.QComboBox(gb)
        cmb_dir.addItems(["Forward", "Reverse"])

        # ★ ここを修正：Acq のときだけ表示、Ctl のときは非表示＋固定 "F"
        if kind == "Acq":
            grid.addWidget(lbl_dir, r, 0)
            grid.addWidget(cmb_dir, r, 1)
            r += 1
        else:
            # Ctl 側は UI を出さない（内部的には Forward 固定として扱う）
            lbl_dir.hide()
            cmb_dir.hide()


        # Preset
        lbl_preset = QtWidgets.QLabel("Preset:", gb)
        edit_name = QtWidgets.QLineEdit(gb)
        edit_name.setPlaceholderText("Preset name")
        cmb_load = QtWidgets.QComboBox(gb)
        btn_save_new = QtWidgets.QPushButton("Save as new", gb)
        btn_manage = QtWidgets.QPushButton("Manage…", gb)

        grid.addWidget(lbl_preset, r, 0)
        grid.addWidget(edit_name, r, 1)
        r += 1
        grid.addWidget(cmb_load, r, 0)
        grid.addWidget(btn_save_new, r, 1)
        r += 1
        grid.addWidget(btn_manage, r, 0, 1, 2)
        r += 1

        # Recent
        lbl_recent = QtWidgets.QLabel("Recent (last 5):", gb)
        list_recent = QtWidgets.QListWidget(gb)
        list_recent.setMaximumHeight(80)
        grid.addWidget(lbl_recent, r, 0, 1, 2)
        r += 1
        grid.addWidget(list_recent, r, 0, 1, 2)

        parent_layout.addWidget(gb, row, col)

        key = (axis, kind)
        self._editors[key] = {
            "mode": cmb_mode,
            "v_move": spin_v_move,
            "acc_move": spin_acc_move,
            "v_step": spin_v_step,
            "acc_step": spin_acc_step,
            "step": spin_step,
            "dir": cmb_dir,
            "name": edit_name,
            "load": cmb_load,
            "save_new": btn_save_new,
            "manage": btn_manage,
            "recent": list_recent,
        }

        cmb_load.activated.connect(
            lambda idx, a=axis, k=kind: self._on_load_preset(a, k, idx)
        )
        btn_save_new.clicked.connect(
            lambda _=False, a=axis, k=kind: self._on_save_as_new(a, k)
        )
        btn_manage.clicked.connect(
            lambda _=False, a=axis, k=kind: self._on_manage_presets(a, k)
        )
        list_recent.itemClicked.connect(
            lambda item, a=axis, k=kind: self._on_recent_clicked(a, k, item)
        )


    # ---- state <-> UI ----
    def _load_state_into_editors(self):
        for axis, kind in [("Sample", "Acq"),
                           ("Camera", "Acq"),
                           ("Sample", "Ctl"),
                           ("Camera", "Ctl")]:
            ed = self._editors[(axis, kind)]
            state = self.sample_state if axis == "Sample" else self.camera_state
            prof = state.acq_profile if kind == "Acq" else state.ctl_profile
            presets = state.acq_presets if kind == "Acq" else state.ctl_presets
            recents = state.acq_recent if kind == "Acq" else state.ctl_recent

            ed["mode"].setCurrentIndex(0 if prof.mode == "Move" else 1)
            ed["v_move"].setValue(prof.v_move)
            ed["acc_move"].setValue(prof.acc_move)
            ed["v_step"].setValue(prof.v_step)
            ed["acc_step"].setValue(prof.acc_step)
            ed["step"].setValue(prof.step)

            # ★ Acq のときだけ dir を UI に反映（Ctl 側はコンボ非表示のため）
            if kind == "Acq":
                ed["dir"].setCurrentIndex(0 if prof.dir == "F" else 1)


            cmb = ed["load"]
            cmb.clear()
            for p in presets:
                cmb.addItem(p.name)

            lst = ed["recent"]
            lst.clear()
            for r in recents:
                lst.addItem(self._format_recent_text(r))


    def _save_editors_into_state(self):
        for axis, kind in [("Sample", "Acq"),
                           ("Camera", "Acq"),
                           ("Sample", "Ctl"),
                           ("Camera", "Ctl")]:
            ed = self._editors[(axis, kind)]
            state = self.sample_state if axis == "Sample" else self.camera_state

            prof = StageProfile()
            prof.mode = "Move" if ed["mode"].currentIndex() == 0 else "Step"
            prof.v_move = ed["v_move"].value()
            prof.acc_move = ed["acc_move"].value()
            prof.v_step = ed["v_step"].value()
            prof.acc_step = ed["acc_step"].value()
            prof.step = ed["step"].value()

            if kind == "Acq":
                # Acq は UI のコンボから取得
                prof.dir = "F" if ed["dir"].currentIndex() == 0 else "R"
                state.acq_profile = prof
                self._append_recent(state.acq_recent, prof)
            else:
                # ★ Ctl 側は常に Forward 固定（UI も出していない）
                prof.dir = "F"
                state.ctl_profile = prof
                self._append_recent(state.ctl_recent, prof)




    # ---- preset / recent handlers ----
    def _get_state_for(self, axis: str) -> AxisState:
        return self.sample_state if axis == "Sample" else self.camera_state

    def _append_recent(self, recent_list: List[StageProfile], prof: StageProfile):
        # 同一連続はスキップ
        if recent_list and profile_to_dict(recent_list[0]) == profile_to_dict(prof):
            return
        recent_list.insert(0, prof)
        if len(recent_list) > 5:
            del recent_list[5:]

    def _format_recent_text(self, p: StageProfile) -> str:
        return (
            f"Move v={p.v_move:.3f} acc={p.acc_move:.1f}; "
            f"Step s={p.step:.4f} v={p.v_step:.3f} acc={p.acc_step:.1f} {p.dir}"
        )


    def _on_load_preset(self, axis: str, kind: str, idx: int):
        state = self._get_state_for(axis)
        presets = state.acq_presets if kind == "Acq" else state.ctl_presets
        if not (0 <= idx < len(presets)):
            return
        p = presets[idx].profile
        ed = self._editors[(axis, kind)]
        ed["mode"].setCurrentIndex(0 if p.mode == "Move" else 1)
        ed["v_move"].setValue(p.v_move)
        ed["acc_move"].setValue(p.acc_move)
        ed["v_step"].setValue(p.v_step)
        ed["acc_step"].setValue(p.acc_step)
        ed["step"].setValue(p.step)

        # ★ Acq のときだけ dir を UI に反映
        if kind == "Acq":
            ed["dir"].setCurrentIndex(0 if p.dir == "F" else 1)

        ed["name"].setText(presets[idx].name)


    def _on_save_as_new(self, axis: str, kind: str):
        state = self._get_state_for(axis)
        ed = self._editors[(axis, kind)]
        name = ed["name"].text().strip()
        if not name:
            base = "Acq" if kind == "Acq" else "Ctl"
            name = f"{base}{len(state.acq_presets if kind == 'Acq' else state.ctl_presets) + 1}"

        prof = StageProfile()
        prof.mode = "Move" if ed["mode"].currentIndex() == 0 else "Step"
        prof.v_move = ed["v_move"].value()
        prof.acc_move = ed["acc_move"].value()
        prof.v_step = ed["v_step"].value()
        prof.acc_step = ed["acc_step"].value()
        prof.step = ed["step"].value()

        if kind == "Acq":
            prof.dir = "F" if ed["dir"].currentIndex() == 0 else "R"
        else:
            # ★ Ctl 側は Forward 固定
            prof.dir = "F"


        preset = StagePreset(name=name, profile=prof)
        if kind == "Acq":
            state.acq_presets.append(preset)
        else:
            state.ctl_presets.append(preset)

        cmb = ed["load"]
        cmb.clear()
        targets = state.acq_presets if kind == "Acq" else state.ctl_presets
        for p in targets:
            cmb.addItem(p.name)

        rec_list = state.acq_recent if kind == "Acq" else state.ctl_recent
        self._append_recent(rec_list, prof)
        lst = ed["recent"]
        lst.clear()
        for r in rec_list:
            lst.addItem(self._format_recent_text(r))



    def _on_manage_presets(self, axis: str, kind: str):
        """
        簡易 Manage: Delete / Up / Down。
        """
        state = self._get_state_for(axis)
        presets = state.acq_presets if kind == "Acq" else state.ctl_presets
        if not presets:
            QtWidgets.QMessageBox.information(self, "Manage presets", "No presets.")
            return

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"Manage presets ({axis} {kind})")
        v = QtWidgets.QVBoxLayout(dlg)
        lst = QtWidgets.QListWidget(dlg)
        for p in presets:
            lst.addItem(p.name)
        v.addWidget(lst)

        h = QtWidgets.QHBoxLayout()
        btn_up = QtWidgets.QPushButton("Up", dlg)
        btn_down = QtWidgets.QPushButton("Down", dlg)
        btn_del = QtWidgets.QPushButton("Delete", dlg)
        h.addWidget(btn_up)
        h.addWidget(btn_down)
        h.addWidget(btn_del)
        v.addLayout(h)

        btn_ok = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dlg,
        )
        v.addWidget(btn_ok)

        def move_selected(delta: int):
            row = lst.currentRow()
            if row < 0:
                return
            new_row = row + delta
            if not (0 <= new_row < lst.count()):
                return
            presets[row], presets[new_row] = presets[new_row], presets[row]
            item = lst.takeItem(row)
            lst.insertItem(new_row, item)
            lst.setCurrentRow(new_row)

        def delete_selected():
            row = lst.currentRow()
            if row < 0:
                return
            lst.takeItem(row)
            del presets[row]

        btn_up.clicked.connect(lambda: move_selected(-1))
        btn_down.clicked.connect(lambda: move_selected(+1))
        btn_del.clicked.connect(delete_selected)
        btn_ok.accepted.connect(dlg.accept)
        btn_ok.rejected.connect(dlg.reject)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        # 元の presets は直接編集済み。
        # 呼び出し元の combo だけ更新しておく。
        ed = self._editors[(axis, kind)]
        cmb = ed["load"]
        cmb.clear()
        for p in presets:
            cmb.addItem(p.name)

    def _on_recent_clicked(self, axis: str, kind: str, item: QtWidgets.QListWidgetItem):
        state = self._get_state_for(axis)
        recents = state.acq_recent if kind == "Acq" else state.ctl_recent
        idx = self._editors[(axis, kind)]["recent"].row(item)
        if not (0 <= idx < len(recents)):
            return
        p = recents[idx]
        ed = self._editors[(axis, kind)]
        ed["mode"].setCurrentIndex(0 if p.mode == "Move" else 1)
        ed["v_move"].setValue(p.v_move)
        ed["acc_move"].setValue(p.acc_move)
        ed["v_step"].setValue(p.v_step)
        ed["acc_step"].setValue(p.acc_step)
        ed["step"].setValue(p.step)

        # ★ Acq のときのみ dir を UI に反映
        if kind == "Acq":
            ed["dir"].setCurrentIndex(0 if p.dir == "F" else 1)




    # ---- accept ----
    def _on_accept(self):
        self._save_editors_into_state()
        self.accept()

    def get_states(self) -> Tuple[AxisState, AxisState]:
        return self.sample_state, self.camera_state


# ------------------------------
# StagePanel（UI + backend プラグイン×2軸）
# ------------------------------
class StagePanel(QtWidgets.QGroupBox):
    # MainWindow 向け：ステージ接続状態を中継（どちらか一方でも接続されていれば True）
    sig_connected = Signal(bool)

    def __init__(self, bridge: StageBridge, timing_logger: TimingLogger, parent=None):
        super().__init__("Stage", parent)
        self.bridge = bridge
        self.timing_logger = timing_logger
        self.settings = QSettings("LabSuite", "StageControl")

        # backend プラグイン情報
        self.backends = scan_stage_backends()

        # Sample / Camera 用 backend インスタンス（1 軸ずつ）
        self.backend_sample: IStageBackend | None = None
        self.backend_camera: IStageBackend | None = None
        self._current_backend_key_sample: str | None = None
        self._current_backend_key_camera: str | None = None

        # Axis state
        self.sample_state = AxisState(
            axis_name="Sample",
            acq_profile=StageProfile(
                mode="Move",
                v_move=0.0400,
                acc_move=1.5,
                v_step=0.0400,
                acc_step=1.5,
                step=0.010,
                dir="F",
            ),
            ctl_profile=StageProfile(
                mode="Move",
                v_move=1.0,
                acc_move=1.5,
                v_step=1.0,
                acc_step=1.5,
                step=0.010,
                dir="F",
            ),
        )
        self.camera_state = AxisState(
            axis_name="Camera",
            acq_profile=StageProfile(
                mode="Move",
                v_move=0.01368,
                acc_move=1.5,
                v_step=0.01368,
                acc_step=1.5,
                step=0.010,
                dir="F",
            ),
            ctl_profile=StageProfile(
                mode="Move",
                v_move=1.0,
                acc_move=1.5,
                v_step=1.0,
                acc_step=1.5,
                step=0.020,
                dir="F",
            ),
        )

        # 接続状態
        self._connected_sample = False
        self._connected_camera = False
        self._connected = False  # 全体（どちらか一方でも True なら True）

        # Start(test) / Start(Forward/Reverse) 状態
        self._test_running = False
        self._fwd_running = False
        self._rev_running = False
        self._prev_acq_dirs: Optional[Tuple[str, str]] = None  # (sample_dir, camera_dir)

        # Step モード用: Start(test) 連続ステップ用タイマー
        #self._step_test_timer = QtCore.QTimer(self)
        #self._step_test_timer.setInterval(100)  # 必要なら適宜 ms に変更
        #self._step_test_timer.timeout.connect(self._on_step_test_tick)
        # Step 連続テストの方向 ("none" / "test" / "reverse")
        #self._step_owner: str = "none"

        # 個別 Jog 状態
        self._sample_jog_running = False
        self._camera_jog_running = False

        # Start 位置（mm）
        self._start_sample_mm: float | None = None
        self._start_camera_mm: float | None = None
        self._has_startpos = False

        # 録画状態
        self._recording_active = False

        # Start系ボタン共通の「赤」スタイル
        self._style_running_red = (
            "QPushButton { border: 1px solid red; padding: 4px 8px; "
            "background-color: red; color: white; font-family: Arial black; font-weight: 900;}"
        )

        # ---- UI 構築 ----
        top = QtWidgets.QGridLayout(self)

        # --- Stage backend selector: Sample / Camera それぞれ ---
        self.cmb_backend_sample = QtWidgets.QComboBox()
        self.cmb_backend_camera = QtWidgets.QComboBox()
        self.btn_connect_sample = QtWidgets.QPushButton("Connect")
        self.btn_connect_camera = QtWidgets.QPushButton("Connect")

        for key in sorted(self.backends.keys()):
            self.cmb_backend_sample.addItem(key, key)
            self.cmb_backend_camera.addItem(key, key)

        # 0 行目: Sample backend + Connect
        self.lbl_backend_sample = QtWidgets.QLabel("Sample backend:")
        top.addWidget(self.lbl_backend_sample,        0, 0)
        top.addWidget(self.cmb_backend_sample,        0, 1, 1, 2)
        top.addWidget(self.btn_connect_sample,        0, 3, 1, 2)

        # 1 行目: Camera backend + Connect
        self.lbl_backend_camera = QtWidgets.QLabel("Camera backend:")
        top.addWidget(self.lbl_backend_camera,        1, 0)
        top.addWidget(self.cmb_backend_camera,        1, 1, 1, 2)
        top.addWidget(self.btn_connect_camera,        1, 3, 1, 2)

        row = 2

        # === body ===
        self.body = QtWidgets.QWidget(self)
        body_layout = QtWidgets.QGridLayout(self.body)

        # 上段: Start / Settings
        self.btn_startstop = QtWidgets.QPushButton("Start (test)")
        #self.btn_start_fwd = QtWidgets.QPushButton("Start (Forward)")
        #self.btn_start_rev = QtWidgets.QPushButton("Start (Reverse)")
        self.btn_start_rev = QtWidgets.QPushButton("Start (Opposite)")
        self.btn_settings = QtWidgets.QPushButton("Settings...")

        h_top = QtWidgets.QHBoxLayout()
        h_top.addWidget(self.btn_startstop)
        #h_top.addWidget(self.btn_start_fwd)
        h_top.addWidget(self.btn_start_rev)
        h_top.addWidget(self.btn_settings)

        r = 0
        body_layout.addLayout(h_top, r, 0, 1, 4)
        r += 1

        # Register / Go to
        self.btn_reg  = QtWidgets.QPushButton("Register Start Position")
        self.btn_goto = QtWidgets.QPushButton("Go to Start Position")
        self.btn_goto.setEnabled(False)

        h_reggoto = QtWidgets.QHBoxLayout()
        h_reggoto.addWidget(self.btn_reg)
        h_reggoto.addWidget(self.btn_goto)
        body_layout.addLayout(h_reggoto, r, 0, 1, 4)
        r += 1

        # === Sample / Camera 用の「カード」(QGroupBox) ===

        # --- Sample ---
        self.gb_sample = QtWidgets.QGroupBox("Sample stage (-)")
        self.gb_sample.setAlignment(QtCore.Qt.AlignCenter)
        grid_s = QtWidgets.QGridLayout(self.gb_sample)
        grid_s.setContentsMargins(6, 6, 6, 6)
        grid_s.setHorizontalSpacing(6)
        grid_s.setVerticalSpacing(4)

        self.btn_sample_disconnect = QtWidgets.QPushButton("Disconnect")
        self.btn_sample_home       = QtWidgets.QPushButton("Home")

        grid_s.addWidget(self.btn_sample_disconnect, 0, 0)
        grid_s.addWidget(self.btn_sample_home,       0, 1)

        self.lbl_sample_acq = QtWidgets.QLabel("Acq: -")
        self.lbl_sample_ctl = QtWidgets.QLabel("Ctl: -")
        grid_s.addWidget(self.lbl_sample_acq, 1, 0, 1, 2)
        grid_s.addWidget(self.lbl_sample_ctl, 2, 0, 1, 2)

        # 手動操作ボタン（↑↑ ↑ ↓ ↓↓）
        # 手動操作ボタン（↑↑ ↑ ↓ ↓↓）
        self.btn_sample_up2 = QtWidgets.QPushButton("↑↑")
        self.btn_sample_up1 = QtWidgets.QPushButton("↑")
        self.btn_sample_down1 = QtWidgets.QPushButton("↓")
        self.btn_sample_down2 = QtWidgets.QPushButton("↓↓")

        # 矢印ボタンを 1 行にまとめる
        h_arrows_sample = QtWidgets.QHBoxLayout()
        for btn in (
            self.btn_sample_up2,
            self.btn_sample_up1,
            self.btn_sample_down1,
            self.btn_sample_down2,
        ):
            btn.setFixedWidth(40)  # 横幅を揃える（必要なら調整）
            h_arrows_sample.addWidget(btn)
        # 必要なら右側に少し余白
        h_arrows_sample.addStretch(1)

        # 2 列ぶんに配置（列 0–1 全体を使う）
        grid_s.addLayout(h_arrows_sample, 3, 0, 1, 2)

        # Ctl プリセットボタン 3 個
        self.btn_sample_preset1 = QtWidgets.QPushButton("P1")
        self.btn_sample_preset2 = QtWidgets.QPushButton("P2")
        self.btn_sample_preset3 = QtWidgets.QPushButton("P3")
        self.btn_sample_preset4 = QtWidgets.QPushButton("P4")

        h_preset_sample = QtWidgets.QHBoxLayout()
        for btn in (
            self.btn_sample_preset1,
            self.btn_sample_preset2,
            self.btn_sample_preset3,
            self.btn_sample_preset4,
        ):
            btn.setFixedWidth(40)  # 必要なら調整
            h_preset_sample.addWidget(btn)
        h_preset_sample.addStretch(1)

        # 2 列ぶんを使って 1 行に配置
        grid_s.addLayout(h_preset_sample, 5, 0, 1, 2)


        # --- Camera ---
        self.gb_camera = QtWidgets.QGroupBox("Camera stage (-)")
        self.gb_camera.setAlignment(QtCore.Qt.AlignCenter)
        grid_c = QtWidgets.QGridLayout(self.gb_camera)
        grid_c.setContentsMargins(6, 6, 6, 6)
        grid_c.setHorizontalSpacing(6)
        grid_c.setVerticalSpacing(4)

        self.btn_camera_disconnect = QtWidgets.QPushButton("Disconnect")
        self.btn_camera_home       = QtWidgets.QPushButton("Home")

        grid_c.addWidget(self.btn_camera_disconnect, 0, 0)
        grid_c.addWidget(self.btn_camera_home,       0, 1)

        self.lbl_camera_acq = QtWidgets.QLabel("Acq: -")
        self.lbl_camera_ctl = QtWidgets.QLabel("Ctl: -")
        grid_c.addWidget(self.lbl_camera_acq, 1, 0, 1, 2)
        grid_c.addWidget(self.lbl_camera_ctl, 2, 0, 1, 2)

        self.btn_camera_up2 = QtWidgets.QPushButton("↑↑")
        self.btn_camera_up1 = QtWidgets.QPushButton("↑")
        self.btn_camera_down1 = QtWidgets.QPushButton("↓")
        self.btn_camera_down2 = QtWidgets.QPushButton("↓↓")

        # 矢印ボタンを 1 行にまとめる
        h_arrows_camera = QtWidgets.QHBoxLayout()
        for btn in (
            self.btn_camera_up2,
            self.btn_camera_up1,
            self.btn_camera_down1,
            self.btn_camera_down2,
        ):
            btn.setFixedWidth(40)  # Sample と同じ値に
            h_arrows_camera.addWidget(btn)
        h_arrows_camera.addStretch(1)

        # 2 列ぶんに配置
        grid_c.addLayout(h_arrows_camera, 3, 0, 1, 2)


        self.btn_camera_preset1 = QtWidgets.QPushButton("P1")
        self.btn_camera_preset2 = QtWidgets.QPushButton("P2")
        self.btn_camera_preset3 = QtWidgets.QPushButton("P3")
        self.btn_camera_preset4 = QtWidgets.QPushButton("P4")

        h_preset_camera = QtWidgets.QHBoxLayout()
        for btn in (
            self.btn_camera_preset1,
            self.btn_camera_preset2,
            self.btn_camera_preset3,
            self.btn_camera_preset4,
        ):
            btn.setFixedWidth(40)  # Sample と同じ値に
            h_preset_camera.addWidget(btn)
        h_preset_camera.addStretch(1)

        grid_c.addLayout(h_preset_camera, 5, 0, 1, 2)


        # Sample / Camera カード
        body_layout.addWidget(self.gb_sample, r, 0, 1, 2)
        body_layout.addWidget(self.gb_camera, r, 2, 1, 2)
        r += 1

        # 軸ごとの status 行
        self.lbl_sample_status = QtWidgets.QLabel("[Sample] status: -")
        self.lbl_camera_status = QtWidgets.QLabel("[Camera] status: -")
        self.lbl_sample_status.setWordWrap(True)
        self.lbl_camera_status.setWordWrap(True)
        body_layout.addWidget(self.lbl_sample_status, r, 0, 1, 2)
        body_layout.addWidget(self.lbl_camera_status, r, 2, 1, 2)
        r += 1

        # === main layout に組み込み ===
        top.addWidget(self.body, row, 0, 1, 5)
        row += 1

        # 初期は body 非表示
        self.body.setEnabled(False)
        self.body.setVisible(False)

        # ---- wiring ----
        self.btn_connect_sample.clicked.connect(self._on_connect_sample_clicked)
        self.btn_connect_camera.clicked.connect(self._on_connect_camera_clicked)
        self.btn_sample_disconnect.clicked.connect(self._on_sample_disconnect_clicked)
        self.btn_camera_disconnect.clicked.connect(self._on_camera_disconnect_clicked)

        self.btn_reg.clicked.connect(self._on_reg_clicked)
        self.btn_goto.clicked.connect(self._on_goto_clicked)
        self.btn_startstop.clicked.connect(self._on_startstop_clicked)

        # 手動: Jog / Step
        self.btn_sample_up2.clicked.connect(self._on_sample_forward_clicked)
        self.btn_sample_down2.clicked.connect(self._on_sample_reverse_clicked)
        self.btn_camera_up2.clicked.connect(self._on_camera_forward_clicked)
        self.btn_camera_down2.clicked.connect(self._on_camera_reverse_clicked)

        """
        self.btn_sample_up1.clicked.connect(lambda: self._on_step_clicked(1, +1))
        self.btn_sample_down1.clicked.connect(lambda: self._on_step_clicked(1, -1))
        self.btn_camera_up1.clicked.connect(lambda: self._on_step_clicked(2, +1))
        self.btn_camera_down1.clicked.connect(lambda: self._on_step_clicked(2, -1))
        """

        self.btn_sample_up1.clicked.connect(lambda: self._on_step_clicked(1, StepDirection.FORWARD))
        self.btn_sample_down1.clicked.connect(lambda: self._on_step_clicked(1, StepDirection.REVERSE))
        self.btn_camera_up1.clicked.connect(lambda: self._on_step_clicked(2, StepDirection.FORWARD))
        self.btn_camera_down1.clicked.connect(lambda: self._on_step_clicked(2, StepDirection.REVERSE))

        
        self.btn_sample_home.clicked.connect(self._on_sample_home_clicked)
        self.btn_camera_home.clicked.connect(self._on_camera_home_clicked)

        # Start (Forward/Reverse)
        #self.btn_start_fwd.clicked.connect(self._toggle_forward)
        self.btn_start_rev.clicked.connect(self._toggle_reverse)

        # Settings dialog
        self.btn_settings.clicked.connect(self._on_settings_clicked)

        # Ctl プリセットボタン
        self.btn_sample_preset1.clicked.connect(lambda: self._on_ctl_preset_clicked("Sample", 0))
        self.btn_sample_preset2.clicked.connect(lambda: self._on_ctl_preset_clicked("Sample", 1))
        self.btn_sample_preset3.clicked.connect(lambda: self._on_ctl_preset_clicked("Sample", 2))
        self.btn_sample_preset4.clicked.connect(lambda: self._on_ctl_preset_clicked("Sample", 3))
        self.btn_camera_preset1.clicked.connect(lambda: self._on_ctl_preset_clicked("Camera", 0))
        self.btn_camera_preset2.clicked.connect(lambda: self._on_ctl_preset_clicked("Camera", 1))
        self.btn_camera_preset3.clicked.connect(lambda: self._on_ctl_preset_clicked("Camera", 2))
        self.btn_camera_preset4.clicked.connect(lambda: self._on_ctl_preset_clicked("Camera", 3))

        # Bridge からの stop に対して UI を同期
        #self.bridge.sig_stage_stop_only.connect(self._on_external_stop)
        # stop_return のときは _on_bridge_stage_stop_return 内で _on_external_stop を呼ぶ

        # Bridge → backend 呼び出し
        #self.bridge.sig_stage_start.connect(self._on_bridge_stage_start)
        #self.bridge.sig_stage_stop_only.connect(self._on_bridge_stage_stop_only)
        #self.bridge.sig_stage_stop_return.connect(self._on_bridge_stage_stop_return)

        # Bridge からの stop に対して UI を同期
        #self.bridge.sig_stage_stop.connect(self._on_external_stop)

        # Bridge → backend 呼び出し
        #self.bridge.sig_stage_start.connect(self._on_bridge_stage_start)
        #self.bridge.sig_stage_stop.connect(self._on_bridge_stage_stop)

        # Bridge → backend 呼び出し／UI 同期
        self.bridge.sig_stage_start.connect(self._on_bridge_stage_start)
        self.bridge.sig_stage_stop.connect(self._on_bridge_stage_stop)

        # ★追加：録画ループからの 1 ステップ依頼
        self.bridge.sig_step_once.connect(self._on_bridge_step_once)

        # 録画状態 → Start (test) ボタンの色
        try:
            self.bridge.sig_recording_state.connect(self._on_recording_state_changed)
        except Exception:
            pass

        # プロファイル／プリセットを自動復元
        self._load_prefs()
        self._update_axis_summary_labels()
        self._update_preset_buttons()
        self._update_groupbox_titles()

    # ---------------- status helper ----------------
    def _set_stage_status(self, msg: str):
        """全体（両軸共通）のメッセージ"""
        self.lbl_sample_status.setText(f"[Stage] {msg}")
        self.lbl_camera_status.setText(f"[Stage] {msg}")

    def _set_sample_status(self, msg: str):
        """Sample 軸専用メッセージ"""
        self.lbl_sample_status.setText(f"[Sample] {msg}")

    def _set_camera_status(self, msg: str):
        """Camera 軸専用メッセージ"""
        self.lbl_camera_status.setText(f"[Camera] {msg}")

    # ---------------- UI summary helpers ----------------
    #def _format_profile_summary(self, label: str, prof: StageProfile) -> str:
    #    return (
    #        f"{label}: "
    #        f"Move v={prof.v_move:.3f} acc={prof.acc_move:.1f}; "
    #        f"Step s={prof.step:.4f} v={prof.v_step:.3f} acc={prof.acc_step:.1f} {prof.dir}"
    #    )

    def _update_axis_summary_labels(self):
        # Sample
        self.lbl_sample_acq.setText(
            self._format_acq_summary(self.sample_state.acq_profile)
        )
        self.lbl_sample_ctl.setText(
            self._format_ctl_summary(self.sample_state.ctl_profile)
        )
        # Camera
        self.lbl_camera_acq.setText(
            self._format_acq_summary(self.camera_state.acq_profile)
        )
        self.lbl_camera_ctl.setText(
            self._format_ctl_summary(self.camera_state.ctl_profile)
        )

    def _update_preset_buttons(self):
        # Sample Ctl presets
        btns_s = [self.btn_sample_preset1, self.btn_sample_preset2, self.btn_sample_preset3, self.btn_sample_preset4]
        for i, btn in enumerate(btns_s):
            if i < len(self.sample_state.ctl_presets):
                btn.setText(self.sample_state.ctl_presets[i].name)
                btn.setEnabled(True)
            else:
                btn.setText(f"P{i+1}")
                btn.setEnabled(False)

        # Camera Ctl presets
        btns_c = [self.btn_camera_preset1, self.btn_camera_preset2, self.btn_camera_preset3, self.btn_camera_preset4]
        for i, btn in enumerate(btns_c):
            if i < len(self.camera_state.ctl_presets):
                btn.setText(self.camera_state.ctl_presets[i].name)
                btn.setEnabled(True)
            else:
                btn.setText(f"P{i+1}")
                btn.setEnabled(False)

    def _update_groupbox_titles(self):
        # serial は backend 側が保持している想定（なければ "-"）
        def title_for(axis_name: str, backend: Optional[IStageBackend]) -> str:
            serial = getattr(backend, "serial", None)
            if serial:
                return f"{axis_name} stage ({serial})"
            return f"{axis_name} stage (-)"

        self.gb_sample.setTitle(title_for("Sample", self.backend_sample if self._connected_sample else None))
        self.gb_camera.setTitle(title_for("Camera", self.backend_camera if self._connected_camera else None))

    # ---------------- backend 管理 ----------------
    def _create_backend_sample_if_needed(self) -> bool:
        key = self.cmb_backend_sample.currentData()
        if not key:
            self.lbl_sample_status.setText("ERROR: no Sample backend selected")
            return False

        # すでに同じ backend があれば再利用
        if self.backend_sample is not None and self._current_backend_key_sample == key:
            return True

        # 古い backend を破棄
        if self.backend_sample is not None:
            try:
                self.backend_sample.shutdown()
            except Exception:
                pass
            self.backend_sample = None
            self.sample_state.backend = None

        info = self.backends.get(key)
        if info is None:
            self.lbl_sample_status.setText(f"ERROR: unknown backend: {key}")
            return False

        backend_class = info["class"]
        backend = backend_class(self.timing_logger, parent=self)
        self.backend_sample = backend
        self.sample_state.backend = backend
        self._current_backend_key_sample = key
        backend.axis_name = "Sample"

        backend.sig_status.connect(self._on_sample_status)

        backend.sig_error.connect(
            lambda s: self.lbl_sample_status.setText(f"[Sample ERROR] {s}")
        )

        backend.sig_connected.connect(
            self._on_sample_connected_changed
        )
        backend.sig_supported_products.connect(
            lambda products: self._on_products_listed(1, products)
        )
        backend.sig_startpos_updated.connect(
            self._on_startpos_sample_updated
        )

        #backend.sig_step_done.connect(self.stage_bridge.sig_step_done)
        #backend.sig_step_done.connect(self.bridge.sig_step_done)

        self._update_groupbox_titles()
        return True

    def _create_backend_camera_if_needed(self) -> bool:
        key = self.cmb_backend_camera.currentData()
        if not key:
            self.lbl_camera_status.setText("ERROR: no Camera backend selected")
            return False

        if self.backend_camera is not None and self._current_backend_key_camera == key:
            return True

        if self.backend_camera is not None:
            try:
                self.backend_camera.shutdown()
            except Exception:
                pass
            self.backend_camera = None
            self.camera_state.backend = None

        info = self.backends.get(key)
        if info is None:
            self.lbl_camera_status.setText(f"ERROR: unknown backend: {key}")
            return False

        backend_class = info["class"]
        backend = backend_class(self.timing_logger, parent=self)
        self.backend_camera = backend
        self.camera_state.backend = backend
        self._current_backend_key_camera = key
        backend.axis_name = "Camera"

        backend.sig_status.connect(self._on_camera_status)

        backend.sig_error.connect(
            lambda s: self.lbl_camera_status.setText(f"[Camera ERROR] {s}")
        )

        backend.sig_connected.connect(
            self._on_camera_connected_changed
        )
        backend.sig_supported_products.connect(
            lambda products: self._on_products_listed(2, products)
        )
        backend.sig_startpos_updated.connect(
            self._on_startpos_camera_updated
        )

        self._update_groupbox_titles()
        return True

    # ---------------- 状態更新 UI ----------------
    @Slot(str)
    def _on_sample_status(self, msg: str):
        """Sample 軸用 status ラベル更新"""
        if hasattr(self, "lbl_sample_status") and self.lbl_sample_status is not None:
            self.lbl_sample_status.setText(f"[Sample] {msg}")

    @Slot(str)
    def _on_camera_status(self, msg: str):
        """Camera 軸用 status ラベル更新"""
        if hasattr(self, "lbl_camera_status") and self.lbl_camera_status is not None:
            self.lbl_camera_status.setText(f"[Camera] {msg}")

    @Slot(bool)
    def _on_sample_connected_changed(self, connected: bool):
        self._connected_sample = bool(connected)
        self._update_connected_state()

    @Slot(bool)
    def _on_camera_connected_changed(self, connected: bool):
        self._connected_camera = bool(connected)
        self._update_connected_state()

    def _update_connected_state(self):
        new_connected = self._connected_sample or self._connected_camera
        self._connected = new_connected

        self.body.setEnabled(new_connected)
        self.body.setVisible(new_connected)

        # ---- Sample 軸が接続されたら、その行だけ消す ----
        if self._connected_sample:
            for w in (
                getattr(self, "lbl_backend_sample", None),
                getattr(self, "cmb_backend_sample", None),
                getattr(self, "btn_connect_sample", None),
            ):
                if w is not None:
                    w.setVisible(False)

        # ---- Camera 軸が接続されたら、その行だけ消す ----
        if self._connected_camera:
            for w in (
                getattr(self, "lbl_backend_camera", None),
                getattr(self, "cmb_backend_camera", None),
                getattr(self, "btn_connect_camera", None),
            ):
                if w is not None:
                    w.setVisible(False)

        # ---- スタート位置ボタンの有効化 ----
        if not new_connected:
            self._test_running = False
            self.btn_startstop.setText("Start (test)")
            self.btn_startstop.setStyleSheet("")
            self._fwd_running = False
            self._rev_running = False
            #self.btn_start_fwd.setText("Start (Forward)")
            #self.btn_start_fwd.setStyleSheet("")
            self.btn_start_rev.setText("Start (Opposite)")
            self.btn_start_rev.setStyleSheet("")

        self.btn_goto.setEnabled(self._connected and self._has_startpos)

        self._update_groupbox_titles()

        # ---- MainWindow へ中継 ----
        self.sig_connected.emit(self._connected)

    def _refresh_connected_flags_from_backend(self):
        """
        backend 側の状態を元に _connected_sample / _connected_camera を更新する。
        sig_connected が emit されない backend 用のフォールバック。
        """
        # Sample
        if self.backend_sample is not None:
            if hasattr(self.backend_sample, "connected"):
                self._connected_sample = bool(self.backend_sample.connected)
            else:
                self._connected_sample = bool(getattr(self.backend_sample, "_connected", False))
        else:
            self._connected_sample = False

        # Camera
        if self.backend_camera is not None:
            if hasattr(self.backend_camera, "connected"):
                self._connected_camera = bool(self.backend_camera.connected)
            else:
                self._connected_camera = bool(getattr(self.backend_camera, "_connected", False))
        else:
            self._connected_camera = False

        self._update_connected_state()

    @Slot()
    def _on_sample_disconnect_clicked(self):
        if self.backend_sample:
            try:
                self.backend_sample.shutdown()
            except Exception:
                pass
        self._connected_sample = False
        self.backend_sample = None
        self.sample_state.backend = None

        # 非表示にしていた行を復活
        for w in (
            self.lbl_backend_sample,
            self.cmb_backend_sample,
            self.btn_connect_sample,
        ):
            if w is not None:
                w.setVisible(True)

        self._update_connected_state()

    @Slot()
    def _on_camera_disconnect_clicked(self):
        if self.backend_camera:
            try:
                self.backend_camera.shutdown()
            except Exception:
                pass
        self._connected_camera = False
        self.backend_camera = None
        self.camera_state.backend = None

        for w in (
            self.lbl_backend_camera,
            self.cmb_backend_camera,
            self.btn_connect_camera,
        ):
            if w is not None:
                w.setVisible(True)

        self._update_connected_state()

    @Slot(float)
    def _on_startpos_sample_updated(self, pos_mm: float):
        """Sample 軸の start position 更新（ラベルなし版）"""
        self._start_sample_mm = pos_mm
        self._update_startpos_label()

    @Slot(float)
    def _on_startpos_camera_updated(self, pos_mm: float):
        """Camera 軸の start position 更新（ラベルなし版）"""
        self._start_camera_mm = pos_mm
        self._update_startpos_label()

    def _update_startpos_label(self):
        """
        Start position の内部状態だけ更新する。
        """
        self._has_startpos = (
            self._start_sample_mm is not None or self._start_camera_mm is not None
        )
        self.btn_goto.setEnabled(self._connected and self._has_startpos)

    # ---------------- Button handlers ----------------
    @Slot()
    def _on_connect_sample_clicked(self):
        """
        Sample 軸: Connect ボタン
        → backend を生成
        → backend.axis_name を "Sample" にして show_setup_dialog() を呼ぶ
        （ダイアログ内で serial 入力〜接続〜device 選択まで完結）
        """
        if not self._create_backend_sample_if_needed():
            self._set_sample_status("ERROR: cannot create Sample backend")
            return

        setattr(self.backend_sample, "axis_name", "Sample")

        ok = False
        try:
            ok = self.backend_sample.show_setup_dialog(self)
        except Exception as e:
            self._set_sample_status(f"[Sample ERROR] setup dialog: {e}")
            ok = False

        if not ok:
            self._refresh_connected_flags_from_backend()
            return

        self._refresh_connected_flags_from_backend()
        self._save_prefs()

    @Slot()
    def _on_connect_camera_clicked(self):
        """
        Camera 軸: Connect ボタン
        （Sample と同様のフロー）
        """
        if not self._create_backend_camera_if_needed():
            self._set_camera_status("ERROR: cannot create Camera backend")
            return

        setattr(self.backend_camera, "axis_name", "Camera")

        ok = False
        try:
            ok = self.backend_camera.show_setup_dialog(self)
        except Exception as e:
            self._set_camera_status(f"[Camera ERROR] setup dialog: {e}")
            ok = False

        if not ok:
            self._refresh_connected_flags_from_backend()
            return

        self._refresh_connected_flags_from_backend()
        self._save_prefs()

    @Slot()
    def _on_reg_clicked(self):
        if not self._connected:
            self._set_stage_status("ERROR: not connected")
            return
        # 両軸の Start position を登録（接続されているものだけ）
        try:
            if self.backend_sample is not None and self._connected_sample:
                self.backend_sample.register_start_point()
            if self.backend_camera is not None and self._connected_camera:
                self.backend_camera.register_start_point()
        except Exception as e:
            self._set_stage_status(f"ERROR: register_start_point: {e}")

    @Slot()
    def _on_goto_clicked(self):
        if not self._connected:
            self._set_stage_status("ERROR: not connected")
            return
        try:
            if self.backend_sample is not None and self._connected_sample:
                self.backend_sample.go_to_start_position()
            if self.backend_camera is not None and self._connected_camera:
                self.backend_camera.go_to_start_position()
        except Exception as e:
            self._set_stage_status(f"ERROR: go_to_start_position: {e}")

    @Slot()
    def _on_sample_home_clicked(self):
        if not (self.backend_sample and self._connected_sample):
            self.lbl_sample_status.setText("ERROR: Sample not connected")
            return

        self.btn_sample_home.setText("Homing...")
        self.btn_sample_home.setStyleSheet(self._style_running_red)
        QtWidgets.QApplication.processEvents()

        try:
            self.backend_sample.home()
        finally:
            self.btn_sample_home.setText("Home")
            self.btn_sample_home.setStyleSheet("")

    @Slot()
    def _on_camera_home_clicked(self):
        if not (self.backend_camera and self._connected_camera):
            self.lbl_camera_status.setText("ERROR: Camera not connected")
            return

        self.btn_camera_home.setText("Homing...")
        self.btn_camera_home.setStyleSheet(self._style_running_red)
        QtWidgets.QApplication.processEvents()

        try:
            self.backend_camera.home()
        finally:
            self.btn_camera_home.setText("Home")
            self.btn_camera_home.setStyleSheet("")

    @Slot()
    def _on_sample_forward_clicked(self):
        if not (self.backend_sample and self._connected_sample):
            self.lbl_sample_status.setText("ERROR: Sample not connected")
            return
        if self._test_running or self._fwd_running or self._rev_running:
            self.lbl_sample_status.setText("ERROR: stage test running")
            return

        # recording 中は Jog 禁止
        if self._recording_active:
            self.lbl_sample_status.setText("ERROR: recording - cannot jog")
            return

        if self._test_running or self._fwd_running or self._rev_running:
            self.lbl_sample_status.setText("ERROR: stage test running")
            return

        if not self._sample_jog_running:
            # Manual 用 Ctl プロファイルを適用
            self._apply_ctl_profile_to_backend(self.sample_state, self.backend_sample, self._connected_sample)
            self.backend_sample.start_jog(0)  # 0=Forward
            self._sample_jog_running = True
            self.btn_sample_up2.setText("Stop")
            self.btn_sample_up2.setStyleSheet(self._style_running_red)
            self.btn_sample_down2.setEnabled(False)
        else:
            self.backend_sample.stop_jog()
            self._sample_jog_running = False
            self.btn_sample_up2.setText("↑↑")
            self.btn_sample_up2.setStyleSheet("")
            self.btn_sample_down2.setEnabled(True)

    @Slot()
    def _on_sample_reverse_clicked(self):
        if not (self.backend_sample and self._connected_sample):
            self.lbl_sample_status.setText("ERROR: Sample not connected")
            return
        if self._test_running or self._fwd_running or self._rev_running:
            self.lbl_sample_status.setText("ERROR: stage test running")
            return

        # recording 中は Jog 禁止
        if self._recording_active:
            self.lbl_sample_status.setText("ERROR: recording - cannot jog")
            return

        if self._test_running or self._fwd_running or self._rev_running:
            self.lbl_sample_status.setText("ERROR: stage test running")
            return

        if not self._sample_jog_running:
            self._apply_ctl_profile_to_backend(self.sample_state, self.backend_sample, self._connected_sample)
            self.backend_sample.start_jog(1)  # 1=Reverse
            self._sample_jog_running = True
            self.btn_sample_down2.setText("Stop")
            self.btn_sample_down2.setStyleSheet(self._style_running_red)
            self.btn_sample_up2.setEnabled(False)
        else:
            self.backend_sample.stop_jog()
            self._sample_jog_running = False
            self.btn_sample_down2.setText("↓↓")
            self.btn_sample_down2.setStyleSheet("")
            self.btn_sample_up2.setEnabled(True)

    @Slot()
    def _on_camera_forward_clicked(self):
        if not (self.backend_camera and self._connected_camera):
            self.lbl_camera_status.setText("ERROR: Camera not connected")
            return
        if self._test_running or self._fwd_running or self._rev_running:
            self.lbl_camera_status.setText("ERROR: stage test running")
            return

        # recording 中は Jog 禁止
        if self._recording_active:
            self.lbl_camera_status.setText("ERROR: recording - cannot jog")
            return

        if self._test_running or self._fwd_running or self._rev_running:
            self.lbl_camera_status.setText("ERROR: stage test running")
            return

        if not self._camera_jog_running:
            self._apply_ctl_profile_to_backend(self.camera_state, self.backend_camera, self._connected_camera)
            self.backend_camera.start_jog(0)
            self._camera_jog_running = True
            self.btn_camera_up2.setText("Stop")
            self.btn_camera_up2.setStyleSheet(self._style_running_red)
            self.btn_camera_down2.setEnabled(False)
        else:
            self.backend_camera.stop_jog()
            self._camera_jog_running = False
            self.btn_camera_up2.setText("↑↑")
            self.btn_camera_up2.setStyleSheet("")
            self.btn_camera_down2.setEnabled(True)

    @Slot()
    def _on_camera_reverse_clicked(self):
        if not (self.backend_camera and self._connected_camera):
            self.lbl_camera_status.setText("ERROR: Camera not connected")
            return
        if self._test_running or self._fwd_running or self._rev_running:
            self.lbl_camera_status.setText("ERROR: stage test running")
            return

        # recording 中は Jog 禁止
        if self._recording_active:
            self.lbl_camera_status.setText("ERROR: recording - cannot jog")
            return

        if self._test_running or self._fwd_running or self._rev_running:
            self.lbl_camera_status.setText("ERROR: stage test running")
            return

        if not self._camera_jog_running:
            self._apply_ctl_profile_to_backend(self.camera_state, self.backend_camera, self._connected_camera)
            self.backend_camera.start_jog(1)
            self._camera_jog_running = True
            self.btn_camera_down2.setText("Stop")
            self.btn_camera_down2.setStyleSheet(self._style_running_red)
            self.btn_camera_up2.setEnabled(False)
        else:
            self.backend_camera.stop_jog()
            self._camera_jog_running = False
            self.btn_camera_down2.setText("↓↓")
            self.btn_camera_down2.setStyleSheet("")
            self.btn_camera_up2.setEnabled(True)
    """
    def _on_step_clicked(self, dev_index: int, direction_sign: int):
        if not self._connected:
            self._set_stage_status("ERROR: not connected")
            return

        # recording 中は Step 禁止
        if self._recording_active:
            self._set_stage_status("ERROR: recording - cannot step")
            return

        # Start(test) / Reverse 実行中は Step 禁止
        if self._test_running or self._rev_running:
            self._set_stage_status("ERROR: test running - cannot step")
            return

        # Jog 中も Step 禁止（Jog < Step のため、先に Jog を止めさせる）
        if dev_index == 1 and self._sample_jog_running:
            self._set_sample_status("ERROR: Sample jog running - stop jog first")
            return
        if dev_index == 2 and self._camera_jog_running:
            self._set_camera_status("ERROR: Camera jog running - stop jog first")
            return

        try:
            if dev_index == 1:
                if self.backend_sample and self._connected_sample:
                    self._apply_ctl_step_profile_to_backend(
                        self.sample_state, self.backend_sample, self._connected_sample
                    )
                    self.backend_sample.step(direction_sign)
                else:
                    self._set_sample_status("ERROR: Sample not connected")
            else:
                if self.backend_camera and self._connected_camera:
                    self._apply_ctl_step_profile_to_backend(
                        self.camera_state, self.backend_camera, self._connected_camera
                    )
                    self.backend_camera.step(direction_sign)
                else:
                    self._set_camera_status("ERROR: Camera not connected")
        except Exception as e:
            self._set_stage_status(f"ERROR: step({dev_index}): {e}")
    """

    def _on_step_clicked(self, dev_index: int, direction: StepDirection):
        if not self._connected:
            self._set_stage_status("ERROR: not connected")
            return

        # recording 中は Step 禁止
        if self._recording_active:
            self._set_stage_status("ERROR: recording - cannot step")
            return

        # Start(test) / Reverse 実行中は Step 禁止
        if self._test_running or self._rev_running:
            self._set_stage_status("ERROR: test running - cannot step")
            return

        # Jog 中も Step 禁止（Jog < Step のため、先に Jog を止めさせる）
        if dev_index == 1 and self._sample_jog_running:
            self._set_sample_status("ERROR: Sample jog running - stop jog first")
            return
        if dev_index == 2 and self._camera_jog_running:
            self._set_camera_status("ERROR: Camera jog running - stop jog first")
            return

        try:
            if dev_index == 1:
                if self.backend_sample and self._connected_sample:
                    self._apply_ctl_step_profile_to_backend(
                        self.sample_state, self.backend_sample, self._connected_sample
                    )
                    self.backend_sample.step(direction)
                else:
                    self._set_sample_status("ERROR: Sample not connected")
            else:
                if self.backend_camera and self._connected_camera:
                    self._apply_ctl_step_profile_to_backend(
                        self.camera_state, self.backend_camera, self._connected_camera
                    )
                    self.backend_camera.step(direction)
                else:
                    self._set_camera_status("ERROR: Camera not connected")
        except Exception as e:
            self._set_stage_status(f"ERROR: step({dev_index}): {e}")

    """
    def _do_acq_step_once(self, reverse: bool = False):
        
        #Acq Profile (mode=Step) に基づいて、
        #接続されている軸を 1 回だけステップさせる。
        #reverse=True の場合は Acq.dir と逆向きに動かす。
        
        #if not (
        #    self.sample_state.acq_profile.mode == "Step" and self.camera_state.acq_profile.mode == "Step"):
        #    self._set_stage_status("ERROR: both axes must be Step mode for Step test")
        #    return

        def _step_axis(axis_state: AxisState,
                    backend: Optional[IStageBackend],
                    connected: bool):
            if not (backend and connected):
                return
            p = axis_state.acq_profile
            #if p.mode != "Step":
            #    return

            # dir を必要なら反転
            dir_char = p.dir
            if reverse:
                dir_char = "R" if dir_char == "F" else "F"

            dir_idx = 0 if dir_char == "F" else 1
            sign = +1 if dir_char == "F" else -1

            if hasattr(backend, "configure_step"):
                backend.configure_step(p.step, p.v_step, p.acc_step, dir_idx)
            else:
                backend.apply_params(p.v_step, p.acc_step, dir_idx)

            backend.step(sign)

        _step_axis(self.sample_state, self.backend_sample, self._connected_sample)
        _step_axis(self.camera_state, self.backend_camera, self._connected_camera)
    """
    def _do_acq_step_once(self, reverse: bool = False):
        """
        Acq Profile (mode=Step) に基づいて、
        接続されている軸を 1 回だけステップさせる。
        reverse=True の場合は Acq.dir と逆向きに動かす。
        """

        def _step_axis(axis_state: AxisState,
                       backend: Optional[IStageBackend],
                       connected: bool):
            if not (backend and connected):
                return
            p = axis_state.acq_profile

            # dir を必要なら反転
            dir_char = p.dir
            if reverse:
                dir_char = "R" if dir_char == "F" else "F"

            # StepDirection に変換
            if dir_char == "F":
                step_dir = StepDirection.FORWARD
                dir_idx = 0
            else:
                step_dir = StepDirection.REVERSE
                dir_idx = 1

            if hasattr(backend, "configure_step"):
                backend.configure_step(p.step, p.v_step, p.acc_step, dir_idx)
            else:
                backend.apply_params(p.v_step, p.acc_step, dir_idx)

            backend.step(step_dir)

        _step_axis(self.sample_state, self.backend_sample, self._connected_sample)
        _step_axis(self.camera_state, self.backend_camera, self._connected_camera)


    """# Step
    def _start_step_test(self):
        #Acq Step モードでの連続ステップ開始（Start(test) 用・正方向）
        if self._test_running:
            # すでに Step 連続動作中（Forward/Reverse いずれか）なら何もしない
            return

        self._step_owner = "test"
        self._test_running = True

        # ボタン表示を整える
        self.btn_startstop.setText("Stop (test)")
        self.btn_startstop.setStyleSheet(self._style_running_red)
        self.btn_start_rev.setText("Start (Opposite)")
        self.btn_start_rev.setStyleSheet("")

        # 1 回目はすぐ実行
        self._on_step_test_tick()
        # 以降はタイマーで連続ステップ
        if not self._step_test_timer.isActive():
            self._step_test_timer.start()

    # Step
    def _stop_step_test(self):
        #Acq Step モードでの連続ステップ停止（Forward/Reverse 共通）
        if self._step_test_timer.isActive():
            self._step_test_timer.stop()

        if self._test_running:
            self._test_running = False

        self._step_owner = "none"

        # 両ボタンをデフォルト状態に戻す
        self.btn_startstop.setText("Start (test)")
        self.btn_startstop.setStyleSheet("")
        self.btn_start_rev.setText("Start (Opposite)")
        self.btn_start_rev.setStyleSheet("")
    """
    """
    def _start_step_test(self):
        #Acq Step モードでの連続ステップ開始（Start(test) 用・正方向）
        if self._test_running:
            # すでに Step 連続動作中（Forward/Reverse いずれか）なら何もしない
            return

        self._step_owner = "test"
        self._test_running = True

        # ボタン表示を整える
        self.btn_startstop.setText("Stop (test)")
        self.btn_startstop.setStyleSheet(self._style_running_red)
        self.btn_start_rev.setText("Start (Opposite)")
        self.btn_start_rev.setStyleSheet("")

        # 1 回目はすぐ実行
        self._on_step_test_tick()
        # 以降はタイマーで連続ステップ
        if not self._step_test_timer.isActive():
            self._step_test_timer.start()


    def _stop_step_test(self):
        #Acq Step モードでの連続ステップ停止（Forward/Reverse 共通）
        if self._step_test_timer.isActive():
            self._step_test_timer.stop()

        if self._test_running:
            self._test_running = False

        self._step_owner = "none"

        # 両ボタンをデフォルト状態に戻す
        self.btn_startstop.setText("Start (test)")
        self.btn_startstop.setStyleSheet("")
        self.btn_start_rev.setText("Start (Opposite)")
        self.btn_start_rev.setStyleSheet("")

    
    # Step
    def _on_step_test_tick(self):
        #Step モード連続テスト用タイマーから呼ばれる（Forward / Reverse 共通）
        # オーナーと状態が不正なら終了
        if (not self._test_running) or self._step_owner not in ("test", "reverse"):
            self._stop_step_test()
            return

        try:
            reverse = (self._step_owner == "reverse")
            self._do_acq_step_once(reverse=reverse)
        except Exception as e:
            self._set_stage_status(f"ERROR: Step test: {e}")
            self._stop_step_test()
    """        

    def _stop_step_test(self):
        #Acq Step モードでの連続ステップ停止（Forward/Reverse 共通）
        if self._test_running:
            self._test_running = False
        # 両ボタンをデフォルト状態に戻す
        self.btn_startstop.setText("Start (test)")
        self.btn_startstop.setStyleSheet("")
        self.btn_start_rev.setText("Start (Opposite)")
        self.btn_start_rev.setStyleSheet("")

    # Start(test) for Move & Step
    @Slot()
    def _on_startstop_clicked(self):
        ...
        s_mode = self.sample_state.acq_profile.mode
        c_mode = self.camera_state.acq_profile.mode
        ...
        # --- Step モード: 両軸 Step のときだけ「1 回ステップ」 ---
        if s_mode == "Step" or c_mode == "Step":
            if not (s_mode == "Step" and c_mode == "Step"):
                self._set_stage_status(
                    "ERROR: Start(test) in Step mode requires both axes = Step"
                )
                return

            try:
                # 正方向に 1 回だけステップ
                self._do_acq_step_once(reverse=False)
                self._set_stage_status("Step test: 1 step forward")
            except Exception as e:
                self._set_stage_status(f"ERROR: Start(test) Step: {e}")
            return

        # --- Move モード: 従来どおり連続走査（Bridge 経由） ---
        else:
            if not self._test_running:
                self._apply_profiles_to_backends()
                self.bridge.sig_stage_start.emit()
                self._test_running = True
                self.btn_startstop.setText("Stop (test)")
                self.btn_startstop.setStyleSheet(self._style_running_red)
            else:
                #self.bridge.sig_stage_stop.emit(int(StageStopMode.STOP_ONLY))
                self.bridge.on_stage_stop()
                self._test_running = False
                self.btn_startstop.setText("Start (test)")
                self.btn_startstop.setStyleSheet("")

        """
    # Start(tset) for Move & Step
    @Slot()
    def _on_startstop_clicked(self):
        if not self._connected:
            self._set_stage_status("ERROR: not connected")
            return

        s_mode = self.sample_state.acq_profile.mode
        c_mode = self.camera_state.acq_profile.mode

        # ---- Recording 中はテスト禁止（優先度: recording > Move/Step/Jog）----
        if self._recording_active:
            self._set_stage_status("ERROR: recording - cannot Start(test)")
            return

        # ---- Jog 中はテスト禁止（Jog < Step/Move）----
        if self._sample_jog_running or self._camera_jog_running:
            self._set_stage_status("ERROR: jog running - stop jog first")
            return

        # ---- Reverse 走査中も禁止 ----
        if self._rev_running:
            self._set_stage_status("ERROR: Reverse running - stop it first")
            return

        # --- Step モード: 連続ステップのトグル ---

        if s_mode == "Step" or c_mode == "Step":
            if not (s_mode == "Step" and c_mode == "Step"):
                self._set_stage_status("ERROR: Start(test) in Step mode requires both axes = Step")
                return

            # トグル動作
            if not self._test_running:
                self._apply_profiles_to_backends()  # いらない？どこかで適用してる？
                self._start_step_test() # Start(test)ではカメラからのシグナルがないから
                self._test_running = True
                self.btn_startstop.setText("Stop (test)")
                self.btn_startstop.setStyleSheet(self._style_running_red)
            else:
                self._stop_step_test()  # Start(test)ではカメラからのシグナルがないから
                self._test_running = False
                self.btn_startstop.setText("Start (test)")
                self.btn_startstop.setStyleSheet("")
            return

        if s_mode == "Step" or c_mode == "Step":
            if not (s_mode == "Step" and c_mode == "Step"):
                self._set_stage_status(
                    "ERROR: Start(test) in Step mode requires both axes = Step"
                )
                return

            # トグル動作
            if not self._test_running:
                self._apply_profiles_to_backends()
                self._start_step_test()   # ← これだけで OK（内部でフラグとボタン更新）
            else:
                self._stop_step_test()    # ← これだけで OK
            return

        # --- Move モード: 従来どおり連続走査（Bridge 経由） ---
        else:
            if not self._test_running:
                self._apply_profiles_to_backends()
                self.bridge.sig_stage_start.emit()  # Start recording と Start(test) が同じ動き
                self._test_running = True
                self.btn_startstop.setText("Stop (test)")
                self.btn_startstop.setStyleSheet(self._style_running_red)
            else:
                # StagePanel からのテスト停止は「STOP_ONLY / direction 無し」で送る
                self.bridge.sig_stage_stop.emit(int(StageStopMode.STOP_ONLY))
                self._test_running = False
                self.btn_startstop.setText("Start (test)")
                self.btn_startstop.setStyleSheet("")
            """
    """
    def _do_step_test(self):
        # Acq mode が Step の軸について、
        # Acq の Step パラメータで 1 ステップだけ動かす簡易テスト。
        # Start(test) ボタンはトグルにはせず、一発動作だけ。
        moved = False
        try:
            # Sample 軸
            if (
                self.backend_sample
                and self._connected_sample
                and self.sample_state.acq_profile.mode == "Step"
            ):
                self._apply_acq_step_profile_to_backend(
                    self.sample_state, self.backend_sample, True
                )
                sign = +1 if self.sample_state.acq_profile.dir == "F" else -1
                self.backend_sample.step(sign)
                moved = True

            # Camera 軸
            if (
                self.backend_camera
                and self._connected_camera
                and self.camera_state.acq_profile.mode == "Step"
            ):
                self._apply_acq_step_profile_to_backend(
                    self.camera_state, self.backend_camera, True
                )
                sign = +1 if self.camera_state.acq_profile.dir == "F" else -1
                self.backend_camera.step(sign)
                moved = True

        except Exception as e:
            self._set_stage_status(f"ERROR: step test: {e}")
            return

        if not moved:
            self._set_stage_status("Step mode の軸がありません（Acq mode が Move のみ）")
        else:
            self._set_stage_status("Step test executed (Acq Step)")

    """
    """
    def _toggle_forward(self):
        #Start/Stop toggle for Forward (Acq の dir を一時的に F にして走査)
        if not self._connected:
            self._set_stage_status("ERROR: not connected")
            return

        if self._test_running:
            self._set_stage_status("ERROR: test running - cannot start forward")
            return
        if self._rev_running:
            self._set_stage_status("ERROR: Reverse running - stop it first")
            return

        if not self._fwd_running:
            # dir を一時的に F にして走査
            self._prev_acq_dirs = (self.sample_state.acq_profile.dir,
                                   self.camera_state.acq_profile.dir)
            self.sample_state.acq_profile.dir = "F"
            self.camera_state.acq_profile.dir = "F"
            self._apply_profiles_to_backends()
            self.bridge.sig_stage_start.emit()
            self._fwd_running = True
            #self.btn_start_fwd.setText("Stop (Forward)")
            #self.btn_start_fwd.setStyleSheet(self._style_running_red)
            self._set_stage_status("Started (Forward)")
        else:
            self.bridge.sig_stage_stop_only.emit()
            self._fwd_running = False
            #self.btn_start_fwd.setText("Start (Forward)")
            #self.btn_start_fwd.setStyleSheet("")

            # dir を元に戻す
            if self._prev_acq_dirs is not None:
                s_dir, c_dir = self._prev_acq_dirs
                self.sample_state.acq_profile.dir = s_dir
                self.camera_state.acq_profile.dir = c_dir
                self._apply_profiles_to_backends()
                self._prev_acq_dirs = None

            self._set_stage_status("Stopped (Forward)")

    def _toggle_reverse(self):
        # Start/Stop toggle for Reverse (Acq の dir を一時的に R にして走査)
        if not self._connected:
            self._set_stage_status("ERROR: not connected")
            return

        if self._test_running:
            self._set_stage_status("ERROR: test running - cannot start reverse")
            return
        if self._fwd_running:
            self._set_stage_status("ERROR: Forward running - stop it first")
            return

        if not self._rev_running:
            self._prev_acq_dirs = (self.sample_state.acq_profile.dir,
                                   self.camera_state.acq_profile.dir)
            self.sample_state.acq_profile.dir = "R"
            self.camera_state.acq_profile.dir = "R"
            self._apply_profiles_to_backends()
            self.bridge.sig_stage_start.emit()
            self._rev_running = True
            self.btn_start_rev.setText("Stop (Reverse)")
            self.btn_start_rev.setStyleSheet(self._style_running_red)
            self._set_stage_status("Started (Reverse)")
        else:
            self.bridge.sig_stage_stop_only.emit()
            self._rev_running = False
            self.btn_start_rev.setText("Start (Reverse)")
            self.btn_start_rev.setStyleSheet("")

            if self._prev_acq_dirs is not None:
                s_dir, c_dir = self._prev_acq_dirs
                self.sample_state.acq_profile.dir = s_dir
                self.camera_state.acq_profile.dir = c_dir
                self._apply_profiles_to_backends()
                self._prev_acq_dirs = None

            self._set_stage_status("Stopped (Reverse)")
        """

    def _toggle_reverse(self):
        #Start/Stop toggle for Reverse
        #Move モード:Acq.dir を一時的に反転させて連続走査。
        #Step モード:
        #    Start(test) の逆向きに連続ステップ。
        #    （Acq.dir が F なら R 方向へ連続、R なら F 方向へ連続）

        if not self._connected:
            self._set_stage_status("ERROR: not connected")
            return

        # recording 中は Reverse 禁止
        if self._recording_active:
            self._set_stage_status("ERROR: recording - cannot start reverse")
            return
    
        s_mode = self.sample_state.acq_profile.mode
        c_mode = self.camera_state.acq_profile.mode

        # --- Step モード: 逆方向に 1 回だけステップ ---
        if s_mode == "Step" or c_mode == "Step":
            if not (s_mode == "Step" and c_mode == "Step"):
                self._set_stage_status(
                    "ERROR: Start(Opposite) in Step mode requires both axes = Step"
                )
                return

            try:
                # 逆方向に 1 回だけステップ
                self._do_acq_step_once(reverse=True)
                self._set_stage_status("Step opposite: 1 step")
            except Exception as e:
                self._set_stage_status(f"ERROR: Start(Opposite) Step: {e}")
            return

        # --- Move モード: これまで通りの「反転走査」 ---
        if self._test_running:
            self._set_stage_status("ERROR: test running - cannot start reverse")
            return
        if self._rev_running:
            # 停止
            #self.bridge.sig_stage_stop_only.emit()
            #self.bridge.sig_stage_stop.emit(int(StageStopMode.STOP_ONLY))
            self.bridge.on_stage_stop()
            self._rev_running = False
            self.btn_start_rev.setText("Start (Opposite)")
            self.btn_start_rev.setStyleSheet("")

            if self._prev_acq_dirs is not None:
                s_dir, c_dir = self._prev_acq_dirs
                self.sample_state.acq_profile.dir = s_dir
                self.camera_state.acq_profile.dir = c_dir
                self._apply_profiles_to_backends()
                self._prev_acq_dirs = None

            self._set_stage_status("Stopped (Opposite)")
            return

        # 開始（Move のときだけここに来る）
        s_dir_orig = self.sample_state.acq_profile.dir
        c_dir_orig = self.camera_state.acq_profile.dir
        self._prev_acq_dirs = (s_dir_orig, c_dir_orig)

        def flip(d: str) -> str:
            return "R" if d == "F" else "F"

        self.sample_state.acq_profile.dir = flip(s_dir_orig)
        self.camera_state.acq_profile.dir = flip(c_dir_orig)

        self._apply_profiles_to_backends()
        self.bridge.sig_stage_start.emit()

        self._rev_running = True
        self.btn_start_rev.setText("Stop (Reverse)")
        self.btn_start_rev.setStyleSheet(self._style_running_red)
        self._set_stage_status("Started (Reverse)")


    """
    def _toggle_reverse(self):

        #Start/Stop toggle for Reverse
        #Move モード:Acq.dir を一時的に反転させて連続走査。
        #Step モード:
            Start(test) の逆向きに連続ステップ。
            （Acq.dir が F なら R 方向へ連続、R なら F 方向へ連続）

        if not self._connected:
            self._set_stage_status("ERROR: not connected")
            return

        # recording 中は Reverse 禁止
        if self._recording_active:
            self._set_stage_status("ERROR: recording - cannot start reverse")
            return

        s_mode = self.sample_state.acq_profile.mode
        c_mode = self.camera_state.acq_profile.mode

        # Jog 中は Reverse 禁止
        if self._sample_jog_running or self._camera_jog_running:
            self._set_stage_status("ERROR: jog running - stop jog first")
            return

        # --- Step モード: 連続ステップ（Start(test) の逆向き）---
        if s_mode == "Step" or c_mode == "Step":
            if not (s_mode == "Step" and c_mode == "Step"):
                self._set_stage_status(
                    "ERROR: Start(Opposite) in Step mode requires both axes = Step"
                )
                return

            # まだ Step 連続動作していない → 逆向き連続スタート
            if not self._test_running:
                self._step_owner = "reverse"
                self._test_running = True

                # ボタン表示（Opposite 側を赤、test 側はデフォルト）
                self.btn_start_rev.setText("Stop (Opposite)")
                self.btn_start_rev.setStyleSheet(self._style_running_red)
                self.btn_startstop.setText("Start (test)")
                self.btn_startstop.setStyleSheet("")

                # 1 回目を即時実行
                self._on_step_test_tick()
                if not self._step_test_timer.isActive():
                    self._step_test_timer.start()
                return

            # すでに Step 連続中
            if self._step_owner == "reverse":
                # 自分がオーナーならトグル停止
                self._stop_step_test()
                return
            else:
                # Forward 実行中はエラー
                self._set_stage_status(
                    "ERROR: Step test (Forward) running - stop it first"
                )
                return

        # --- Move モード: これまで通りの「反転走査」 ---
        if self._test_running:
            self._set_stage_status("ERROR: test running - cannot start reverse")
            return
        if self._rev_running:
            # 停止
            #self.bridge.sig_stage_stop_only.emit()
            self.bridge.sig_stage_stop.emit(int(StageStopMode.STOP_ONLY))
            self._rev_running = False
            self.btn_start_rev.setText("Start (Opposite)")
            self.btn_start_rev.setStyleSheet("")

            if self._prev_acq_dirs is not None:
                s_dir, c_dir = self._prev_acq_dirs
                self.sample_state.acq_profile.dir = s_dir
                self.camera_state.acq_profile.dir = c_dir
                self._apply_profiles_to_backends()
                self._prev_acq_dirs = None

            self._set_stage_status("Stopped (Opposite)")
            return

        # 開始（Move のときだけここに来る）
        s_dir_orig = self.sample_state.acq_profile.dir
        c_dir_orig = self.camera_state.acq_profile.dir
        self._prev_acq_dirs = (s_dir_orig, c_dir_orig)

        def flip(d: str) -> str:
            return "R" if d == "F" else "F"

        self.sample_state.acq_profile.dir = flip(s_dir_orig)
        self.camera_state.acq_profile.dir = flip(c_dir_orig)

        self._apply_profiles_to_backends()
        self.bridge.sig_stage_start.emit()

        self._rev_running = True
        self.btn_start_rev.setText("Stop (Reverse)")
        self.btn_start_rev.setStyleSheet(self._style_running_red)
        self._set_stage_status("Started (Reverse)")
        """
    
    @Slot()
    def _on_external_stop(self):
        """外部（camera 等）から stop が来たときに UI 状態をクリアする"""
        if self._rev_running:
            self._rev_running = False
            self.btn_start_rev.setText("Start (Opposite)")
            self.btn_start_rev.setStyleSheet("")

        if self._prev_acq_dirs is not None:
            s_dir, c_dir = self._prev_acq_dirs
            self.sample_state.acq_profile.dir = s_dir
            self.camera_state.acq_profile.dir = c_dir
            self._apply_profiles_to_backends()
            self._prev_acq_dirs = None

        # 現在モードが Step のときだけ Step 用ループを止める
        if (self.sample_state.acq_profile.mode == "Step"
            or self.camera_state.acq_profile.mode == "Step"):
            self._stop_step_test()


    # ---------------- Settings dialog ----------------
    @Slot()
    def _on_settings_clicked(self):
        dlg = StageSettingsDialog(self.sample_state, self.camera_state, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        self.sample_state, self.camera_state = dlg.get_states()

        # UI 更新
        self._update_axis_summary_labels()
        self._update_preset_buttons()
        self._update_groupbox_titles()

        # プロファイル保存
        self._save_prefs()

        # Acq プロファイルを backend に適用
        self._apply_profiles_to_backends()

    def _on_ctl_preset_clicked(self, axis: str, index: int):
        state = self.sample_state if axis == "Sample" else self.camera_state
        presets = state.ctl_presets
        if not (0 <= index < len(presets)):
            return
        state.ctl_profile = presets[index].profile
        self._update_axis_summary_labels()

    # ---------------- Bridge → backend ラッパ ----------------
    def _apply_acq_profile_to_backend(self, axis_state: AxisState,
                                      backend: Optional[IStageBackend],
                                      connected: bool):
        if not (backend and connected):
            return
        p = axis_state.acq_profile
        dir_idx = 0 if p.dir == "F" else 1
        try:
            backend.apply_params(p.v_move, p.acc_move, dir_idx)
        except Exception as e:
            if axis_state.axis_name == "Sample":
                self._set_sample_status(f"[Sample ERROR] apply_params(Acq): {e}")
            else:
                self._set_camera_status(f"[Camera ERROR] apply_params(Acq): {e}")

    def _apply_acq_step_profile_to_backend(
        self,
        axis_state: AxisState,
        backend: Optional[IStageBackend],
        connected: bool,
    ):
        """Acq: Step モード用の step パラメータを backend に渡す"""
        if not (backend and connected):
            return

        p = axis_state.acq_profile
        dir_idx = 0 if p.dir == "F" else 1

        try:
            # Step 用パラメータ（step_mm, v_step, acc_step, dir）を backend に渡す
            if hasattr(backend, "configure_step"):
                backend.configure_step(p.step, p.v_step, p.acc_step, dir_idx)
            else:
                # 古い backend 向けフォールバック
                backend.apply_params(p.v_step, p.acc_step, dir_idx)
        except Exception as e:
            if axis_state.axis_name == "Sample":
                self._set_sample_status(f"[Sample ERROR] apply_params(Acq Step): {e}")
            else:
                self._set_camera_status(f"[Camera ERROR] apply_params(Acq Step): {e}")



    def _apply_profiles_to_backends(self):
        self._apply_acq_profile_to_backend(self.sample_state, self.backend_sample, self._connected_sample)
        self._apply_acq_profile_to_backend(self.camera_state, self.backend_camera, self._connected_camera)

    @Slot()
    def _on_bridge_stage_start(self):
        """
        CameraPane → StageBridge → StagePanel の録画用スタート。

        ・Move 録画: CameraPane が sig_stage_start を emit
            → ここで「Acq Move プロファイル」を backend に適用して
            start_continuous() を呼ぶだけ。

        ・Step 録画: CameraPane は sig_stage_start を使わず、
            フレームごとに sig_step_once() を emit する。
            → その場合、このスロットは呼ばれない。
        """
        print("[StagePanel] _on_bridge_stage_start: received stage_start")

        if not self._connected:
            return

        # 録画の Move 用として「Acq の Move 部分」だけを backend に適用
        self._apply_profiles_to_backends()

        try:
            if self.backend_sample and self._connected_sample:
                self.backend_sample.start_continuous()
            if self.backend_camera and self._connected_camera:
                self.backend_camera.start_continuous()
        except Exception as e:
            self._set_stage_status(f"ERROR: start_continuous: {e}")


            
    """
    @Slot()
    def _on_bridge_stage_stop_only(self):
        if not self._connected:
            return
        try:
            if self.backend_sample and self._connected_sample:
                self.backend_sample.stop_only()
            if self.backend_camera and self._connected_camera:
                self.backend_camera.stop_only()
        except Exception as e:
            self._set_stage_status(f"ERROR: stop_only: {e}")

    @Slot(str)
    def _on_bridge_stage_stop_return(self, direction: str):
        if not self._connected:
            return
        # UI 状態はここでリセット
        self._on_external_stop()

        try:
            # Sample 軸
            if self.backend_sample and self._connected_sample:
                backend = self.backend_sample
                # 新 API を優先、なければ旧 API を使う
                if hasattr(backend, "start_return"):
                    backend.start_return(direction)
                else:
                    backend.start_home_return_async(direction)

            # Camera 軸
            if self.backend_camera and self._connected_camera:
                backend = self.backend_camera
                if hasattr(backend, "start_return"):
                    backend.start_return(direction)
                else:
                    backend.start_home_return_async(direction)

        except Exception as e:
            self._set_stage_status(f"ERROR: start_return: {e}")

    
    @Slot(str, int)
    def _on_bridge_stage_stop(self, direction: str, mode: int):

        print(f"[StagePanel] _on_bridge_stage_stop: direction={direction!r}, mode={mode}")  # デバッグ用

        if not self._connected:
            return

        # まず UI 側（ボタン状態や Step test タイマーなど）を一括リセット
        self._on_external_stop()

        # 不正値が来ても STOP_ONLY 扱いにしておく
        try:
            mode_enum = StageStopMode(int(mode))
        except ValueError:
            mode_enum = StageStopMode.STOP_ONLY

        # STOP_AND_RETURN のときに direction が空なら、後ろで困らないように一応ガード
        if mode_enum is StageStopMode.STOP_AND_RETURN and not direction:
            direction = ""

        try:
            # Sample 軸
            if self.backend_sample and self._connected_sample:
                backend = self.backend_sample
                if mode_enum is StageStopMode.STOP_ONLY:
                    backend.stop_only()
                else:
                    if hasattr(backend, "start_return"):
                        backend.start_return(direction)
                    else:
                        backend.start_home_return_async(direction)

            # Camera 軸
            if self.backend_camera and self._connected_camera:
                backend = self.backend_camera
                if mode_enum is StageStopMode.STOP_ONLY:
                    backend.stop_only()
                else:
                    if hasattr(backend, "start_return"):
                        backend.start_return(direction)
                    else:
                        backend.start_home_return_async(direction)

        except Exception as e:
            self._set_stage_status(f"ERROR: stage stop({mode_enum.name}): {e}")
    """
    @Slot(int, int)
    def _on_bridge_stage_stop(self, link_mode: int, stop_mode: int):
        print(f"[StagePanel] _on_bridge_stage_stop: link_mode={link_mode}, stop_mode={stop_mode}")

        if not self._connected:
            return

        if self._test_running or self._rev_running:
            if self.backend_sample:
                self.backend_sample.stop_only()
            if self.backend_camera:
                self.backend_camera.stop_only()
            return

        self._on_external_stop()  # UI リセットだけ

        try:
            link_mode_enum = StageLinkMode(int(link_mode))
        except ValueError:
            link_mode_enum = StageLinkMode.STAGE_OFF

        try:
            stop_mode_enum = StageStopMode(int(stop_mode))
        except ValueError:
            stop_mode_enum = StageStopMode.STOP_ONLY

        try:
            # ---- Sample 軸 ----
            if self.backend_sample and self._connected_sample:
                backend = self.backend_sample

                if link_mode_enum == StageLinkMode.MOVE_CONTINUOUS:
                    # 連続モードのときだけ stop_only を使う
                    backend.stop_only()
                    if stop_mode_enum == StageStopMode.STOP_AND_RETURN:
                        s_dir = getattr(self.sample_state.acq_profile, "dir", "") or ""
                        if hasattr(backend, "start_return"):
                            backend.start_return(s_dir)
                        elif hasattr(backend, "start_home_return_async"):
                            backend.start_home_return_async(s_dir)
                        print("[StagePanel] sample: MOVE_CONTINUOUS stop + return")
                    else:
                        print("[StagePanel] sample: MOVE_CONTINUOUS stop only")

                elif link_mode_enum == StageLinkMode.STEP:
                    # STEP では stop_only は絶対に呼ばない
                    if stop_mode_enum == StageStopMode.STOP_AND_RETURN:
                        s_dir = getattr(self.sample_state.acq_profile, "dir", "") or ""
                        if hasattr(backend, "start_return"):
                            backend.start_return(s_dir)
                        elif hasattr(backend, "start_home_return_async"):
                            backend.start_home_return_async(s_dir)
                        print("[StagePanel] sample: STEP return only")
                    else:
                        # STOP_ONLY なら何もしない（位置はそのまま）
                        print("[StagePanel] sample: STEP no auto-return (no stop_only)")

            # ---- Camera 軸 ----
            if self.backend_camera and self._connected_camera:
                backend = self.backend_camera

                if link_mode_enum == StageLinkMode.MOVE_CONTINUOUS:
                    backend.stop_only()
                    if stop_mode_enum == StageStopMode.STOP_AND_RETURN:
                        c_dir = getattr(self.camera_state.acq_profile, "dir", "") or ""
                        if hasattr(backend, "start_return"):
                            backend.start_return(c_dir)
                        elif hasattr(backend, "start_home_return_async"):
                            backend.start_home_return_async(c_dir)
                        print("[StagePanel] camera: MOVE_CONTINUOUS stop + return")
                    else:
                        print("[StagePanel] camera: MOVE_CONTINUOUS stop only")

                elif link_mode_enum == StageLinkMode.STEP:
                    if stop_mode_enum == StageStopMode.STOP_AND_RETURN:
                        c_dir = getattr(self.camera_state.acq_profile, "dir", "") or ""
                        if hasattr(backend, "start_return"):
                            backend.start_return(c_dir)
                        elif hasattr(backend, "start_home_return_async"):
                            backend.start_home_return_async(c_dir)
                        print("[StagePanel] camera: STEP return only")
                    else:
                        print("[StagePanel] camera: STEP no auto-return (no stop_only)")

        except Exception as e:
            self._set_stage_status(f"ERROR: stage stop({link_mode_enum.name}): {e}")


    @Slot(bool)
    def _on_recording_state_changed(self, recording: bool):
        self._recording_active = recording

        if self._test_running:
            self.btn_startstop.setStyleSheet(self._style_running_red)
        else:
            if recording:
                self.btn_startstop.setStyleSheet(
                    "QPushButton { border: 2px solid #b7f3b0; padding: 2px 8px; "
                    "background-color: #b7f3b0; }"
                )
            else:
                self.btn_startstop.setStyleSheet("")

    # ---------------- 製品選択など ----------------
    @Slot(int, list)
    def _on_products_listed(self, dev_index: int, products: list):
        """
        現在は device 選択を backend 側のダイアログで完結させているため、
        StagePanel 側では対応製品リストを受け取っても何もしない。
        """
        return

    # ---------------- 設定保存／ロード ----------------
    def _load_prefs(self):
        settings = self.settings
        try:
            # ---- 軸プロファイルの復元（既存） ----
            raw_s = settings.value("StageProfile/Sample", "", str)
            if raw_s:
                d = json.loads(raw_s)
                self.sample_state = axis_state_from_dict("Sample", d, self.sample_state)

            raw_c = settings.value("StageProfile/Camera", "", str)
            if raw_c:
                d = json.loads(raw_c)
                self.camera_state = axis_state_from_dict("Camera", d, self.camera_state)

            # ---- backend 選択の復元（追加）----
            sample_key = settings.value("StageBackendKey/Sample", "", str)
            if sample_key:
                idx = self.cmb_backend_sample.findData(sample_key)
                if idx >= 0:
                    self.cmb_backend_sample.setCurrentIndex(idx)

            camera_key = settings.value("StageBackendKey/Camera", "", str)
            if camera_key:
                idx = self.cmb_backend_camera.findData(camera_key)
                if idx >= 0:
                    self.cmb_backend_camera.setCurrentIndex(idx)

        except Exception as e:
            print(f"[StagePanel] _load_prefs error: {e}")


    def _save_prefs(self):
        settings = self.settings
        try:
            # ---- 軸プロファイルの保存（既存）----
            settings.setValue(
                "StageProfile/Sample",
                json.dumps(axis_state_to_dict(self.sample_state)),
            )
            settings.setValue(
                "StageProfile/Camera",
                json.dumps(axis_state_to_dict(self.camera_state)),
            )

            # ---- backend 選択の保存（追加）----
            settings.setValue("StageBackendKey/Sample", self._current_backend_key_sample or "")
            settings.setValue("StageBackendKey/Camera", self._current_backend_key_camera or "")

            settings.sync()
        except Exception as e:
            print(f"[StagePanel] _save_prefs error: {e}")


    # ---------------- シャットダウン ----------------
    def on_shutdown(self):
        for b in (self.backend_sample, self.backend_camera):
            if b is None:
                continue
            try:
                b.shutdown()
            except Exception:
                pass

    # ---------------- Filter 用 helper ----------------
    def get_camera_device(self):
        """
        FilterController に渡すための「Camera 軸の stage device」を返す。
        1 軸 backend では camera 側 backend の device をそのまま返す。
        """
        if self.backend_camera is None:
            return None
        return getattr(self.backend_camera, "device", None)
    
    def _apply_ctl_profile_to_backend(self, axis_state: AxisState,
                                      backend: Optional[IStageBackend],
                                      connected: bool):
        """Ctl: Move（↑↑ / ↓↓ / jog）用のパラメータを反映"""
        if not (backend and connected):
            return
        p = axis_state.ctl_profile
        dir_idx = 0 if p.dir == "F" else 1
        try:
            backend.apply_params(p.v_move, p.acc_move, dir_idx)
        except Exception as e:
            if axis_state.axis_name == "Sample":
                self._set_sample_status(f"[Sample ERROR] apply_params(Ctl Move): {e}")
            else:
                self._set_camera_status(f"[Camera ERROR] apply_params(Ctl Move): {e}")


    def _apply_ctl_step_profile_to_backend(
        self,
        axis_state: AxisState,
        backend: Optional[IStageBackend],
        connected: bool,
    ):
        """Ctl: Step（↑ / ↓）用のパラメータを反映"""
        if not (backend and connected):
            return

        p = axis_state.ctl_profile
        dir_idx = 0 if p.dir == "F" else 1

        try:
            # 1) Step 用パラメータ（step_mm, v_step, acc_step, dir）を backend に渡す
            if hasattr(backend, "configure_step"):
                backend.configure_step(p.step, p.v_step, p.acc_step, dir_idx)
            else:
                # 古い backend 向けのフォールバック（今まで通り）
                backend.apply_params(p.v_step, p.acc_step, dir_idx)
        except Exception as e:
            if axis_state.axis_name == "Sample":
                self._set_sample_status(f"[Sample ERROR] apply_params(Ctl Step): {e}")
            else:
                self._set_camera_status(f"[Camera ERROR] apply_params(Ctl Step): {e}")



    def _format_acq_summary(self, prof: StageProfile) -> str:
        """Acq: 選択中 mode のみ表示"""
        if prof.mode == "Move":
            return f"Acq: Move v={prof.v_move:.3f} acc={prof.acc_move:.1f} {prof.dir}"
        else:
            return (
                f"Acq: Step v={prof.v_step:.3f} acc={prof.acc_step:.1f} s={prof.step:.4f} {prof.dir}"
            )

    def _format_ctl_summary(self, prof: StageProfile) -> str:
        """Ctl: Move / Step を 2 行に分割して表示（横幅を抑える）"""
        line1 = f"Ctl Move: v={prof.v_move:.3f} acc={prof.acc_move:.1f}"    # {prof.dir}"
        line2 = (f"Ctl Step: v={prof.v_step:.3f} acc={prof.acc_step:.1f} s={prof.step:.4f}")
        return line1 + "\n" + line2


    @Slot()
    def _on_bridge_step_once(self):
        """
        録画ループ（CaptureWorker 等）から呼ばれる「1 ステップだけ」動作。
        Acq Profile が Step モードの両軸に対して _do_acq_step_once() を実行。
        """
        if not self._connected:
            return
        try:
            self._do_acq_step_once(reverse=False)   # ← 常に False 固定
        except Exception as e:
            self._set_stage_status(f"ERROR: step_once: {e}")




