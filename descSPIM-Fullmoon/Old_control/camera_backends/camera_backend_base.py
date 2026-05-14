# camera_backend_base.py
from __future__ import annotations

from typing import Optional, Any

from PySide6.QtCore import QObject, Signal, Qt


class ICameraBackend(QObject):
    """
    カメラ用バックエンドの共通インターフェース。

    - GUI 側（CameraPane）は、このインターフェースだけを前提に記述しておく。
    - 実機ごとにサブクラス（NikonDS50MBackend, ThorlabsXXXBackend など）を作って実装する。
    """

    # CaptureWorker から渡ってくるフレームを GUI に中継するための共通シグナル
    # frame: dict で { "w", "h", "bits", "bpl", "data", ... } を想定
    sig_frame = Signal(object)

    # Win32 メッセージベースの SDK 用に、イベント種別ごとのシグナルも共通化
    # WinMsg を使わないバックエンドでは、emit しなくてもよい。
    sig_event = Signal(int, int)         # (wparam, lparam) 汎用イベント
    sig_image = Signal(int, int)         # 画像到着イベント
    sig_error = Signal(int, int)         # エラーイベント
    sig_disconnected = Signal(int, int)  # 切断イベント

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        # 共通で保持してもよいが、必須ではない
        self._pane: Any = parent
        self._worker: Any = None

    # ---- 共通ヘルパ / オプショナル API ----

    def attach_worker(self, worker: Any) -> None:
        """
        CaptureWorker の sig_frame_ready(object) → backend.sig_frame(object)
        への橋渡しを行う共通実装。

        特殊な経路（WinMsg 経由など）が必要な場合はサブクラス側で override する。
        """
        self._worker = worker
        try:
            worker.sig_frame_ready.connect(self.sig_frame, Qt.QueuedConnection)
        except Exception:
            # まだ worker 側が未実装でも落ちないようにしておく
            pass

    def describe_event(self, wparam: int) -> str:
        """
        SDK 固有のイベントコードを人間可読な文字列に変換する（任意実装）。
        実装しないバックエンドでは空文字を返しておけばよい。
        """
        return ""

    # ---- 必須メソッド（機種ごとに実装） ----

    def connect(self) -> bool:
        """カメラと接続し、必要なら SDK の初期化やハンドル取得を行う。"""
        raise NotImplementedError

    def disconnect(self) -> None:
        """
        カメラのクローズ／ストリーム停止／メモリ解放などを行う。
        CameraPane.closeEvent の中で呼び出されることを想定。
        """
        raise NotImplementedError

    def set_paused(self, paused: bool) -> None:
        """
        ストリームの一時停止 / 再開を行う。

        paused=True  -> Pause（ストリーム停止）
        paused=False -> Resume（ストリーム再開）
        """
        raise NotImplementedError

    def start_stream(self, hwnd: int) -> None:
        """
        Live view 用のストリーム開始処理。

        - Win32 メッセージベースの SDK の場合：
            hwnd をメッセージ送信先として登録し、その後ストリーム開始。
        - コールバック / ポーリングベースの SDK の場合：
            hwnd は無視して、内部スレッドやコールバック登録を行ってもよい。
        """
        raise NotImplementedError

    # ---- GUI 側の処理を段階的に移していく予定のメソッド ----

    def populate_controls(self, pane: "CameraPane") -> None:
        """
        GUI（CameraPane）のコントロールを SDK の現在値で初期化する。

        例：
          - ゲイン / 露光時間の範囲と現在値を SDK から読み取り、
            pane.ctrl_gain / pane.ctrl_expo に反映
          - 解像度の一覧を SDK から取得して pane.ctrl_res に addItem
          - 現在の bit depth を pane.ctrl_bit に反映
        """
        raise NotImplementedError

    def apply_gain_expo(self, gain: int, expo_ms: float) -> None:
        """
        ゲインと露光時間（ms）を SDK / カメラへ反映する。
        """
        raise NotImplementedError

    def apply_res_bit(self, res_index: int, bit_index: int) -> None:
        """
        解像度とビット深度を SDK / カメラへ反映する。
          - res_index: 解像度インデックス
          - bit_index: 0=8bit, 1=16bit など
        """
        raise NotImplementedError

    def set_roi(self, x: int, y: int, w: int, h: int) -> None:
        """
        ROI を SDK / カメラへ設定する。
        """
        raise NotImplementedError

    def reset_roi(self, full_width: int, full_height: int) -> None:
        """
        ROI をフルフレームに戻す。
        """
        raise NotImplementedError

    def get_full_frame_size(self, res_index: int | None) -> tuple[int, int]:
        """
        現在の解像度インデックスに対応するフルフレームサイズを返す。
        res_index が None の場合は、可能であれば「現在の出力サイズ」から推定する。
        """
        raise NotImplementedError

    def pull_frame_into_buffer(self, buf, size, bits: int):
        """
        カメラから 1 フレーム取得し、buf に詰め、
        UI 側で使う dict（w,h,bits,bpl,data,seq,ts_us,exp_us…）を返す。
        失敗したら None を返す。
        """
        raise NotImplementedError

    def query_params(self, bits: int):
        """
        現在の出力サイズ・ビット深度などを問い合わせる。
        戻り値は (w, h, bits, bpl, size) を想定。
        """
        raise NotImplementedError

    def get_current_bit_depth(self) -> int:
        """
        現在のカメラ設定のビット深度 (8 or 16 など) を返す。
        エラー時や未対応機種では 8bit を返しておくと無難。
        """
        raise NotImplementedError


