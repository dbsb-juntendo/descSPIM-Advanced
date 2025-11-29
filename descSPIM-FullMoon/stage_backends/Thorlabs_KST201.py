# stage_backends/Thorlabs_KST201.py

# ---------------------------------
# 動作確認ができていない。デバグが必要。
# Not tested. Debugging is necessary.
# ---------------------------------

# -*- coding: utf-8 -*-
from .stage_backend_base import IStageBackend, StepDirection
from timing_logger import TimingLogger

import os, time
from contextlib import contextmanager

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Slot, QSettings

# ---- XA SDK imports ----
from xa_sdk.products.kst201 import KST201
from xa_sdk.shared.tlmc_type_structures import *
from xa_sdk.native_sdks.xa_sdk import XASDK


LIBDIR = r"C:\Program Files\Thorlabs XA\SDK\Native (C, C++)\Libraries\x64"
XAROOT = r"C:\Program Files\Thorlabs XA"
os.add_dll_directory(LIBDIR)

_XA_STARTED = False


def ensure_xa_started():
    """
    XA SDK をプロセス全体で一度だけ startup する。
    複数の backend インスタンスから呼ばれても問題ないようにガード。
    """
    global _XA_STARTED
    if _XA_STARTED:
        return
    with pushd(LIBDIR):
        XASDK.try_load_library(__file__)
    XASDK.startup(XAROOT)
    _XA_STARTED = True


@contextmanager
def pushd(p: str):
    cur = os.getcwd()
    os.chdir(p)
    try:
        yield
    finally:
        os.chdir(cur)


