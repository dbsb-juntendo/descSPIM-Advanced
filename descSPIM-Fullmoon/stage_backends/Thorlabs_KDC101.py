# stage_backends/Thorlabs_KDC101.py
# -*- coding: utf-8 -*-

from dataclasses import dataclass, field

from .stage_backend_base import IStageBackend, StepDirection
from timing_logger import TimingLogger

import time
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Slot, QSettings

from .internal import xa_shared


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


class ThorlabsKDC101Backend(IStageBackend):
    """
    Thorlabs KDC101 を 1 軸だけ扱う backend。
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
    req_step = QtCore.Signal(int)        
    req_return = QtCore.Signal()

    SETTINGS_GROUP_BASE = "StageBackend/Thorlabs_KDC101"

    def __init__(self, timing_logger: TimingLogger | None, parent=None):
        super().__init__(timing_logger=timing_logger, parent=parent)

        # 設定モデル
        self._config = StageAxisConfig()

        # IStageBackend 側にもあるが、明示しておく
        self.serial: str = ""
        self.product_code: str = "Z825"

        self.device = None  # type: ignore[assignment]
        self._start_mm: float | None = None

        # 連続移動用の現在方向（KDC101 API の MoveDirection）
        self._move_direction = None
        self._v_mm_s = self._config.move.v_mm_s
        self._a_mm_s2 = self._config.move.a_mm_s2
        self._jog_active = False

        # Step 用パラメータ
        self._step_mm = self._config.step.step_mm
        self._step_v_mm_s = self._config.step.v_mm_s
        self._step_a_mm_s2 = self._config.step.a_mm_s2

        #self._ret_thread: QtCore.QThread | None = None
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

    def _update_move_direction_from_dir_index(self, dir_index: int) -> None:
        """
        UI の dir_index (0/1) から KDC101 API 用 MoveDirection を更新する。
        """
        # StagePane: dir_index == 0 → "Forward"（＋方向に動いてほしい）
        # KDC101 実機では API の Reverse が ＋方向なので、
        # 0 → Move_Direction_Reverse, 1 → Move_Direction_Forward にする
        if dir_index == 0:
            self._move_direction = xa_shared.TLMC_MoveDirection.Move_Direction_Reverse
        else:
            self._move_direction = xa_shared.TLMC_MoveDirection.Move_Direction_Forward

    def _apply_move_params_to_device(self) -> None:
        """
        現在の move パラメータを実機に反映（set_velocity_params）する。
        """
        if not self._connected or self.device is None:
            self.sig_status.emit("no device")
            return

        try:
            v_dev = int(
                round(
                    self.device.convert_from_physical_to_device(
                        xa_shared.TLMC_ScaleType.TLMC_ScaleType_Velocity,
                        xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                        self._v_mm_s,
                    )
                )
            )
            a_dev = int(
                round(
                    self.device.convert_from_physical_to_device(
                        xa_shared.TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                        xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                        self._a_mm_s2,
                    )
                )
            )
            self.device.set_velocity_params(0, a_dev, v_dev)
            self.sig_status.emit("params applied.")
        except Exception as e:
            self.sig_error.emit(f"apply_move_params: {e}")

    # ---- util ----
    def show_setup_dialog(self, parent=None) -> bool:
        """
        KDC101 用設定ダイアログ（2 段階）:
        1) Serial を入力 → 接続を試みる
        2) 接続に成功したら、実機から列挙した product_code（Z825/Z925 等）を選択
        両方とも QSettings 経由で保存・復元する。
        """
        print("[ThorlabsKDC101Backend] show_setup_dialog called")
        # まず現在の axis に対する settings を読み込んでおく
        self._load_settings()

        # --- 1) serial ダイアログ ---
        serial_default = self.serial
        product_default = self.product_code or "Z825"

        dlg1 = QtWidgets.QDialog(parent)
        dlg1.setWindowTitle("Thorlabs KDC101 setup (Serial)")
        layout1 = QtWidgets.QFormLayout(dlg1)

        ed_serial = QtWidgets.QLineEdit()
        ed_serial.setPlaceholderText("2726xxxx")
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

        # --- 1') serial が決まったので接続を試みる ---
        self.connect_device()
        if not getattr(self, "_connected", False) or self.device is None:
            # connect_device 側で sig_error を出している想定
            return False

        # --- 2) 接続後、実機から対応 device を列挙して選択ダイアログ ---
        try:
            raw = self.device.get_connected_products_supported() or []
            products = self._normalize_products(raw)

        except Exception as ee:
            # 列挙に失敗した場合は fallback として現在の product_code だけ出す
            self.sig_status.emit(f"enumeration warning: {ee}")
            products = [product_default or "Z825"]

        if not products:
            products = [product_default or "Z825"]

        dlg2 = QtWidgets.QDialog(parent)
        dlg2.setWindowTitle("Thorlabs KDC101 setup (Device)")
        layout2 = QtWidgets.QFormLayout(dlg2)

        cmb_product = QtWidgets.QComboBox()
        cmb_product.setEditable(True)
        cmb_product.addItems(products)

        # 既存設定があれば優先
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
            # デバイス選択をキャンセルした場合は、接続自体はされているが
            # product_code は変更せず現状維持にする
            # serial はすでに更新されているので保存しておく
            self._save_settings()
            return True

        product_code = cmb_product.currentText().strip() or products[0]
        self.product_code = product_code

        # デバイスに反映
        self.set_product(product_code)

        # 設定を保存（serial / product_code / move / step）
        self._save_settings()

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
            f"[ThorlabsKDC101Backend] axis={getattr(self, 'axis_name', 'N/A')} "
            f"connect_device() serial={self.serial!r}"
        )
        try:
            if not self.serial:
                raise ValueError("serial not set")

            # グローバルに一度だけ SDK を初期化
            xa_shared.ensure_started()
            print("[ThorlabsKDC101Backend] XA started")  # デバッグ用

            self.device = xa_shared.KDC101(
                self.serial, "", xa_shared.TLMC_OperatingModes.Default
            )
            self.device.set_enable_state(
                xa_shared.TLMC_ChannelEnableStates.ChannelEnabled
            )

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

            # Motion worker thread を停止
            if self._motion_thread is not None:
                self._motion_thread.quit()
                self._motion_thread.wait()
                self._motion_thread = None

            # ここでは XASDK.shutdown() は呼ばない
            # （プロセス終了時に OS 側で解放される想定）

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

    # ---- move 用パラメータ適用 ---------------------------------------

    @Slot(float, float, int)
    def apply_move_params(self, v_mm_s: float, a_mm_s2: float, dir_index: int):
        """
        連続移動用（move/jog/return 基準）のパラメータを更新して実機に適用する。
        StagePane から呼ばれる既存のエントリポイント。
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
        実機への反映は do_step() 内で毎回行う。
        dir_index は move 側の方向フラグにも反映する。
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
        if not self._connected or self.device is None:
            self.sig_error.emit("register_start_point: not connected")
            return
        try:
            c = self.device.get_position_counter(xa_shared.TLMC_Wait.TLMC_InfiniteWait)
            self._start_mm = self.device.convert_from_device_units_to_physical(
                xa_shared.TLMC_ScaleType.TLMC_ScaleType_Distance, c
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
        direction: StepDirection.FORWARD (= 0) / StepDirection.REVERSE (= 1)
        Step size / velocity / acceleration は apply_step_params() で事前に設定された値を使う。
        """
        if not self._connected or self.device is None:
            self.sig_error.emit("step: not connected")
            return
        self.req_step.emit(int(direction))

    @Slot(str)
    def start_return(self):
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
    実際に KDC101 device を叩くスレッド用 worker。
    ThorlabsKDC101Backend からの req_* シグナルだけを入口にして、
    ここからのみ device.* を呼ぶ。
    """

    def __init__(self, backend: ThorlabsKDC101Backend):
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
            c.device.home(xa_shared.TLMC_Wait.TLMC_InfiniteWait)
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
                            xa_shared.TLMC_ScaleType.TLMC_ScaleType_Velocity,
                            xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                            RET_V_MM_S,
                        )
                    )
                )
                a_dev_fast = int(
                    round(
                        c.device.convert_from_physical_to_device(
                            xa_shared.TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                            xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
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
                        xa_shared.TLMC_ScaleType.TLMC_ScaleType_Distance,
                        xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                        c._start_mm,
                    )
                )
            )
            c.device.move_absolute(
                xa_shared.TLMC_MoveModes.MoveMode_Absolute,
                cnt,
                xa_shared.TLMC_Wait.TLMC_InfiniteWait,
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
                                xa_shared.TLMC_ScaleType.TLMC_ScaleType_Velocity,
                                xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                                prev_v,
                            )
                        )
                    )
                    a_dev_orig = int(
                        round(
                            c.device.convert_from_physical_to_device(
                                xa_shared.TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                                xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
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
            c.device.move_continuous(c._move_direction, xa_shared.TLMC_Wait.TLMC_NoWait)
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
                xa_shared.TLMC_StopModes.StopMode_Profiled,
                xa_shared.TLMC_Wait.TLMC_InfiniteWait,
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
            # StagePane: direction_index == 0 → 「↑↑」= Forward（＋）
            # → API 側では Reverse を呼ぶ（KDC101 仕様）
            if direction_index == 0:
                direction = xa_shared.TLMC_MoveDirection.Move_Direction_Reverse
                direction_label = "Forward"
            else:
                direction = xa_shared.TLMC_MoveDirection.Move_Direction_Forward
                direction_label = "Reverse"

            c.device.move_continuous(direction, xa_shared.TLMC_Wait.TLMC_NoWait)
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
                xa_shared.TLMC_StopModes.StopMode_Profiled,
                xa_shared.TLMC_Wait.TLMC_InfiniteWait,
            )
            c._jog_active = False
            c.sig_status.emit("stopped")

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
            step_mm = c._step_mm

            step_counts = int(
                round(
                    c.device.convert_from_physical_to_device(
                        xa_shared.TLMC_ScaleType.TLMC_ScaleType_Distance,
                        xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                        step_mm,
                    )
                )
            )
            if step_counts <= 0:
                step_counts = 1

            # --- Step 用の速度・加速度 ---
            v_mm_s = c._step_v_mm_s
            a_mm_s2 = c._step_a_mm_s2

            v_dev = int(
                round(
                    c.device.convert_from_physical_to_device(
                        xa_shared.TLMC_ScaleType.TLMC_ScaleType_Velocity,
                        xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                        v_mm_s,
                    )
                )
            )
            a_dev = int(
                round(
                    c.device.convert_from_physical_to_device(
                        xa_shared.TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                        xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                        a_mm_s2,
                    )
                )
            )

            jp = c.device.get_move_jog_params(xa_shared.TLMC_Wait.TLMC_InfiniteWait)

            c.device.set_move_jog_params(
                xa_shared.TLMC_JogModes.JogMode_SingleStep,
                step_counts,
                jp.min_velocity,
                v_dev,
                a_dev,
                xa_shared.TLMC_JogStopModes.JogStopMode_Profiled,
            )

            # 方向は StepDirection から決める
            if direction is StepDirection.FORWARD:
                # UI: Forward（↑） → API: Reverse（＋方向）
                d = xa_shared.TLMC_MoveDirection.Move_Direction_Reverse
                d_label = "Forward"
            else:
                # UI: Reverse（↓） → API: Forward（－方向）
                d = xa_shared.TLMC_MoveDirection.Move_Direction_Forward
                d_label = "Reverse"

            c.device.move_jog(d, xa_shared.TLMC_Wait.TLMC_InfiniteWait)
            c.sig_status.emit(f"{d_label} {step_mm*1000:.1f} um (step)")

        except Exception as e:
            c.sig_error.emit(f"step: {e}")

    @Slot(str)
    def do_return(self):
        """
        録画終了時などに「開始位置へ戻る」処理。
        以前の _ReturnWorker.run() を MotionWorker に統合。
        """
        c = self._b
        prev_v = prev_a = None

        try:
            if not c._connected or c.device is None:
                c.sig_error.emit("stop return: not connected")
                return

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
                            xa_shared.TLMC_ScaleType.TLMC_ScaleType_Velocity,
                            xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                            RET_V_MM_S,
                        )
                    )
                )
                a_dev_fast = int(
                    round(
                        c.device.convert_from_physical_to_device(
                            xa_shared.TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                            xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                            RET_A_MM_S2,
                        )
                    )
                )
                c.device.set_velocity_params(0, a_dev_fast, v_dev_fast)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to set fast return speed: {ee}")

            if c._start_mm is not None:
                cnt = int(
                    round(
                        c.device.convert_from_physical_to_device(
                            xa_shared.TLMC_ScaleType.TLMC_ScaleType_Distance,
                            xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                            c._start_mm,
                        )
                    )
                )
                c.device.move_absolute(
                    xa_shared.TLMC_MoveModes.MoveMode_Absolute,
                    cnt,
                    xa_shared.TLMC_Wait.TLMC_InfiniteWait,
                )

            c.sig_status.emit("returned to start position.")

        except Exception as e:
            c.sig_error.emit(f"return: {e}")

        finally:
            try:
                if prev_v is not None and c.device is not None:
                    v_dev_orig = int(
                        round(
                            c.device.convert_from_physical_to_device(
                                xa_shared.TLMC_ScaleType.TLMC_ScaleType_Velocity,
                                xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                                prev_v,
                            )
                        )
                    )
                    a_dev_orig = int(
                        round(
                            c.device.convert_from_physical_to_device(
                                xa_shared.TLMC_ScaleType.TLMC_ScaleType_Acceleration,
                                xa_shared.TLMC_Unit.TLMC_Unit_Millimetres,
                                prev_a,
                            )
                        )
                    )
                    c.device.set_velocity_params(0, a_dev_orig, v_dev_orig)
            except Exception as ee:
                c.sig_status.emit(f"warning: failed to restore speed: {ee}")

            c._returning = False


def get_backend_class():
    """StagePanel から呼ばれるファクトリ用フック。"""
    return ThorlabsKDC101Backend