# ===== Template backend for other camera models =====
#
# このクラスは「別機種 backend を作るときの雛形」です。
# 使い方の想定：
#   - このクラスを丸ごとコピーして、ファイル名・クラス名・中身を
#     そのカメラの SDK に合わせて書き換える。
#   - CameraPane に渡す backend を、その新しいクラスに差し替える。
#
# 例：
#   class ThorlabsXYZBackend(ICameraBackend):
#       ...  （下の ExampleSDKBackend をベースに実装）
#


class ExampleSDKBackend(ICameraBackend):
    """
    別機種用 backend のひな型。

    - self._pane : CameraPane への参照（必要なら UI にアクセス）
    - self._worker : CaptureWorker 相当のオブジェクト（sig_frame_ready を emit する側）
    - self._device : 実機 SDK のハンドルなどを保持する場所
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._pane: Any = parent
        self._worker: Any = None
        self._device: Any = None   # ここに SDK のハンドル等を入れる想定

    # --- CameraPane から呼ばれる想定の「共通 API」 -------------------------

    def attach_worker(self, worker: Any) -> None:
        """
        CaptureWorker のような「フレームを emit する側」を受け取って、
        self.sig_frame に橋渡しするためのメソッド。

        WinMsg を使わない SDK では、このまま共通実装で十分なことが多い。
        """
        super().attach_worker(worker)

    def connect(self) -> bool:
        """
        カメラへの接続処理を行う。

        実装例：
          - SDK の初期化
          - デバイス列挙 → 1台選んで open
          - self._device にハンドルを保存
          - 必要なら CameraPane 側に何か渡す
        """
        print("[ExampleSDKBackend] connect() is not implemented yet.")
        return False

    def disconnect(self) -> None:
        """
        カメラとの接続を閉じる。
        実機では Pause / Stop / Close 相当をここでまとめてやる。
        """
        if self._device is None:
            print("[ExampleSDKBackend] disconnect() called but no device.")
            return

        # TODO: SDK に合わせて安全にクローズする
        # 例：
        #   sdk_stop_stream(self._device)
        #   sdk_close(self._device)
        self._device = None
        print("[ExampleSDKBackend] Camera disconnect sequence finished.")

    def set_paused(self, paused: bool) -> None:
        """
        ストリームの一時停止 / 再開。
        """
        if self._device is None:
            print(f"[ExampleSDKBackend] set_paused({paused}) but no device.")
            return

        # TODO: SDK の Pause / Resume に合わせて実装
        # 例：
        #   sdk_pause(self._device, True/False)
        print(f"[ExampleSDKBackend] set_paused({paused}) called (not implemented).")

    def start_stream(self, hwnd: int) -> None:
        """
        Live view 用ストリーム開始。

        WinMsg を使わない SDK の場合、hwnd は無視してよい。
        """
        if self._device is None:
            print("[ExampleSDKBackend] start_stream() called but no device.")
            return

        # TODO: SDK に合わせてストリーム開始
        # 例：
        #   sdk_start_stream(self._device, callback=self._on_sdk_frame)
        print("[ExampleSDKBackend] start_stream() is not implemented yet.")

    # --- 以下は CameraPane から backend に寄せていく想定のメソッド ---

    def populate_controls(self, pane: "CameraPane") -> None:
        """
        GUI のコントロールを SDK の現在値で初期化する処理。
        """
        print("[ExampleSDKBackend] populate_controls() is not implemented yet.")

    def apply_gain_expo(self, gain: int, expo_ms: float) -> None:
        """
        ゲインと露光時間を SDK に反映する。
        """
        if self._device is None:
            print("[ExampleSDKBackend] apply_gain_expo called but no device.")
            return

        # TODO: SDK の API に合わせて実装
        # 例：
        #   sdk_set_gain(self._device, gain)
        #   sdk_set_exposure_ms(self._device, expo_ms)
        print(f"[ExampleSDKBackend] apply_gain_expo(gain={gain}, expo_ms={expo_ms}) not implemented.")

    def apply_res_bit(self, res_index: int, bit_index: int) -> None:
        """
        解像度と bit depth を SDK に反映する。

        res_index: CameraPane.ctrl_res.currentData() から渡ってくる想定のインデックス
        bit_index: 0 = 8bit, 1 = 16bit など
        """
        if self._device is None:
            print("[ExampleSDKBackend] apply_res_bit called but no device.")
            return

        # TODO: SDK に合わせて解像度変更＋bit depth 変更＋ストリーム再構成
        print(f"[ExampleSDKBackend] apply_res_bit(res_index={res_index}, bit_index={bit_index}) not implemented.")

    def set_roi(self, x: int, y: int, w: int, h: int) -> None:
        """
        ROI を SDK に設定する。
        """
        if self._device is None:
            print("[ExampleSDKBackend] set_roi called but no device.")
            return

        # TODO: SDK の ROI API を呼ぶ
        print(f"[ExampleSDKBackend] set_roi({x}, {y}, {w}, {h}) not implemented.")

    def reset_roi(self, full_width: int, full_height: int) -> None:
        """
        ROI をフルフレームに戻す。
        """
        if self._device is None:
            print("[ExampleSDKBackend] reset_roi called but no device.")
            return

        # TODO: (0,0, full_width, full_height) に戻す処理を SDK に合わせて実装
        print(f"[ExampleSDKBackend] reset_roi({full_width} x {full_height}) not implemented.")

    def get_full_frame_size(self, res_index: int | None) -> tuple[int, int]:
        """
        解像度インデックスからフルフレームサイズを返す。
        """
        if self._device is None:
            print("[ExampleSDKBackend] get_full_frame_size called but no device.")
            return (0, 0)

        # TODO: SDK から解像度一覧 or 現在の出力サイズを取得
        print(f"[ExampleSDKBackend] get_full_frame_size(res_index={res_index}) not implemented.")
        return (0, 0)

    def pull_frame_into_buffer(self, buf, size, bits: int):
        """
        カメラから 1 フレーム取得し、dict を返す。
        """
        if self._device is None:
            # print("[ExampleSDKBackend] pull_frame_into_buffer called but no device.")
            return None

        # TODO: SDK から画像を読み出して dict を組み立てる
        print("[ExampleSDKBackend] pull_frame_into_buffer() is not implemented yet.")
        return None

    def query_params(self, bits: int):
        """
        現在の出力サイズ・bit depth 等を問い合わせる。
        """
        if self._device is None:
            print("[ExampleSDKBackend] query_params called but no device.")
            return None

        # TODO: SDK から w,h を取得し、(w,h,bits,bpl,size) を返す
        print(f"[ExampleSDKBackend] query_params(bits={bits}) is not implemented yet.")
        return None

    def get_current_bit_depth(self) -> int:
        """
        現在の bit depth を返す。
        """
        if self._device is None:
            print("[ExampleSDKBackend] get_current_bit_depth called but no device.")
            return 8

        # TODO: SDK の設定値から 8 or 16 などを返す
        print("[ExampleSDKBackend] get_current_bit_depth() is not implemented yet; returning 8.")
        return 8

    def capture_snapshot(self, bits: int):
        """
        カメラから 1 フレームを同期で取得して返す。

        戻り値は dict を想定：
            {
                "w": width,
                "h": height,
                "bits": bits(8/16),
                "bpl": bytes_per_line,
                "data": メモリバッファ (bytes / memoryview / ctypes)
            }

        取得に失敗したら None を返す。

        pull_frame_into_buffer() を内部で使う実装でもよいし、
        SDK の「1フレームだけ取得」API を直接使ってもよい。
        """
        raise NotImplementedError
