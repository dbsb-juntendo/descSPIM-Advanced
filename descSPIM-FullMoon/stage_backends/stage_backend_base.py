# stage_backends/stage_backend_base.py
# -*- coding: utf-8 -*-
from PySide6.QtCore import QObject, Signal
from enum import IntEnum

class StepDirection(IntEnum):
    FORWARD = 0
    REVERSE = 1

class IStageBackend(QObject):
    """
    1 軸用のステージ backend 抽象クラス。
    StagePanel はこの API だけを見る。
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
        self.serial = ""
        self.product_code = ""

    # ---- StagePanel が呼ぶ最小 API セット ----
    def show_setup_dialog(self, parent=None) -> bool:
        """
        各 backend が必要な設定 UI を表示して self.serial / self.product_code 等を更新する。
        OK: True, Cancel: False を返す。
        """
        raise NotImplementedError

    def connect_device(self):
        """シリアル番号などを使ってデバイスを open する。"""
        raise NotImplementedError

    def shutdown(self):
        """アプリ終了時の後始末（close など）。"""
        raise NotImplementedError

    def set_product(self, product_code: str):
        """Z825 / Z925 などの製品コードを設定。"""
        raise NotImplementedError

    def apply_params(self, v_mm_s: float, a_mm_s2: float, dir_index: int):
        """
        速度・加速度・方向を設定。
        dir_index: 0 = Forward, 1 = Reverse
        """
        raise NotImplementedError

    def home(self):
        """Home 動作。"""
        raise NotImplementedError

    def register_start_point(self):
        """現在位置を Start 位置として記録。"""
        raise NotImplementedError

    def go_to_start_position(self):
        """記録した Start 位置へ戻る。"""
        raise NotImplementedError

    def start_continuous(self):
        """カメラ録画開始と同期してステージを連続移動開始。"""
        raise NotImplementedError

    def stop_only(self):
        """手動停止（Home/Return なし）。"""
        raise NotImplementedError

    def start_home_return_async(self, save_dir_for_log: str):
        """録画終了後に Home → Start 位置へ戻す非同期処理。"""
        raise NotImplementedError

    def start_jog(self, direction_index: int):
        """指定方向に連続 jog 開始。direction_index: 0=Forward, 1=Reverse."""
        raise NotImplementedError

    def stop_jog(self):
        """jog 停止。"""
        raise NotImplementedError

    def step(self, direction: StepDirection):
        """
        1 ステップだけ移動させる。
        direction: StepDirection.FORWARD / StepDirection.REVERSE
        """
        raise NotImplementedError

    def configure_step(
        self,
        step_mm: float,
        v_mm_s: float,
        a_mm_s2: float,
        dir_index: int,
    ) -> None:
        """
        任意実装: Step（↑ / ↓）用のパラメータを事前に設定する。
        StagePanel から呼ばれ、step() 実行時に backend が参照して使う想定。

        base 実装は no-op にしておけば、未対応 backend でも壊れない。
        """
        # デフォルトは何もしない（古い backend との互換性用）
        return
    
    def start_return(self, direction_for_log: str):
        """
        録画終了時などに「開始位置へ戻る」ための非同期処理を開始する。

        direction_for_log:
            timing_logger があれば、その CSV を flush するディレクトリ。
        """

        return