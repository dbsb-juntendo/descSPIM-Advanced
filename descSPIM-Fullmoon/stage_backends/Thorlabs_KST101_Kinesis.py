# stage_backends/Thorlabs_KST101.py
# -*- coding: utf-8 -*-

from .stage_backend_base import IStageBackend, StepDirection
from timing_logger import TimingLogger

import os
import time
from pathlib import Path
from contextlib import contextmanager

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Slot, QSettings

#import clr
#from System import Decimal as SysDecimal
#from System.Globalization import CultureInfo
from dataclasses import dataclass, field


# ---- 設定用データクラス ---------------------------------------------
@dataclass
class MoveParams:
    """連続移動（move/jog/return の基準）用パラメータ."""
    v_mm_s: float = 0.04
    a_mm_s2: float = 1.5
    dir_index: int = 0  # 0: UI "Forward"(＋), 1: "Reverse"(−)


@dataclass
class StepParams:
    """単ステップ（step）用パラメータ."""
    step_mm: float = 0.005
    v_mm_s: float = 0.2
    a_mm_s2: float = 1.5


@dataclass
class StageAxisConfig:
    """1 軸分の設定をまとめたコンテナ."""
    move: MoveParams = field(default_factory=MoveParams)
    step: StepParams = field(default_factory=StepParams)



# TODO:これを遅延インポートにする
# ---- Kinesis (.NET) 用設定 ----
KINESIS_ROOT = r"C:\Program Files\Thorlabs\Kinesis"
KINESIS_LIBDIR = KINESIS_ROOT  # DLL がここにある前提

# DLL ディレクトリが存在する場合のみ追加（無いと FileNotFoundError になる）
if os.path.isdir(KINESIS_LIBDIR):
    try:
        os.add_dll_directory(KINESIS_LIBDIR)
    except Exception:
        # 古い Python / Windows の場合は PATH にある前提
        pass
else:
    print(f"[ThorlabsKST101Backend] warning: KINESIS_LIBDIR not found: {KINESIS_LIBDIR}")

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


def _mkdec(x):  # -> SysDecimal:
    """Decimal.Parse + InvariantCulture で Real Units(mm 等) を渡す."""
    return SysDecimal.Parse(str(x), CultureInfo.InvariantCulture)


def ensure_kinesis_loaded():
    """
    Kinesis の .NET DLL をプロセス全体で一度だけ読み込む。
    複数 backend インスタンスから呼ばれても安全。
    """
    global _KINESIS_LOADED
    global DeviceManagerCLI, KCubeStepper, VelocityParameters, MotorDirection, SysDecimal, CultureInfo

    if _KINESIS_LOADED:
        return
    
    import clr
    from System import Decimal as _SysDecimal
    from System.Globalization import CultureInfo as _CultureInfo
    SysDecimal = _SysDecimal
    CultureInfo = _CultureInfo

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

    # VelocityParameters と MotorDirection を個別に import
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