class ThorlabsKST201Backend(IStageBackend):
    """
    Thorlabs KST201 を 1 軸だけ扱う backend。
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
    req_step = QtCore.Signal(int)        # StepDirection.value
    req_return = QtCore.Signal(str)

    SETTINGS_GROUP_BASE = "StageBackend/Thorlabs_KST201"

    FINE_STEP_MM = 0.005      # 旧デフォルト（5 µm)     

    # jog 用
    JOG_V_MM_S = 0.2
    JOG_A_MM_S2 = 1.5

    def __init__(self, timing_logger: TimingLogger | None, parent=None):
        super().__init__(timing_logger=timing_logger, parent=parent)

        self.serial: str = ""
        self.product_code: str = "ZFS25"  # デフォルト（必要に応じて変更）

        self.device: KST201 | None = None
        self._start_mm: float | None = None

        # 連続移動用の現在方向（MoveDirection）
        self._move_direction = TLMC_MoveDirection.Move_Direction_Reverse
        self._v_mm_s = 0.04   # paramチェック
        self._a_mm_s2 = 1.5   # paramチェック
        self._jog_active = False

        # Step 用パラメータ
        self._step_mm = self.FINE_STEP_MM
        self._step_v_mm_s = self.JOG_V_MM_S
        self._step_a_mm_s2 = self.JOG_A_MM_S2

        self._ret_thread: QtCore.QThread | None = None
        self._returning = False

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

    # ---- util ----
    def show_setup_dialog(self, parent=None) -> bool:
        """
        KST201 用設定ダイアログ（2 段階）:
        1) Serial を入力 → 接続を試みる
        2) 接続に成功したら、実機から列挙した product_code（Zxxxx 等）を選択
        両方とも QSettings 経由で保存・復元する。
        """
        settings = QSettings("LabSuite", "StageControl")

        # 軸名 (Sample / Camera)。未設定なら "Single"
        axis = getattr(self, "axis_name", "Single")
        group = f"{self.SETTINGS_GROUP_BASE}/{axis}"

        # --- 1) serial ダイアログ ---
        settings.beginGroup(group)
        serial_default = settings.value("serial", self.serial, str)
        product_default = settings.value("product_code", self.product_code or "Z825", str)
        settings.endGroup()

        dlg1 = QtWidgets.QDialog(parent)
        dlg1.setWindowTitle("Thorlabs KST201 setup (Serial)")
        layout1 = QtWidgets.QFormLayout(dlg1)

        ed_serial = QtWidgets.QLineEdit()
        ed_serial.setPlaceholderText("2625xxxx")
        ed_serial.setText(serial_default)
        layout1.addRow("Serial:", ed_serial)

        buttons1 = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dlg1,
        )
        buttons1.accepted.connect(dlg1.accept)
        buttons1.rejected.connect(dlg1.reject)
        layout1.addRow(buttons1)

        if dlg1.exec() != QtWidgets.QDialog.Accepted:
            return False

        serial = ed_serial.text().strip()
        if not serial:
            self.sig_error.emit("serial is required")
            return False

        # backend に反映
        self.serial = serial

        # serial を保存
        settings.beginGroup(group)
        settings.setValue("serial", self.serial)
        settings.endGroup()
        settings.sync()

        # --- 1') serial が決まったので接続を試みる ---
        self.connect_device()
        if not getattr(self, "_connected", False) or self.device is None:
            return False

        # --- 2) 接続後、実機から対応 device を列挙して選択ダイアログ ---
        try:
            raw = self.device.get_connected_products_supported() or []
            products = self._normalize_products(raw)
        except Exception as ee:
            self.sig_status.emit(f"enumeration warning: {ee}")
            products = [product_default or "Z825"]

        if not products:
            products = [product_default or "Z825"]

        dlg2 = QtWidgets.QDialog(parent)
        dlg2.setWindowTitle("Thorlabs KST201 setup (Device)")
        layout2 = QtWidgets.QFormLayout(dlg2)

        cmb_product = QtWidgets.QComboBox()
        cmb_product.setEditable(True)
        cmb_product.addItems(products)

        if product_default in products:
            cmb_product.setCurrentText(product_default)
        else:
            cmb_product.setCurrentText(products[0])

        layout2.addRow("Device:", cmb_product)

        buttons2 = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dlg2,
        )
        buttons2.accepted.connect(dlg2.accept)
        buttons2.rejected.connect(dlg2.reject)
        layout2.addRow(buttons2)

        if dlg2.exec() != QtWidgets.QDialog.Accepted:
            return True

        product_code = cmb_product.currentText().strip() or products[0]
        self.product_code = product_code

        # デバイスに反映
        self.set_product(product_code)

        # 設定を保存
        settings.beginGroup(group)
        settings.setValue("product_code", self.product_code)
        settings.endGroup()
        settings.sync()

        return True

    def _normalize_products(self, p):
        if isinstance(p, (bytes, bytearray)):
            s = p.decode("utf-8", "ignore")
            return [x.strip() for x in s.split(",") if x.strip()]
        if isinstance(p, str):
            return [x.strip() for x in p.split(",") if x.strip()]
        if isinstance(p, (list, tuple)):
            out = []
            for x in p:
                out.append(
                    (x.decode("utf-8", "ignore") if isinstance(x, (bytes, bytearray)) else str(x)).strip()
                )
            return [x for x in out if x]
        return [str(p)]

    # ---------------- IStageBackend API 実装 ----------------
    @Slot()
    def connect_device(self):
        print(
            f"[ThorlabsKST201Backend] axis={getattr(self, 'axis_name', 'N/A')} "
            f"connect_device() serial={self.serial!r}"
        )
        try:
            if not self.serial:
                raise ValueError("serial not set")

            ensure_xa_started()

            self.device = KST201(self.serial, "", TLMC_OperatingModes.Default)
            self.device.set_enable_state(TLMC_ChannelEnableStates.ChannelEnabled)

            # 製品コード設定
            self.device.set_connected_product(self.product_code)

            # 対応製品列挙
            try:
                raw = self.device.get_connected_products_supported() or []
                self.sig_supported_products.emit(self._normalize_products(raw))
            except Exception as ee:
                self.sig_status.emit(f"enumeration warning: {ee}")

            self._connected = True
            self.sig_connected.emit(True)
            self.sig_status.emit(f"connected: {self.serial}")

        except Exception as e:
            self.sig_error.emit(f"connect_device: {e}")
            self._connected = False
            self.sig_connected.emit(False)

    @Slot()
    def shutdown(self):
        try:
            if self.device is not None:
                try:
                    self.device.disconnect()
                    self.device.close()
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
        self.product_code = product_code
        if not self._connected or self.device is None:
            self.sig_status.emit(f"product set (pending): {product_code}")
            return
        try:
            self.device.set_connected_product(product_code)
            self.sig_status.emit(f"product set: {product_code}")
        except Exception as e:
            self.sig_error.emit(f"set_product: {e}")

    @Slot(float, float, int)
    def apply_params(self, v_mm_s: float, a_mm_s2: float, dir_index: int):
        self._v_mm_s = float(v_mm_s)  # paramチェック
        self._a_mm_s2 = float(a_mm_s2)    # paramチェック

        # StagePane: dir_index == 0 → "Forward"（＋方向に動いてほしい）
        # KDC101 と同様のマッピング（必要ならあとで修正）
        if dir_index == 0:
            self._move_direction = TLMC_MoveDirection.Move_Direction_Reverse
        else:
            self._move_direction = TLMC_MoveDirection.Move_Direction_Forward

        if not self._connected or self.device is None:
            self.sig_status.emit("no device")
            return

        try:
            v_dev = int(
                round(
                    self.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Velocity,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        self._v_mm_s, # paramチェック
                    )
                )
            )
            a_dev = int(
                round(
                    self.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        self._a_mm_s2,    # paramチェック
                    )
                )
            )
            self.device.set_velocity_params(0, a_dev, v_dev)
            self.sig_status.emit("params applied.")
        except Exception as e:
            self.sig_error.emit(f"apply_params: {e}")

    @Slot()
    def home(self):
        if not self._connected or self.device is None:
            self.sig_error.emit("home: not connected")
            return
        self.req_home.emit()

    @Slot()
    def register_start_point(self):
        if not self._connected or self.device is None:
            self.sig_error.emit("register_start_point: not connected")
            return
        try:
            c = self.device.get_position_counter(TLMC_Wait.TLMC_InfiniteWait)
            self._start_mm = self.device.convert_from_device_units_to_physical(
                TLMC_ScaleType.TLMC_ScaleType_Distance, c
            ).converted_value
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

    @Slot()
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
        direction: StepDirection.FORWARD / StepDirection.REVERSE
        Step size / velocity / acceleration は configure_step() で事前に設定。
        """
        if not self._connected or self.device is None:
            self.sig_error.emit("step: not connected")
            return
        self.req_step.emit(int(direction))

    @Slot(str)
    def start_return(self, direction_for_log: str):
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
        self.req_return.emit(direction_for_log)


