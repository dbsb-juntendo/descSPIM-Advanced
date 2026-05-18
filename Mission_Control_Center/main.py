# main.py
# -*- coding: utf-8 -*-
import sys
from typing import List, Optional

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QApplication, QMainWindow

from camera_integration import CameraPane
from stage_integration import StageBridge, StagePanel
from timing_logger import TimingLogger
from laser_integration import LaserPane
from filter_integration import FilterPane
from galvo_integration import GalvoPane   # ← ガルボパネル


class MainWindow(QMainWindow):
    def __init__(self, hcam=None):
        super().__init__()
        self.setWindowTitle("Microscope Control")

        # core helpers / controllers
        self.timing = TimingLogger()
        self.stage_bridge = StageBridge(self)

        # panes
        self.camera_pane = CameraPane(
            hcam,
            timing_logger=self.timing,
            stage_bridge=self.stage_bridge,
            parent=self,
        )
        self.stage_pane = StagePanel(
            self.stage_bridge, self.timing, parent=self.camera_pane
        )

        self.laser_pane = LaserPane(parent=self.camera_pane)
        self.galvo_pane = GalvoPane(parent=self.camera_pane)

        # FilterPane（1 台専任 / backend プラグイン方式）
        self.filter_pane = FilterPane(parent=self.camera_pane)
        # 最初から表示しておく（有効/無効は FilterPane 内部で制御してもよい）
        self.filter_pane.setEnabled(True)

        # layout: try to add into camera_pane.form, otherwise fallback vertical layout
        try:
            # assume camera_pane.form exists (QFormLayout-like)
            self.camera_pane.form.addRow(self.stage_pane)
            self.camera_pane.form.addRow(self.laser_pane)
            self.camera_pane.form.addRow(self.filter_pane)
            self.camera_pane.form.addRow(self.galvo_pane)
            self.setCentralWidget(self.camera_pane)
        except Exception:
            main_layout = QtWidgets.QVBoxLayout()
            main_layout.addWidget(self.stage_pane)
            main_layout.addWidget(self.laser_pane)
            main_layout.addWidget(self.filter_pane)
            main_layout.addWidget(self.galvo_pane)
            container = QtWidgets.QWidget(self)
            container.setLayout(main_layout)
            self.setCentralWidget(container)

        # wiring: stage 接続状態 → FilterPane 側へ camera_device を伝搬
        try:
            self.stage_pane.sig_connected.connect(self._on_stage_connected)
        except Exception:
            pass

        # ---------- Filter / Stage 連携（Orchestrator） ----------
        # フィルタボタン（Register OFF）押下 → フィルタ変更要求シグナル
        try:
            self.filter_pane.sig_filter_change_requested.connect(
                self._on_filter_change_requested
            )
        except Exception:
            pass

        # フィルタ移動完了待ち用タイマー（busy=Falseまで backend.query_status で監視）
        self._filter_move_timer = QtCore.QTimer(self)
        self._filter_move_timer.setInterval(50)  # 50 ms 間隔程度
        self._filter_move_timer.timeout.connect(self._check_filter_move_done)
        self._pending_filter_label: Optional[str] = None
        # 前回フィルタ名（差分計算用 / 「from」側）
        self._last_filter_label: Optional[str] = None

        # ---- Laser と Filter の連携は将来用。いったんコメントアウト ----
        # wiring: when laser connect/refresh clicked, schedule wavelength collection
        # try:
        #     # LaserPane 側で btn_connect を持っている前提（backend 追加用）
        #     self.laser_pane.btn_connect.clicked.connect(self._on_laser_connect_clicked)
        # except Exception:
        #     pass
        #
        # # LaserPane が波長シグナルを持っていれば接続
        # for attr in (
        #     "sig_wavelengths",
        #     "sig_supported_wavelengths",
        #     "sig_lines",
        #     "sig_available_lines",
        # ):
        #     if hasattr(self.laser_pane, attr):
        #         try:
        #             getattr(self.laser_pane, attr).connect(self._on_laser_wavelengths)
        #             break
        #         except Exception:
        #             pass

    # ---------- laser wavelength helpers（将来用に残しておくが未使用） ----------
    def _collect_laser_wavelengths(self) -> List[str]:
        out: List[str] = []
        try:
            if hasattr(self.laser_pane, "get_all_wavelengths"):
                raw = self.laser_pane.get_all_wavelengths() or []
            else:
                raw = []

            for wl in raw:
                if isinstance(wl, (int, float)):
                    s = f"{int(wl)}nm"
                else:
                    s = str(wl).strip()
                    if s.lower().endswith("nm"):
                        out.append(s)
                        continue
                    digits = "".join(ch for ch in s if ch.isdigit())
                    s = f"{digits}nm" if digits else s
                out.append(s)
        except Exception:
            pass
        return out[:4]

    def _on_laser_connect_clicked(self):
        QtCore.QTimer.singleShot(200, self._on_laser_connected)

    def _on_laser_connected(self):
        try:
            wls = self._collect_laser_wavelengths()
            if wls:
                self.filter_pane.set_wavelengths(wls)
        except Exception:
            pass

    @QtCore.Slot(list)
    def _on_laser_wavelengths(self, wls):
        try:
            norm = []
            for x in wls:
                if isinstance(x, (int, float)):
                    norm.append(f"{int(x)}nm")
                else:
                    s = str(x).strip()
                    if s.lower().endswith("nm"):
                        norm.append(s)
                    else:
                        digits = "".join(ch for ch in s if ch.isdigit())
                        norm.append(f"{digits}nm" if digits else s)
            norm = norm[:4]
            if norm:
                self.filter_pane.set_wavelengths(norm)
        except Exception:
            pass

    # ---------- stage connected ----------
    @QtCore.Slot(bool)
    def _on_stage_connected(self, connected: bool):
        try:
            cam_device = self.stage_pane.get_camera_device()
            if cam_device is not None:
                self.filter_pane.set_camera_device(cam_device)
        except Exception:
            pass

    # ---------- filter change → stage focus correction (Orchestrator) ----------
    @QtCore.Slot(str)
    def _on_filter_change_requested(self, label: str):
        """
        FilterPane からの「フィルタ変更要求」を受け取り、
        backend.busy が False になるまで待ってから
        「登録位置間の差分」によるフォーカス補正を発火する。
        """
        # ステージ同期が無効なら何もしない
        try:
            if not self.filter_pane.is_stage_sync_enabled():
                return
        except Exception:
            return

        # カメラステージ軸が未設定なら何もしない
        try:
            focus_ctl = getattr(self.filter_pane, "_focus_controller", None)
            if focus_ctl is None or getattr(focus_ctl, "camera", None) is None:
                return
        except Exception:
            return

        # 「今のフィルタ名」を backend.position から取得して from_label として保存
        try:
            backend = getattr(self.filter_pane, "backend", None)
            if backend is not None:
                state = backend.query_status() or {}
                pos = state.get("position")
                slot_names = getattr(self.filter_pane, "_slot_names", {}) or {}
                if isinstance(pos, int) and pos in slot_names:
                    current_label = slot_names.get(pos)
                    if current_label:
                        self._last_filter_label = current_label
        except Exception as e:
            print(f"[MainWindow] failed to get current filter label: {e}")

        # 監視対象ラベルを登録し、タイマー開始
        self._pending_filter_label = label
        if not self._filter_move_timer.isActive():
            self._filter_move_timer.start()

    def _check_filter_move_done(self):
        """
        backend.query_status().busy が False になるのを待ち、
        完了後に「登録位置間の差分」のみでフォーカス補正を行う。
        """
        label = self._pending_filter_label
        if not label:
            self._filter_move_timer.stop()
            return

        backend = getattr(self.filter_pane, "backend", None)
        if backend is None:
            self._filter_move_timer.stop()
            self._pending_filter_label = None
            return

        # busy 状態を問い合わせ
        try:
            state = backend.query_status() or {}
        except Exception as e:
            print(f"[MainWindow] filter query_status error: {e}")
            self._filter_move_timer.stop()
            self._pending_filter_label = None
            return

        busy = bool(state.get("busy", False))

        # Motorized backend: busy=True の間は待機
        # Manual backend: busy が常に False の想定なので、最初の呼び出しですぐ進む
        if busy:
            return

        # ここに来た時点で「フィルタ移動完了」とみなす
        try:
            focus_ctl = getattr(self.filter_pane, "_focus_controller", None)
            if focus_ctl is None:
                return

            from_label = self._last_filter_label
            to_label = label

            # 差分が定義できない場合（前回ラベルなし or 同一ラベル）は何もしない
            if not from_label or from_label == to_label:
                # ここではステージを動かさず、そのまま終了
                return

            # 常に「登録位置間の差分」のみで移動
            focus_ctl.apply_delta_mm(from_label, to_label)

            # 今回を「前回のラベル」として記録
            self._last_filter_label = to_label

        except Exception as e:
            print(f"[MainWindow] focus correction error: {e}")
        finally:
            self._pending_filter_label = None
            self._filter_move_timer.stop()

    # ---------- shutdown ----------
    def on_shutdown(self):
        # まずカメラまわりを確実に止める
        try:
            print("[MainWindow] on_shutdown() start")

            if hasattr(self.camera_pane, "worker_thread") and self.camera_pane.worker_thread:
                print("[MainWindow] Stopping camera worker thread...")
                try:
                    backend = getattr(self.camera_pane, "backend", None)
                    if backend is not None:
                        try:
                            backend.set_paused(True)
                        except Exception as e:
                            print(f"[MainWindow] set_paused error: {e}")
                except Exception as e:
                    print(f"[MainWindow] backend pause block error: {e}")

                self.camera_pane.worker_thread.quit()
                self.camera_pane.worker_thread.wait(5000)
                print("[MainWindow] Camera worker thread stopped.")

            backend = getattr(self.camera_pane, "backend", None)
            if backend is not None:
                try:
                    backend.disconnect()
                except Exception as e:
                    print(f"[MainWindow] backend.disconnect error: {e}")

        except Exception as e:
            print(f"[MainWindow] camera shutdown block error: {e}")

        # ステージ・レーザー等
        try:
            self.filter_pane.on_shutdown()
        except Exception:
            pass
        try:
            getattr(self.stage_pane, "on_shutdown", lambda: None)()
        except Exception:
            pass
        try:
            getattr(self.laser_pane, "on_shutdown", lambda: None)()
        except Exception:
            pass
        try:
            getattr(self.galvo_pane, "on_shutdown", lambda: None)()
        except Exception:
            pass

        print("[MainWindow] on_shutdown() finished.")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow(hcam=None)
    app.aboutToQuit.connect(lambda: w.on_shutdown())
    w.resize(1300, 1300)
    w.show()
    sys.exit(app.exec())