class ThorlabsKST101Backend(IStageBackend):
    """
    Thorlabs KST101 + ZFS25B を 1 軸として扱う Kinesis backend。
    StagePanel からは「1 軸」として見える。
    """

    # Motion 用 worker へのリクエストシグナル
    req_home = QtCore.Signal()
    req_go_start = QtCore.Signal()
    req_start_continuous = QtCore.Signal()
    req_stop_only = QtCore.Signal()
    req_start_jog = QtCore.Signal(int)   # direction_index (0=Forward, 1=Reverse)
    req_stop_jog = QtCore.Signal()
    # StepDirection は IntEnum なので Signal(int) で値を渡す
    req_step = QtCore.Signal(int)        # StepDirection.value (0=FORWARD, 1=REVERSE)
    req_return = QtCore.Signal()

    SETTINGS_GROUP_BASE = "StageBackend/Thorlabs_KST101"

    def __init__(self, timing_logger: TimingLogger | None, parent=None):
        super().__init__(timing_logger=timing_logger, parent=parent)

        # 設定モデル
        self._config = StageAxisConfig()

        self.serial: str = ""
        self.product_code: str = "ZFS25B"        # KDC101 互換のためだけに残す（Kinesis では特に使用しない）

        self.device = None  # type: ignore[assignment]        # Kinesis デバイスハンドル
        self._start_mm: float | None = None

        # Move 用パラメータ
        self._move_direction = None
        self._v_mm_s = self._config.move.v_mm_s
        self._a_mm_s2 = self._config.move.a_mm_s2
        self._jog_active = False

        # Step 用パラメータ
        self._step_mm = self._config.step.step_mm
        self._step_v_mm_s = self._config.step.v_mm_s
        self._step_a_mm_s2 = self._config.step.a_mm_s2

        self._returning = False
        # 連続移動状態フラグ
        self._continuous_moving: bool = False
        self._connected: bool = False

        # ---- Motion worker / thread 設定（device を触るのはここ経由）----
        self._motion_thread: QtCore.QThread | None = QtCore.QThread(self)
        self._motion_worker = _MotionWorker(self)
        self._motion_worker.moveToThread(self._motion_thread)

        # リクエストシグナルと worker スロットの接続（QueuedConnection）
        self.req_home.connect(self._motion_worker.do_home, QtCore.Qt.QueuedConnection)
        self.req_go_start.connect(self._motion_worker.do_go_to_start_position, QtCore.Qt.QueuedConnection)
        self.req_start_continuous.connect(self._motion_worker.do_start_continuous, QtCore.Qt.QueuedConnection)
        self.req_stop_only.connect(self._motion_worker.do_stop_only, QtCore.Qt.QueuedConnection)
        self.req_start_jog.connect(self._motion_worker.do_start_jog, QtCore.Qt.QueuedConnection)
        self.req_stop_jog.connect(self._motion_worker.do_stop_jog, QtCore.Qt.QueuedConnection)
        self.req_step.connect(self._motion_worker.do_step, QtCore.Qt.QueuedConnection)
        self.req_return.connect(self._motion_worker.do_return, QtCore.Qt.QueuedConnection)

        self._motion_thread.start()

    # ---- settings ヘルパ ---------------------------------------------
    def _settings_group(self) -> str:
        """現在の axis_name に基づく settings グループ名を返す."""
        axis = getattr(self, "axis_name", "Single")
        return f"{self.SETTINGS_GROUP_BASE}/{axis}"

    def _load_settings(self) -> None:
        """
        QSettings から serial / product_code / move / step の設定を読み込んで
        backend 内部のフィールドに反映する。
        """
        settings = QSettings("LabSuite", "StageControl")
        group = self._settings_group()

        settings.beginGroup(group)

        # serial / product_code
        serial_val = settings.value("serial", None, str)
        if serial_val is not None:
            self.serial = serial_val

        product_val = settings.value("product_code", None, str)
        if product_val is not None:
            self.product_code = product_val

        # move
        mv = self._config.move
        v_val = settings.value("move_v_mm_s", None)
        if v_val is not None:
            try:
                mv.v_mm_s = float(v_val)
            except (TypeError, ValueError):
                pass

        a_val = settings.value("move_a_mm_s2", None)
        if a_val is not None:
            try:
                mv.a_mm_s2 = float(a_val)
            except (TypeError, ValueError):
                pass

        dir_val = settings.value("move_dir_index", None)
        if dir_val is not None:
            try:
                mv.dir_index = int(dir_val)
            except (TypeError, ValueError):
                pass

        # backend 内キャッシュに反映
        self._v_mm_s = mv.v_mm_s
        self._a_mm_s2 = mv.a_mm_s2

        # step
        st = self._config.step
        step_mm_val = settings.value("step_mm", None)
        if step_mm_val is not None:
            try:
                st.step_mm = float(step_mm_val)
            except (TypeError, ValueError):
                pass

        step_v_val = settings.value("step_v_mm_s", None)
        if step_v_val is not None:
            try:
                st.v_mm_s = float(step_v_val)
            except (TypeError, ValueError):
                pass

        step_a_val = settings.value("step_a_mm_s2", None)
        if step_a_val is not None:
            try:
                st.a_mm_s2 = float(step_a_val)
            except (TypeError, ValueError):
                pass

        # backend 内キャッシュに反映
        self._step_mm = st.step_mm
        self._step_v_mm_s = st.v_mm_s
        self._step_a_mm_s2 = st.a_mm_s2

        settings.endGroup()

    def _save_settings(self) -> None:
        """
        現在の serial / product_code / move / step の設定を QSettings に保存する。
        """
        settings = QSettings("LabSuite", "StageControl")
        group = self._settings_group()

        settings.beginGroup(group)

        settings.setValue("serial", self.serial)
        settings.setValue("product_code", self.product_code)

        mv = self._config.move
        settings.setValue("move_v_mm_s", mv.v_mm_s)
        settings.setValue("move_a_mm_s2", mv.a_mm_s2)
        settings.setValue("move_dir_index", mv.dir_index)

        st = self._config.step
        settings.setValue("step_mm", st.step_mm)
        settings.setValue("step_v_mm_s", st.v_mm_s)
        settings.setValue("step_a_mm_s2", st.a_mm_s2)

        settings.endGroup()
        settings.sync()


    # KST101には必要ない？
    def _update_move_direction_from_dir_index(self, direction_value: int) -> None:
        # UI の direction_value (0/1) から KST101 API 用 MoveDirection を更新する。
        # 向きが逆なら、ここを修正する
        if direction_value == 0:
            self._move_direction = MotorDirection.Forward
        else:
            self._move_direction = MotorDirection.Backward



    def _apply_move_params_to_device(self) -> None:
        """
        現在の move パラメータを実機に反映（set_velocity_params）する。
        """
        if not self._connected or self.device is None:
            self.sig_status.emit("no device")
            return

        try:
            vp = VelocityParameters()
            vp.Acceleration = _mkdec(self._a_mm_s2)
            vp.MaxVelocity = _mkdec(self._v_mm_s)
            self.device.SetVelocityParams(vp)
            self.sig_status.emit("movie params applied.")
        except Exception as e:
            self.sig_error.emit(f"apply_move_params: {e}")


    # ---- 設定ダイアログ ----
    def show_setup_dialog(self, parent=None) -> bool:
        """
        KST101 用設定ダイアログ:
        1) Serial を入力 → 接続を試みる

        Kinesis 側で ZFS25B の設定を済ませてある前提。
        """
        settings = QSettings("LabSuite", "StageControl")

        axis = getattr(self, "axis_name", "Single")
        group = f"{self.SETTINGS_GROUP_BASE}/{axis}"

        settings.beginGroup(group)
        serial_default = settings.value("serial", self.serial, str)
        settings.endGroup()

        dlg = QtWidgets.QDialog(parent)
        dlg.setWindowTitle("Thorlabs KST101 setup (Serial)")
        layout = QtWidgets.QFormLayout(dlg)

        ed_serial = QtWidgets.QLineEdit()
        ed_serial.setPlaceholderText("2600xxxx")
        ed_serial.setText(serial_default or "")
        layout.addRow("Serial:", ed_serial)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dlg,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addRow(buttons)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False

        serial = ed_serial.text().strip()
        if not serial:
            self.sig_error.emit("serial is required")
            return False

        self.serial = serial

        settings.beginGroup(group)
        settings.setValue("serial", self.serial)
        settings.endGroup()
        settings.sync()

        # 接続を試みる
        self.connect_device()
        return bool(self._connected and self.device is not None)

    # ---- 実機から現在位置(mm) を読み出して _current_mm を同期 ----
    def _update_current_from_device(self):
        if not self._connected or self.device is None:
            return
        try:
            self._current_mm = self.device.Position
        except Exception as e:
            # 位置取得に失敗しても致命傷にはしない
            self.sig_status.emit(f"warning: failed to read current position: {e}")

    # ---------------- IStageBackend API 実装 ----------------
    @Slot()
    def connect_device(self):
        print(
            f"[ThorlabsKST101Backend] axis={getattr(self, 'axis_name', 'N/A')} "
            f"connect_device() serial={self.serial!r}"
        )
        try:
            if not self.serial:
                raise ValueError("serial not set")

            print("[KST101] ensure_kinesis_loaded() ...")
            ensure_kinesis_loaded()
            print("[KST101] ensure_kinesis_loaded() done")

            last_err = None
            self._connected = False
            self.device = None

            # ちょっとした不安定さに対してリトライ
            for i in range(5):
                try:
                    print(f"[KST101] BuildDeviceList (try {i+1}) ...")
                    DeviceManagerCLI.BuildDeviceList()
                    print("[KST101] DeviceManagerCLI.BuildDeviceList() done")

                    print("[KST101] KCubeStepper.CreateKCubeStepper(...) ...")
                    dev = KCubeStepper.CreateKCubeStepper(self.serial)
                    print("[KST101] KCubeStepper.CreateKCubeStepper(...) done")

                    if dev is None:
                        raise RuntimeError(f"KCubeStepper.CreateKCubeStepper({self.serial}) returned None")

                    print("[KST101] device.Connect(...) ...")
                    dev.Connect(self.serial)
                    print("[KST101] device.Connect(...) done")

                    try:
                        dev.WaitForSettingsInitialized(5000)
                    except Exception:
                        pass

                    time.sleep(0.2)
                    print("[KST101] StartPolling(250) ...")
                    dev.StartPolling(250)
                    print("[KST101] StartPolling(250) done")

                    time.sleep(0.2)
                    print("[KST101] EnableDevice() ...")
                    dev.EnableDevice()
                    print("[KST101] EnableDevice() done")

                    time.sleep(0.3)
                    print("[KST101] LoadMotorConfiguration(...) ...")
                    try:
                        # シリアルに紐づく設定ファイルがあれば使う
                        dev.LoadMotorConfiguration(self.serial)
                    except Exception:
                        # 無くてもそのまま続行
                        pass
                    print("[KST101] LoadMotorConfiguration(...) done")

                    self.device = dev
                    self._connected = True
                    break

                except Exception as e_try:
                    last_err = e_try
                    print(f"[KST101] connect attempt {i+1} failed: {e_try}")
                    time.sleep(1.0)

            if not self._connected or self.device is None:
                raise RuntimeError(f"failed to connect to KST101 ({self.serial}): {last_err}")

            print("[KST101] _update_current_from_device() ...")
            self._update_current_from_device()
            print("[KST101] _update_current_from_device() done")

            try:
                print("[KST101] GetDeviceInfo() ...")
                dev_info = self.device.GetDeviceInfo()
                print(f"[KST101] GetDeviceInfo() done: {dev_info.Description}")
                self.sig_status.emit(f"{dev_info.Description}")
            except Exception:
                pass

            self.sig_connected.emit(True)
            self.sig_status.emit(f"connected: {self.serial}")
            print("[KST101] connect_device() finished normally")

        except Exception as e:
            print(f"[KST101] connect_device() exception: {e!r}")
            self.sig_error.emit(f"connect_device: {e}")
            self._connected = False
            self.device = None
            self.sig_connected.emit(False)

    @Slot()
    def shutdown(self):
        try:
            if self.device is not None:
                try:
                    # ポーリング停止 → 切断
                    self.device.StopPolling()
                except Exception:
                    pass
                try:
                    self.device.Disconnect()
                except Exception:
                    pass
                self.device = None

            if self._motion_thread is not None:
                self._motion_thread.quit()
                self._motion_thread.wait()
                self._motion_thread = None

            self._connected = False
            self.sig_connected.emit(False)
            self.sig_status.emit("disconnected.")
        except Exception as e:
            self.sig_error.emit(f"shutdown: {e}")

    @Slot(str)
    def set_product(self, product_code: str):
        """
        XA 版との互換のためだけに残しているが、
        Kinesis / KST101 では特に何もしない。
        """
        self.product_code = product_code
        self.sig_status.emit(f"product (ignored on KST101): {product_code}")

    # ---- move 用パラメータ適用 ---------------------------------------
    @Slot(float, float, int)
    def apply_move_params(self, v_mm_s: float, a_mm_s2: float, dir_index: int):
        """
        連続移動用（move/jog/return 基準）のパラメータを更新して実機に適用する。
        """
        mv = self._config.move
        mv.v_mm_s = float(v_mm_s)
        mv.a_mm_s2 = float(a_mm_s2)
        mv.dir_index = int(dir_index)

        # backend 内キャッシュを更新
        self._v_mm_s = mv.v_mm_s
        self._a_mm_s2 = mv.a_mm_s2
        self._update_move_direction_from_dir_index(mv.dir_index)

        # 設定を保存
        self._save_settings()

        # 実機に反映
        self._apply_move_params_to_device()


    # ---- step 用パラメータ適用 ---------------------------------------
    @Slot(float, float, float, int)
    def apply_step_params(self, step_mm: float, v_mm_s: float, a_mm_s2: float, dir_index: int):
        """
        Step 移動用のパラメータを更新して保存する。
        """
        st = self._config.step
        st.step_mm = float(step_mm)
        st.v_mm_s = float(v_mm_s)
        st.a_mm_s2 = float(a_mm_s2)

        # backend 内キャッシュを更新
        self._step_mm = st.step_mm
        self._step_v_mm_s = st.v_mm_s
        self._step_a_mm_s2 = st.a_mm_s2

        # 必要なら Step 用の「向き」も move 設定に反映
        self._config.move.dir_index = int(dir_index)
        self._update_move_direction_from_dir_index(self._config.move.dir_index)

        self._save_settings()


    @Slot()
    def home(self):
        if not self._connected or self.device is None:
            self.sig_error.emit("home: not connected")
            return
        self.req_home.emit()

    @Slot()
    def register_start_point(self):
        """
        現在位置を開始位置として登録。
        可能なら Kinesis から現在位置を読み直してから _current_mm を使う。
        """
        if not self._connected or self.device is None:
            self.sig_error.emit("register_start_point: not connected")
            return
        try:
            # 実機位置で同期してから開始位置登録
            self._update_current_from_device()

            self._start_mm = float(self._current_mm)
            self.sig_status.emit(f"Start pos registered: {self._start_mm:.6f} mm")
            self.sig_startpos_updated.emit(self._start_mm)
        except Exception as e:
            self.sig_error.emit(f"register_start_point: {e}")

    @Slot()
    def go_to_start_position(self):
        if not self._connected or self.device is None:
            self.sig_error.emit("go_to_start_position: not connected")
            return
        if self._start_mm is None:
            self.sig_error.emit("go_to_start_position: start position not registered")
            return
        self.req_go_start.emit()

    @Slot(int)
    def start_continuous(self):
        if not self._connected or self.device is None:
            self.sig_error.emit("start_continuous: not connected")
            return
        self.req_start_continuous.emit()


    @Slot()
    def stop_only(self):
        if not self._connected or self.device is None:
            self.sig_error.emit("stop_only: not connected")
            return
        self.req_stop_only.emit()

    @Slot(int)
    def start_jog(self, direction_index: int):
        if not self._connected or self.device is None:
            self.sig_error.emit("start: not connected")
            return
        self.req_start_jog.emit(direction_index)

    @Slot()
    def stop_jog(self):
        if not self._connected or self.device is None:
            self.sig_error.emit("stop: not connected")
            return
        self.req_stop_jog.emit()

    def step(self, direction: StepDirection):
        """
        direction: StepDirection.FORWARD (= 0) / StepDirection.REVERSE (= 1)
        Step size / velocity / acceleration は apply_step_params() で事前に設定された値を使う想定。
        """
        if not self._connected or self.device is None:
            self.sig_error.emit("step: not connected")
            return

        self.req_step.emit(int(direction))

    @Slot()
    def start_return(self):
        """
        録画終了時などに「開始位置へ戻る」ための非同期処理を開始する。
        """
        if not self._connected or self.device is None:
            self.sig_error.emit("stop return: not connected")
            return
        if self._returning:
            self.sig_status.emit("already returning...")
            return

        self._returning = True
        self.req_return.emit()


