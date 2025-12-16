# stage_backends/stage_backend_base.py
# -*- coding: utf-8 -*-
from PySide6.QtCore import QObject, Signal
from enum import IntEnum

"""
home() → req_home → do_home()

go_to_start_position() → req_go_start → do_go_to_start_position()

start_continuous() → req_start_continuous → do_start_continuous()

stop_only() → req_stop_only → do_stop_only()

start_jog(direction_index) → req_start_jog → do_start_jog(direction_index)

stop_jog() → req_stop_jog → do_stop_jog()

step(direction) → req_step → do_step(direction_value)

start_return(direction_for_log) → req_return → do_return(direction_for_log)

"""


class StepDirection(IntEnum):
    FORWARD = 0
    REVERSE = 1


class IStageBackend(QObject):
    """
    1 軸用のステージ backend 抽象クラス。
    StagePanel はこの API だけを見る。

    ThorlabsKDC101Backend を基準にした共通インタフェース。
    """

    # 共通シグナル
    sig_status = Signal(str)        # "connected", "homing..." など
    sig_error = Signal(str)         # エラー文字列
    sig_connected = Signal(bool)    # True = 接続完了, False = 切断
    sig_startpos_updated = Signal(float)  # start 位置 [mm]
    sig_supported_products = Signal(list) # ["Z825", "Z925", ...]

    def __init__(self, timing_logger=None, parent=None):
        super().__init__(parent)
        self.timing = timing_logger
        self._connected = False
        # serial / product_code は各 backend が適宜使う
        self.serial: str = ""
        self.product_code: str = ""

    # ---- StagePanel が呼ぶ最小 API セット ----

    # 設定・接続まわり
    def show_setup_dialog(self, parent=None) -> bool:
        """
        必須:
            backend 固有の設定 UI を表示して
            self.serial / self.product_code 等を更新し、
            必要なら connect_device() / set_product() まで行う。

        戻り値:
            True  = 設定確定（OK）
            False = キャンセル
        """
        raise NotImplementedError

    def connect_device(self) -> None:
        """
        必須:
            self.serial などを用いて実機デバイスを open し、
            self._connected / sig_connected を更新する。
        """
        raise NotImplementedError

    def shutdown(self) -> None:
        """
        必須:
            デバイスの disconnect / close、
            スレッド停止などの後始末を行う。
        """
        raise NotImplementedError

    def set_product(self, product_code: str) -> None:
        """
        必須:
            Z825 / Z925 など製品コードを backend に設定する。
        """
        raise NotImplementedError

    # ---- Move（連続移動 / jog / return 基準）用パラメータ ----

    def apply_move_params(self, v_mm_s: float, a_mm_s2: float, dir_index: int) -> None:
        """
        必須:
            連続移動（move / jog / return の基準）用の
            速度・加速度・方向を更新し、必要なら実機に反映する。

        引数:
            v_mm_s   : 速度 [mm/s]
            a_mm_s2  : 加速度 [mm/s^2]
            dir_index: 0 = Forward, 1 = Reverse（UI ベース）
        """
        raise NotImplementedError

    # ---- Step（↑ / ↓）用パラメータ ----

    def apply_step_params(
        self,
        step_mm: float,
        v_mm_s: float,
        a_mm_s2: float,
        dir_index: int,
    ) -> None:
        """
        必須:
            Step（↑ / ↓）用パラメータを更新して保存する。
            実機への反映は step() 実行時に行ってもよいし、
            ここで行ってもよい（実装依存）。

        引数:
            step_mm : ステップ量 [mm]
            v_mm_s  : Step 移動速度 [mm/s]
            a_mm_s2 : Step 加速度 [mm/s^2]
            dir_index: 0 = Forward, 1 = Reverse
                      （向きを Move 側にも共有したい場合に利用）
        """
        raise NotImplementedError

    # ---- 動作コマンド ----

    def home(self) -> None:
        """必須: Home 動作。"""
        raise NotImplementedError

    def register_start_point(self) -> None:
        """
        必須:
            現在位置を Start 位置として記録し、
            sig_startpos_updated(start_mm) を emit する。
        """
        raise NotImplementedError

    def go_to_start_position(self) -> None:
        """必須: 記録した Start 位置へ戻る。"""
        raise NotImplementedError

    def start_continuous(self) -> None:
        """
        必須:
            Move 連続移動を開始する。
            CameraPane の録画開始と同期して呼ばれる想定。
        """
        raise NotImplementedError

    def stop_only(self) -> None:
        """必須: 連続移動を停止する（Home/Return なし）。"""
        raise NotImplementedError

    def start_jog(self, direction_index: int) -> None:
        """
        必須:
            jog 連続移動を開始する。

        引数:
            direction_index: 0 = Forward（UI 上の「↑↑」）
                             1 = Reverse（UI 上の「↓↓」）
        """
        raise NotImplementedError

    def stop_jog(self) -> None:
        """必須: jog を停止する。"""
        raise NotImplementedError

    def step(self, direction: StepDirection) -> None:
        """
        必須:
            1 ステップだけ移動させる。

        引数:
            direction: StepDirection.FORWARD / StepDirection.REVERSE
        """
        raise NotImplementedError

    def start_return(self) -> None:
        """
        必須:
            録画終了時などに「開始位置へ戻る」処理を開始する。
        """
        raise NotImplementedError
