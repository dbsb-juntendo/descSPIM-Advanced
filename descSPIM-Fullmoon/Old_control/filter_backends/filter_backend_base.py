# -*- coding: utf-8 -*-
"""
filter_backend_base.py

Filter 用 Backend の共通インターフェース定義。

■ 役割
- 各種フィルターチェンジャー（手動 / 電動 / ホイール / スライダーなど）の
  HW 依存ロジックをカプセル化する。
- UI（FilterPane）や他デバイス構成を一切知らない。
- query_status() でフィルタ状態を返す「唯一の真実のソース」となる。

■ 必須シグナル
- sig_connected(bool): 接続状態の変化
- sig_state_changed(dict): 状態変化通知（query_status() と同じ構造）
- sig_error(str): エラー通知

■ query_status() の正式仕様
{
    "position": int,      # 現在位置 (1..N) または 0（未設定）
    "num_slots": int,     # 総スロット数
    "slot_names": {       # スロット番号 → 表示名
        1: "DAPI",
        2: "FITC",
        ...
    },
    "busy": bool          # 移動中かどうか
}
"""

from __future__ import annotations

from typing import Dict, Any

from PySide6 import QtCore
from PySide6.QtCore import QObject


class IFilterBackend(QObject):
    """
    Filter backend 抽象クラス。

    - 1 デバイス = 1 backend インスタンス。
    - HW 通信（USB / Serial / DLL / MCU 等）と状態保持を担当。
    - UI / Orchestrator はこのクラスの公開 API とシグナルのみを利用する。
    """

    sig_connected = QtCore.Signal(bool)
    sig_state_changed = QtCore.Signal(object)  # dict 期待
    sig_error = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    # ------------------------------------------------------------------
    # 接続前設定
    # ------------------------------------------------------------------
    def show_setup_dialog(self, parent=None) -> bool:
        """
        接続前に、ポート名やスロット数など HW 固有の設定をユーザーに尋ねる。
        - True: OK / 設定完了
        - False: キャンセル
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 接続 / 切断
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        """
        デバイスへ接続し、初期状態を query_status() で通知する。
        成功時には sig_connected(True) を emit すること。
        """
        raise NotImplementedError

    def disconnect(self) -> None:
        """
        デバイスを切断する。
        切断時には sig_connected(False) を emit すること。
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 構造取得
    # ------------------------------------------------------------------
    def get_num_slots(self) -> int:
        """
        スロット数（フィルタ枚数）を返す。
        """
        raise NotImplementedError

    def get_slot_names(self) -> Dict[int, str]:
        """
        スロット番号 → デフォルト名の dict を返す。
        実際の表示名は FilterPane 側で上書きされる可能性がある。
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 位置制御
    # ------------------------------------------------------------------
    def set_position(self, slot: int) -> None:
        """
        指定スロット番号にフィルタを移動させる。
        - 電動機種ではモータ駆動を行う。
        - 手動機種（ManualChangeBackend 等）では内部状態のみ更新する。
        完了後は query_status() を反映した dict を sig_state_changed で通知すること。
        """
        raise NotImplementedError

    def get_position(self) -> int:
        """
        現在位置のスロット番号を返す（1..N または 0）。
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 状態取得
    # ------------------------------------------------------------------
    def query_status(self) -> Dict[str, Any]:
        """
        現在の状態を dict で返す（仕様はモジュール冒頭参照）。
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # 安全系
    # ------------------------------------------------------------------
    def emergency_shutdown(self) -> None:
        """
        緊急停止。
        - モータ停止 / 出力停止 など、可能な限り安全側に倒す。
        - Manual backend では busy フラグを落として状態通知するだけでもよい。
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # オプション: スロット名更新
    # ------------------------------------------------------------------
    def update_slot_name(self, slot: int, name: str) -> None:
        """
        FilterPane 側のスロット名ダイアログで編集された名称を backend に反映する。
        実装が不要な機種は no-op でよい。
        """
        # デフォルト実装は何もしない
        return


__all__ = ["IFilterBackend"]