class _MotionWorker(QtCore.QObject):
    """
    実際に KST101 (KCubeStepper) を叩くスレッド用 worker。
    """

    def __init__(self, backend: ThorlabsKST101Backend):
        super().__init__()
        self._b = backend

    @Slot()
    def do_home(self):
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("home: not connected")
            return
        try:
            c.sig_status.emit("homing...")
            c.device.Home(60000)              # Kinesis サンプルと同じ Home(timeout:60s) パターン
            c._current_mm = 0.0   # ホーム位置を 0 mm とみなす
            c.sig_status.emit("homed.")
        except Exception as e:
            c.sig_error.emit(f"home: {e}")

    @Slot()
    def do_go_to_start_position(self):
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("go_to_start_position: not connected")
            return
        if c._start_mm is None:
            c.sig_error.emit("go_to_start_position: start position not registered")
            return

        prev_v = prev_a = None

        try:
            prev_v = c._v_mm_s
            prev_a = c._a_mm_s2

            RET_V_MM_S = 1.5
            RET_A_MM_S2 = 1.0

            try:            # 速度パラメータを一時的に早めにする
                vp = VelocityParameters()
                vp.Acceleration = _mkdec(RET_A_MM_S2)
                vp.MaxVelocity = _mkdec(RET_V_MM_S)
                c.device.SetVelocityParams(vp)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to set fast goto speed: {ee}")

            c.sig_status.emit("returning to start position...")
            target = _mkdec(c._start_mm)
            c.device.MoveTo(target, 60000)
            c._current_mm = float(c._start_mm)
            c.sig_status.emit("at start position.")

        except Exception as e:
            c.sig_error.emit(f"go_to_start_position: {e}")

        finally:
            try:            # 元の速度に戻す
                if prev_v is not None and c.device is not None:
                    vp = VelocityParameters()
                    vp.Acceleration = _mkdec(prev_a)
                    vp.MaxVelocity = _mkdec(prev_v)
                    c.device.SetVelocityParams(vp)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to restore speed (goto): {ee}")

    @Slot(int)
    def do_start_continuous(self, direction_index: int):
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("start_continuous: not connected")
            return

        if c._continuous_moving:
            c.sig_status.emit("continuous move already running.")
            return

        try:
            if direction_index == 0:
                direction = MotorDirection.Forward
                d_label = "Forward"
            else:
                direction = MotorDirection.Backward
                d_label = "Backward"

            if c.timing:
                c.timing.log_event("CONTINUOUS_BEGIN")

            c.device.MoveContinuous(direction)
            c._continuous_moving = True
            c.sig_status.emit(f"continuous move started ({d_label}).")
        except Exception as e:
            c._continuous_moving = False
            c.sig_error.emit(f"start_continuous: {e}")


    @Slot()
    def do_stop_only(self):
        """
        連続移動（MoveAtVelocity）を停止する。
        """
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("stop_only: not connected")
            return

        try:
            c.device.Stop()
            c._continuous_moving = False

            try:            # 停止後に位置を実機から同期
                c._update_current_from_device()
            except Exception:
                pass

            c.sig_status.emit("continuous move stopped.")
        except Exception as e:
            c._continuous_moving = False
            c.sig_error.emit(f"stop_only: {e}")

    @Slot(int)
    def do_start_jog(self, direction_index: int):
        """
        Jog(↑↑/↓↓)用:
        """
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("start_jog: not connected")
            return

        # すでに連続移動中なら何もしない（必要に応じて仕様に合わせて変更）
        if c._continuous_moving:
            c.sig_status.emit("jog already running.")
            return

        try:
            if direction_index == 0:
                direction = MotorDirection.Forward
                d_label = "Forward"
            else:
                direction = MotorDirection.Backward
                d_label = "Backward"

            c.device.MoveContinuous(direction)
            c._continuous_moving = True
            c.sig_status.emit(
                f"jog started ({d_label}, v={c._v_mm_s:.3f} mm/s, a={c._a_mm_s2:.3f} mm/s^2)."
            )
        except Exception as e:
            c._continuous_moving = False
            c.sig_error.emit(f"start_jog: {e}")

    @Slot()
    def do_stop_jog(self):
        """
        Jog(↑↑/↓↓)連続移動の停止。
        StopProfiled() で停止し、位置を同期する。
        """
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("stop_jog: not connected")
            return

        try:
            if not c._continuous_moving:
                c.sig_status.emit("jog already stopped.")
                return

            if c.timing:
                c.timing.log_event("JOG_STOP_CMD")

            c.device.Stop()
            c._continuous_moving = False

            # 停止後に位置を同期（失敗しても致命的ではないので握りつぶす）
            try:
                c._update_current_from_device()
            except Exception:
                pass

            c.sig_status.emit("jog stopped.")
        except Exception as e:
            c._continuous_moving = False
            c.sig_error.emit(f"stop_jog: {e}")


    @Slot(int)
    def do_step(self, direction_value: int):
        """
        StepDirection に基づいて、_step_mm ぶんだけ MoveRelative で移動する。
        """
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("step: not connected")
            return

        if direction_value == 0:
            direction = MotorDirection.Forward
            d_label = "Forward"
        else:
            direction = MotorDirection.Backward
            d_label = "Backward"

        try:
            step_mm = c._step_mm
            c.device.MoveRelative(direction, step_mm, 60000)
            c.sig_status.emit(f"{d_label}, {step_mm*1000:.1f} um (step)")
        except Exception as e:
            c.sig_error.emit(f"step: {e}")

    @Slot(str)
    def do_return(self):
        """
        録画終了時などに、「開始位置 (_start_mm) へ戻る」処理。
        """
        c = self._b
        prev_v = prev_a = None

        try:
            if not c._connected or c.device is None:
                c.sig_error.emit("stop return: not connected")
                return

            if c.timing:
                c.timing.log_event("STAGE_STOP_CMD")

            c.sig_status.emit("waiting briefly before returning to start position...")
            time.sleep(1)

            prev_v = c._v_mm_s
            prev_a = c._a_mm_s2

            RET_V_MM_S = 1.5
            RET_A_MM_S2 = 1.0

            try:
                vp = VelocityParameters()
                vp.Acceleration = _mkdec(RET_A_MM_S2)
                vp.MaxVelocity = _mkdec(RET_V_MM_S)
                c.device.SetVelocityParams(vp)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to set fast return speed: {ee}")

            if c._start_mm is not None:
                if c.timing:
                    c.timing.log_event("RETURN_BEGIN")
                target = _mkdec(c._start_mm)
                c.device.MoveTo(target, 60000)
                c._current_mm = float(c._start_mm)
                if c.timing:
                    c.timing.log_event("RETURN_DONE")

            c.sig_status.emit("returned to start position.")

        except Exception as e:
            c.sig_error.emit(f"return: {e}")

        finally:
            try:
                if prev_v is not None and c.device is not None:
                    vp = VelocityParameters()
                    vp.Acceleration = _mkdec(prev_a)
                    vp.MaxVelocity = _mkdec(prev_v)
                    c.device.SetVelocityParams(vp)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to restore speed: {ee}")

            c._returning = False


def get_backend_class():
    """StagePanel から呼ばれるファクトリ用フック。"""
    return ThorlabsKST101Backend
