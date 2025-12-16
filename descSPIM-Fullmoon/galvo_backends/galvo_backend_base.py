# galvo_backends/galvo_backend_base.py
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import List, Dict, Any
from PySide6.QtCore import QObject, Signal


class IGalvoBackend(QObject):
    """
    Galvo / パターンジェネレータ backend の共通インターフェース

    ・UI や他デバイス（Camera / Stage / Laser）は一切知らない
    ・チャンネルは ch_id (例: "CH1", "CH2") で扱う
    """

    sig_connected = Signal(bool)      # True: connected / False: disconnected
    sig_error = Signal(str)           # エラー時のメッセージ
    sig_state_changed = Signal(object)  # 状態変更通知（任意の dict 等）

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

    # ---- 接続系 ----
    def show_setup_dialog(self, parent=None) -> bool:
        """
        接続に必要な情報（COM ポート等）をダイアログで受け取る。
        OK なら True, キャンセルなら False を返す。
        """
        raise NotImplementedError

    def connect(self) -> bool:
        """
        デバイスに接続する。
        成功時 True / 失敗時 False を返す。
        """
        raise NotImplementedError

    def disconnect(self) -> None:
        """
        デバイスとの接続を切断する。
        """
        raise NotImplementedError

    def get_connection_key(self) -> str:
        """
        二重接続防止用のキーを返す。
        例: "COM5", "SN=XXXX" など。一意であればよい。
        """
        raise NotImplementedError

    # ---- チャンネル情報 ----
    def get_channels(self) -> List[Dict[str, Any]]:
        """
        利用可能なチャンネル一覧を返す。
        例: [{"id": "CH1", "name": "CH1"}, {"id": "CH2", "name": "CH2"}]
        """
        raise NotImplementedError

    # ---- パラメータ設定 ----
    def set_freq(self, ch_id: str, value_hz: float) -> None:
        raise NotImplementedError

    def set_amp(self, ch_id: str, value_vpp: float) -> None:
        raise NotImplementedError

    def set_offset(self, ch_id: str, value_v: float) -> None:
        raise NotImplementedError

    def set_waveform(self, ch_id: str, wave: str) -> None:
        """
        wave: "sine", "square", "triangle", "sawtooth" など
        """
        raise NotImplementedError

    # ---- ON/OFF ----
    def set_enabled(self, ch_id: str, enabled: bool) -> None:
        raise NotImplementedError

    def get_enabled(self, ch_id: str) -> bool:
        raise NotImplementedError

    # ---- 状態問い合わせ / 安全系 ----
    def query_status(self) -> Dict[str, Any]:
        """
        任意の状態情報を dict で返す。
        GalvoPane 側では、以下の形を想定して利用する:
            {
                "channels": {
                    "CH1": {
                        "enabled": bool,
                        "waveform": str,
                        "freq": float,
                        "amp": float,
                        "offset": float,
                    },
                    ...
                }
            }
        """
        raise NotImplementedError

    def emergency_shutdown(self) -> None:
        """
        全チャンネルを安全な状態（出力 OFF）にする。
        """
        raise NotImplementedError