class _MotionWorker(QtCore.QObject):
    """
    実際に KST201 device を叩くスレッド用 worker。
    ThorlabsKST201Backend からの req_* シグナルだけを入口にして、
    ここからのみ device.* を呼ぶ。
    """

    def __init__(self, backend: ThorlabsKST201Backend):
        super().__init__()
        self._b = backend

    @Slot()
    def do_home(self):
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("home: not connected")
            return
        try:
            if c.timing:
                c.timing.log_event("HOME_SINGLE_BEGIN")
            c.sig_status.emit("homing...")
            c.device.home(TLMC_Wait.TLMC_InfiniteWait)
            if c.timing:
                c.timing.log_event("HOME_SINGLE_DONE")
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

            try:
                v_dev_fast = int(
                    round(
                        c.device.convert_from_physical_to_device(
                            TLMC_ScaleType.TLMC_ScaleType_Velocity,
                            TLMC_Unit.TLMC_Unit_Millimetres,
                            RET_V_MM_S,
                        )
                    )
                )
                a_dev_fast = int(
                    round(
                        c.device.convert_from_physical_to_device(
                            TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                            TLMC_Unit.TLMC_Unit_Millimetres,
                            RET_A_MM_S2,
                        )
                    )
                )
                c.device.set_velocity_params(0, a_dev_fast, v_dev_fast)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to set fast goto speed: {ee}")

            c.sig_status.emit("returning to start position...")
            cnt = int(
                round(
                    c.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Distance,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        c._start_mm,
                    )
                )
            )
            c.device.move_absolute(
                TLMC_MoveModes.MoveMode_Absolute,
                cnt,
                TLMC_Wait.TLMC_InfiniteWait,
            )
            c.sig_status.emit("at start position.")

        except Exception as e:
            c.sig_error.emit(f"go_to_start_position: {e}")

        finally:
            try:
                if prev_v is not None and c.device is not None:
                    v_dev_orig = int(
                        round(
                            c.device.convert_from_physical_to_device(
                                TLMC_ScaleType.TLMC_ScaleType_Velocity,
                                TLMC_Unit.TLMC_Unit_Millimetres,
                                prev_v,
                            )
                        )
                    )
                    a_dev_orig = int(
                        round(
                            c.device.convert_from_physical_to_device(
                                TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                                TLMC_Unit.TLMC_Unit_Millimetres,
                                prev_a,
                            )
                        )
                    )
                    c.device.set_velocity_params(0, a_dev_orig, v_dev_orig)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to restore speed (goto): {ee}")

    @Slot()
    def do_start_continuous(self):
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("start_continuous: not connected")
            return
        try:
            if c.timing:
                c.timing.log_event("STAGE_START")
            c.device.move_continous(c._move_direction, TLMC_Wait.TLMC_NoWait)               
            #c.device.move_continuous(c._move_direction, TLMC_Wait.TLMC_NoWait)     # KST201のラッパーはmove_continous
            c.sig_status.emit("continuous move started.")
        except Exception as e:
            c.sig_error.emit(f"start_continuous: {e}")

    @Slot()
    def do_stop_only(self):
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("stop_only: not connected")
            return
        try:
            if c.timing:
                c.timing.log_event("STAGE_STOP_CMD")
            c.device.stop(
                TLMC_StopModes.StopMode_Profiled, TLMC_Wait.TLMC_InfiniteWait
            )
            c.sig_status.emit("stopped (test).")
        except Exception as e:
            c.sig_error.emit(f"stop_only: {e}")

    @Slot(int)
    def do_start_jog(self, direction_index: int):
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("start: not connected")
            return
        if c._jog_active:
            c.sig_status.emit("already running")
            return

        try:
            v_mm_s = c.JOG_V_MM_S
            a_mm_s2 = c.JOG_A_MM_S2

            v_dev = int(
                round(
                    c.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Velocity,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        v_mm_s,
                    )
                )
            )
            a_dev = int(
                round(
                    c.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        a_mm_s2,
                    )
                )
            )
            c.device.set_velocity_params(0, a_dev, v_dev)

            # StagePane: direction_index == 0 → 「↑↑」= Forward（＋）
            # → API 側では Reverse を呼ぶ（KDC101 と同じ方針）
            if direction_index == 0:
                direction = TLMC_MoveDirection.Move_Direction_Reverse
                direction_label = "Forward"
            else:
                direction = TLMC_MoveDirection.Move_Direction_Forward
                direction_label = "Reverse"

            c.device.move_continuous(direction, TLMC_Wait.TLMC_NoWait)
            c._jog_active = True
            c.sig_status.emit(f"started ({direction_label})")

        except Exception as e:
            c.sig_error.emit(f"start: {e}")

    @Slot()
    def do_stop_jog(self):
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("stop: not connected")
            return
        if not c._jog_active:
            return

        try:
            c.device.stop(
                TLMC_StopModes.StopMode_Profiled, TLMC_Wait.TLMC_InfiniteWait
            )

            v_mm_s = c._v_mm_s
            a_mm_s2 = c._a_mm_s2

            v_dev = int(
                round(
                    c.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Velocity,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        v_mm_s,
                    )
                )
            )
            a_dev = int(
                round(
                    c.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        a_mm_s2,
                    )
                )
            )
            c.device.set_velocity_params(0, a_dev, v_dev)

            c._jog_active = False
            c.sig_status.emit("stopped (params restored)")

        except Exception as e:
            c.sig_error.emit(f"stop: {e}")

    @Slot(int)
    def do_step(self, direction_value: int):
        c = self._b
        if not c._connected or c.device is None:
            c.sig_error.emit("step: not connected")
            return

        try:
            direction = StepDirection(direction_value)

            # --- Step size ---
            step_mm = c._step_mm if c._step_mm > 0 else c.FINE_STEP_MM

            step_counts = int(
                round(
                    c.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Distance,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        step_mm,
                    )
                )
            )
            if step_counts <= 0:
                step_counts = 1

            # --- Step 用の速度・加速度 ---
            v_mm_s = c._step_v_mm_s if c._step_v_mm_s > 0 else c.JOG_V_MM_S
            a_mm_s2 = c._step_a_mm_s2 if c._step_a_mm_s2 > 0 else c.JOG_A_MM_S2

            v_dev = int(
                round(
                    c.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Velocity,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        v_mm_s,
                    )
                )
            )
            a_dev = int(
                round(
                    c.device.convert_from_physical_to_device(
                        TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                        TLMC_Unit.TLMC_Unit_Millimetres,
                        a_mm_s2,
                    )
                )
            )

            jp = c.device.get_move_jog_params(TLMC_Wait.TLMC_InfiniteWait)

            # ★ KST201 ラッパのシグネチャに合わせて、引数を 4 つにしている点だけ KDC 版と異なる
            c.device.set_move_jog_params(
                step_counts,
                jp.min_velocity,
                v_dev,
                a_dev,
            )

            # 方向は StepDirection から決める
            if direction is StepDirection.FORWARD:
                d = TLMC_MoveDirection.Move_Direction_Reverse
                d_label = "Forward"
            else:
                d = TLMC_MoveDirection.Move_Direction_Forward
                d_label = "Reverse"

            c.device.move_jog(d, TLMC_Wait.TLMC_InfiniteWait)
            c.sig_status.emit(f"{d_label} {step_mm*1000:.1f} um (step)")

        except Exception as e:
            c.sig_error.emit(f"step: {e}")

    @Slot(str)
    def do_return(self, direction_for_log: str):
        """
        録画終了時などに「開始位置へ戻る」処理。
        """
        c = self._b
        prev_v = prev_a = None

        try:
            if not c._connected or c.device is None:
                c.sig_error.emit("stop return: not connected")
                if direction_for_log and c.timing:
                    c.timing.flush_to_csv(direction_for_log)
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
                v_dev_fast = int(
                    round(
                        c.device.convert_from_physical_to_device(
                            TLMC_ScaleType.TLMC_ScaleType_Velocity,
                            TLMC_Unit.TLMC_Unit_Millimetres,
                            RET_V_MM_S,
                        )
                    )
                )
                a_dev_fast = int(
                    round(
                        c.device.convert_from_physical_to_device(
                            TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                            TLMC_Unit.TLMC_Unit_Millimetres,
                            RET_A_MM_S2,
                        )
                    )
                )
                c.device.set_velocity_params(0, a_dev_fast, v_dev_fast)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to set fast return speed: {ee}")

            if c._start_mm is not None:
                if c.timing:
                    c.timing.log_event("RETURN_BEGIN")
                cnt = int(
                    round(
                        c.device.convert_from_physical_to_device(
                            TLMC_ScaleType.TLMC_ScaleType_Distance,
                            TLMC_Unit.TLMC_Unit_Millimetres,
                            c._start_mm,
                        )
                    )
                )
                c.device.move_absolute(
                    TLMC_MoveModes.MoveMode_Absolute,
                    cnt,
                    TLMC_Wait.TLMC_InfiniteWait,
                )
                if c.timing:
                    c.timing.log_event("RETURN_DONE")

            c.sig_status.emit("returned to start position.")

        except Exception as e:
            c.sig_error.emit(f"return: {e}")

        finally:
            try:
                if prev_v is not None and c.device is not None:
                    v_dev_orig = int(
                        round(
                            c.device.convert_from_physical_to_device(
                                TLMC_ScaleType.TLMC_ScaleType_Velocity,
                                TLMC_Unit.TLMC_Unit_Millimetres,
                                prev_v,
                            )
                        )
                    )
                    a_dev_orig = int(
                        round(
                            c.device.convert_from_physical_to_device(
                                TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                                TLMC_Unit.TLMC_Unit_Millimetres,
                                prev_a,
                            )
                        )
                    )
                    c.device.set_velocity_params(0, a_dev_orig, v_dev_orig)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to restore speed: {ee}")

            try:
                if direction_for_log and c.timing:
                    c.timing.flush_to_csv(direction_for_log)
            except Exception:
                pass

            c._returning = False


def get_backend_class():
    """StagePanel から呼ばれるファクトリ用フック。"""
    return ThorlabsKST201Backend
