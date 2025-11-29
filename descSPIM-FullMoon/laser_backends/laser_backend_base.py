# laser_backends/laser_backend_base.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Optional, List, Dict, Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget


class ILaserBackend(QObject):
    """
    すべての Laser backend が継承すべきインターフェース。
    規約案にあるメソッドを最小限の形で定義している。
    """

    # True: 接続完了 / False: 切断
    sig_connected = Signal(bool)

    # エラーが発生したときにメッセージを通知
    sig_error = Signal(str)

    # 状態オブジェクト（構造は backend ごとに自由）
    sig_state_changed = Signal(object)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

    # ---- 接続まわり ----
    def show_setup_dialog(self, parent: Optional[QWidget] = None) -> bool:
        """
        COM ポート / シリアル / 使用ラインなどを設定するためのダイアログを表示。
        OK なら True, キャンセルなら False を返す。
        """
        return True

    def connect(self) -> bool:
        """
        実デバイスに接続する。
        成功したら True を返し、必要であれば sig_connected(True) を emit する。
        """
        raise NotImplementedError

    def disconnect(self) -> None:
        """
        実デバイスから切断する。
        必要であれば sig_connected(False) を emit する。
        """
        raise NotImplementedError

    # ---- 能力・ライン情報 ----
    def get_capabilities(self) -> Dict[str, Any]:
        """
        例:
        {
            "type": "CoboltSkyra",
            "multi_line": True,
            "max_lines": 4,
        }
        """
        return {}

    def get_lines(self) -> List[Dict[str, Any]]:
        """
        例:
        [
            {"id": "488", "wavelength_nm": 488, "name": "488 nm"},
            {"id": "561", "wavelength_nm": 561, "name": "561 nm"},
        ]
        """
        return []

    # ---- 出力・ON/OFF ----
    def set_power_mw(self, line_id: str, power_mw: float) -> None:
        raise NotImplementedError

    def get_power_mw(self, line_id: str) -> float:
        raise NotImplementedError

    def get_power_range(self, line_id: str) -> tuple:
        """
        (min_mW, max_mW) を返す。
        実装していない backend 用のデフォルト値として 0–50 mW を返す。
        """
        return (0.0, 50.0)

    def set_enabled(self, line_id: str, enabled: bool) -> None:
        raise NotImplementedError

    def get_enabled(self, line_id: str) -> bool:
        raise NotImplementedError

    def set_master_enable(self, enabled: bool) -> None:
        """
        可能なら「全ライン ON/OFF」を提供。
        対応しない機種では no-op でもよい。
        """
        pass

    def emergency_shutdown(self) -> None:
        """
        緊急停止（可能なら全ライン強制 OFF）。
        """
        pass

    def query_status(self) -> Dict[str, Any]:
        """
        現在の状態を簡単な dict で返す。
        """
        return {}

    # ---- 論理的な一意キー ----
    def get_connection_key(self) -> str:
        """
        この物理レーザーを一意に表すキーを返す。
        例: "COM5", "SN=12345", "ip=192.168.0.10" など。
        """
        raise NotImplementedError
