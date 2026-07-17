# timing_logger.py
# -*- coding: utf-8 -*-
# Copyright © 2026 Kiyotada Naitou
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

import csv
import os
import time
from datetime import datetime
from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QObject, Signal, Slot, QSettings

# ------------------------------
# Timing logger（同一スレッドでもそのまま利用）
# ------------------------------
class TimingLogger:
    def __init__(self):
        self._buf = []
        self._lock = QtCore.QMutex()

    @Slot(str)
    def log_event(self, name: str):
        t_perf = time.perf_counter_ns()
        t_wall = datetime.now().isoformat(timespec="milliseconds")
        with QtCore.QMutexLocker(self._lock):
            self._buf.append((t_wall, t_perf, name))

    def flush_to_csv(self, save_dir: str):
        if not save_dir:
            return
        os.makedirs(save_dir, exist_ok=True)
        path = os.path.join(save_dir, "timing_log.csv")
        header_needed = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if header_needed:
                w.writerow(["wall_time_iso", "perf_counter_ns", "label"])
            with QtCore.QMutexLocker(self._lock):
                for row in self._buf:
                    w.writerow(row)
                self._buf.clear()