# -*- coding: utf-8 -*-
"""
Stack_and_Avg_GUI
────────────────────
• ex488 / ex561 / ex647 / ex730:
    - Unmixed maps (e.g., Cy3_, A594_, Alexa488_...) are stacked across loops
      into multi-page TIFFs (one stack per label), preserving original dtype
      and without scaling.

• ex405:
    - From each loop TIFF stack, pick bands by wavelength:
        choose nm_min (e.g., 470 nm), then take the first K bands (K=1..5)
      within [nm >= nm_min], average them into 2D image per loop,
      then save a multi-page TIFF across loops (optionally save per-loop images).

• Loops are detected by "loop(\d+)" in filenames and sorted numerically.
• XML for 405 nm can be provided once (global) or detected as sidecar "loop*.tif(f).xml".

Deps: tkinter, numpy, tifffile, pillow (optional), lxml not required.

"""

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
import tifffile as tiff
from xml.etree import ElementTree as ET

# ---------- Common helpers ----------

LOOP_RE = re.compile(r"loop(?P<num>\d+)", re.IGNORECASE)

def find_sidecar_xml_for_any_loop(folder: Path) -> Optional[Path]:
    for f in folder.iterdir():
        if f.is_file() and f.suffix.lower() in (".tif", ".tiff"):
            m = LOOP_RE.search(f.name)
            if m:
                x = Path(str(f) + ".xml")
                if x.exists():
                    return x
    return None

def parse_xml_wavelengths(xml_path: Path) -> List[float]:
    root = ET.parse(xml_path).getroot()
    ws = []
    for band in root.findall(".//band"):
        try:
            wl = float(band.attrib.get("wavelength_nm", "0"))
        except Exception:
            wl = 0.0
        if wl > 0:
            ws.append(wl)
    return ws

def sorted_loop_files(folder: Path) -> List[Path]:
    files = []
    for f in folder.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".tif", ".tiff"):
            continue
        m = LOOP_RE.search(f.name)
        if not m:
            continue
        try:
            num = int(m.group("num"))
        except Exception:
            continue
        files.append((num, f))
    files.sort(key=lambda x: x[0])
    return [f for _, f in files]

def read_tiff_as_stack(p: Path) -> np.ndarray:
    arr = tiff.imread(str(p))
    # shape: (Z,H,W) or (H,W); normalize to 3D
    if arr.ndim == 2:
        arr = arr[None, ...]
    return arr

def bigtiff_needed(stack_bytes: int) -> bool:
    return stack_bytes >= 4 * (1024 ** 3)  # >= 4 GiB

# ---------- ex405 averaging ----------

def band_indices_for_405(xml_wls: List[float], nm_min: float, k_first: int) -> List[int]:
    """Return first k_first indices whose wavelength >= nm_min."""
    idx = [i for i, w in enumerate(xml_wls) if w >= nm_min]
    return idx[:k_first]

def average_bands(stack: np.ndarray, indices: List[int]) -> np.ndarray:
    """stack: (B,H,W) -> average over selected band indices -> (H,W)."""
    if not indices:
        raise ValueError("No band indices selected for averaging.")
    sel = [i for i in indices if 0 <= i < stack.shape[0]]
    if not sel:
        raise ValueError("Selected band indices are out of stack range.")
    return stack[sel, :, :].mean(axis=0)

# ---------- GUI Blocks ----------

class ChannelStackUI(ttk.LabelFrame):
    """
    For ex488/ex561/ex647/ex730:
      - input folder containing per-loop single-page TIFFs per label (e.g., Cy3_*.tif)
      - loops N
      - optional label filter (regex): stack per label across loops
    """
    def __init__(self, master, title: str):
        super().__init__(master, text=title)
        self.var_folder = tk.StringVar(value="")
        self.var_loops = tk.IntVar(value=300)
        self.var_label_regex = tk.StringVar(value="")  # empty = auto-detect labels
        self.var_make_individual = tk.BooleanVar(value=False)  # save individual frames too?
        self._build()

    def _build(self):
        p = {"padx": 6, "pady": 3}

        ttk.Label(self, text="Source folder").grid(row=0, column=0, sticky="e", **p)
        ttk.Entry(self, textvariable=self.var_folder, width=52).grid(row=0, column=1, sticky="we", **p)
        ttk.Button(self, text="Browse", command=self._choose_folder).grid(row=0, column=2, **p)

        ttk.Label(self, text="Loops (N)").grid(row=1, column=0, sticky="e", **p)
        ttk.Entry(self, textvariable=self.var_loops, width=10).grid(row=1, column=1, sticky="w", **p)

        ttk.Label(self, text="Label filter (regex, optional)").grid(row=2, column=0, sticky="e", **p)
        ttk.Entry(self, textvariable=self.var_label_regex, width=52).grid(row=2, column=1, sticky="we", **p)

        ttk.Checkbutton(self, text="Also save individual per-loop files under /Singles", variable=self.var_make_individual).grid(
            row=3, column=1, sticky="w", **p
        )

    def _choose_folder(self):
        d = filedialog.askdirectory(title=f"Choose source folder ({self['text']})")
        if d:
            self.var_folder.set(d)

    def params(self) -> Dict:
        return dict(
            folder=Path(self.var_folder.get().strip()) if self.var_folder.get().strip() else None,
            loops=max(1, int(self.var_loops.get())),
            label_regex=self.var_label_regex.get().strip(),
            save_singles=bool(self.var_make_individual.get()),
        )

class EX405UI(ttk.LabelFrame):
    """
    For ex405 averaging into multipage:
      - source folder of per-loop stacks (tiff with multiple bands)
      - loops N
      - nm_min (>=470), first K bands (1..5) among [wavelength >= nm_min]
      - optional XML selection (or use sidecar)
      - option to save per-loop averaged images too
    """
    def __init__(self, master):
        super().__init__(master, text="ex405 — Average first 1–5 bands by nm")
        self.var_folder = tk.StringVar(value="")
        self.var_loops = tk.IntVar(value=300)
        self.var_nm_min = tk.DoubleVar(value=470.0)
        self.var_k_first = tk.IntVar(value=5)
        self.var_xml = tk.StringVar(value="")  # optional override
        self.var_save_singles = tk.BooleanVar(value=True)
        self._build()

    def _build(self):
        p = {"padx": 6, "pady": 3}

        ttk.Label(self, text="Source folder (loop TIFF stacks)").grid(row=0, column=0, sticky="e", **p)
        ttk.Entry(self, textvariable=self.var_folder, width=52).grid(row=0, column=1, sticky="we", **p)
        ttk.Button(self, text="Browse", command=self._choose_folder).grid(row=0, column=2, **p)

        ttk.Label(self, text="Loops (N)").grid(row=1, column=0, sticky="e", **p)
        ttk.Entry(self, textvariable=self.var_loops, width=10).grid(row=1, column=1, sticky="w", **p)

        ttk.Label(self, text="nm_min (≥470)").grid(row=2, column=0, sticky="e", **p)
        ttk.Entry(self, textvariable=self.var_nm_min, width=10).grid(row=2, column=1, sticky="w", **p)

        ttk.Label(self, text="First K bands within [nm ≥ nm_min] (1–5)").grid(row=3, column=0, sticky="e", **p)
        ttk.Spinbox(self, from_=1, to=5, textvariable=self.var_k_first, width=6).grid(row=3, column=1, sticky="w", **p)

        ttk.Label(self, text="XML (optional; else sidecar)").grid(row=4, column=0, sticky="e", **p)
        ttk.Entry(self, textvariable=self.var_xml, width=52).grid(row=4, column=1, sticky="we", **p)
        ttk.Button(self, text="Browse", command=self._choose_xml).grid(row=4, column=2, **p)

        ttk.Checkbutton(self, text="Also save per-loop averaged images", variable=self.var_save_singles).grid(
            row=5, column=1, sticky="w", **p
        )

    def _choose_folder(self):
        d = filedialog.askdirectory(title="Choose ex405 folder")
        if d:
            self.var_folder.set(d)

    def _choose_xml(self):
        f = filedialog.askopenfilename(title="Choose XML", filetypes=[("XML", "*.xml"), ("All", "*.*")])
        if f:
            self.var_xml.set(f)

    def params(self) -> Dict:
        return dict(
            folder=Path(self.var_folder.get().strip()) if self.var_folder.get().strip() else None,
            loops=max(1, int(self.var_loops.get())),
            nm_min=float(self.var_nm_min.get()),
            k_first=max(1, min(5, int(self.var_k_first.get()))),
            xml=Path(self.var_xml.get().strip()) if self.var_xml.get().strip() else None,
            save_singles=bool(self.var_save_singles.get()),
        )

class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        master.title("Stack multipage (ex488/561/647/730) + Average & stack (ex405)")
        master.protocol("WM_DELETE_WINDOW", master.destroy)
        self.grid(padx=10, pady=10, sticky="nsew")

        # Output root
        self.var_out = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "multipage_output"))
        self._build_header()

        # Channels
        self.ch488 = ChannelStackUI(self, "ex488 — Stack unmixed results to multipage")
        self.ch561 = ChannelStackUI(self, "ex561 — Stack unmixed results to multipage")
        self.ch647 = ChannelStackUI(self, "ex647 — Stack unmixed results to multipage")
        self.ch730 = ChannelStackUI(self, "ex730 — Stack unmixed results to multipage")
        self.ch405 = EX405UI(self)

        self.ch488.grid(row=1, column=0, sticky="nsew", pady=(6,2))
        self.ch561.grid(row=2, column=0, sticky="nsew", pady=(6,2))
        self.ch647.grid(row=3, column=0, sticky="nsew", pady=(6,2))
        self.ch730.grid(row=4, column=0, sticky="nsew", pady=(6,2))
        self.ch405.grid(row=5, column=0, sticky="nsew", pady=(6,2))

        ctrl = ttk.Frame(self); ctrl.grid(row=6, column=0, sticky="e", pady=(8,0))
        ttk.Button(ctrl, text="Run", command=self.on_run).grid(row=0, column=0, padx=6)
        ttk.Button(ctrl, text="Quit", command=self.master.destroy).grid(row=0, column=1, padx=6)

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status).grid(row=7, column=0, sticky="w", pady=(6,0))

    def _build_header(self):
        f = ttk.LabelFrame(self, text="Global")
        f.grid(row=0, column=0, sticky="ew")
        ttk.Label(f, text="Output root").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(f, textvariable=self.var_out, width=56).grid(row=0, column=1, padx=6, pady=6, sticky="we")
        ttk.Button(f, text="Browse", command=self._choose_out).grid(row=0, column=2, padx=6, pady=6)

    def _choose_out(self):
        d = filedialog.askdirectory(title="Choose output root")
        if d:
            self.var_out.set(d)

    # ---- Workflows ----

    def on_run(self):
        out_root = Path(self.var_out.get().strip())
        if not out_root:
            messagebox.showerror("Output", "Please choose output root.")
            return
        out_root.mkdir(parents=True, exist_ok=True)

        try:
            # 405 first (so XML errors appear early)
            self._process_405(out_root)
            # others
            for title, ch, wl in [
                ("ex488", self.ch488, 488),
                ("ex561", self.ch561, 561),
                ("ex647", self.ch647, 647),
                ("ex730", self.ch730, 730),
            ]:
                self._stack_unmixed_channel(out_root, title, ch, wl)

            self.status.set("Done.")
            messagebox.showinfo("Finished", "All tasks completed.")
        except Exception as e:
            self.status.set("Error.")
            messagebox.showerror("Error", str(e))

    def _process_405(self, out_root: Path):
        p = self.ch405.params()
        folder: Optional[Path] = p["folder"]
        if not folder:
            return
        loops = p["loops"]
        nm_min = p["nm_min"]
        k_first = p["k_first"]
        xml_path = p["xml"]

        if xml_path is None:
            xml_path = find_sidecar_xml_for_any_loop(folder)
        if xml_path is None or not xml_path.exists():
            raise FileNotFoundError("ex405: XML not found (specify in GUI or ensure sidecar .xml exists).")

        xml_wls = parse_xml_wavelengths(xml_path)
        if not xml_wls:
            raise RuntimeError("ex405: No wavelengths found in XML.")
        band_idx = band_indices_for_405(xml_wls, nm_min, k_first)
        if not band_idx:
            raise RuntimeError(f"ex405: No bands with wavelength >= {nm_min} nm.")

        files = sorted_loop_files(folder)
        if not files:
            raise RuntimeError("ex405: No loop files found.")

        out_dir = out_root / "ex405"
        singles_dir = out_dir / "Singles"
        out_dir.mkdir(parents=True, exist_ok=True)
        if p["save_singles"]:
            singles_dir.mkdir(parents=True, exist_ok=True)

        frames = []
        count = 0
        for f in files:
            if count >= loops:
                break
            stack = read_tiff_as_stack(f)
            # guard band range
            idx = [i for i in band_idx if 0 <= i < stack.shape[0]]
            if not idx:
                print(f"[ex405] skip {f.name}: no valid bands at selected nm range.")
                continue
            avg2d = average_bands(stack, idx)
            # keep float32 for averaged results
            avg2d = avg2d.astype(np.float32)
            frames.append(avg2d)
            count += 1
            if p["save_singles"]:
                out_single = singles_dir / f"ex405_avg_{f.stem}.tif"
                tiff.imwrite(str(out_single), avg2d, photometric="minisblack")

        if not frames:
            print("[ex405] No averaged frames to stack.")
            return

        stack = np.stack(frames, axis=0)  # (Z,H,W)
        out_stack = out_dir / f"ex405_avg_loop1-{count}.tif"
        tiff.imwrite(
            str(out_stack),
            stack,
            photometric="minisblack",
            imagej=True,
            bigtiff=bigtiff_needed(stack.nbytes),
            compression=None,
            metadata=None,
        )
        print(f"[ex405] stacked -> {out_stack} | shape={stack.shape} | dtype={stack.dtype}")

    def _stack_unmixed_channel(self, out_root: Path, title: str, ch: ChannelStackUI, wl: int):
        p = ch.params()
        folder: Optional[Path] = p["folder"]
        if not folder:
            return
        loops = p["loops"]
        label_regex = p["label_regex"]
        save_singles = p["save_singles"]

        files = sorted_loop_files(folder)
        if not files:
            print(f"[{title}] no loop files.")
            return

        # Detect labels by filename prefix before first underscore,
        # e.g., "Cy3_Extracted_loop5_561nm_object_300ms.tif"
        labels = {}
        for f in files:
            name = f.name
            if f".{wl}nm" not in name and f"_{wl}nm" not in name:
                # allow any; if you want strict filtering, uncomment next line:
                # continue
                pass
            # label = part before first underscore; fallback: 'unknown'
            parts = name.split("_")
            label = parts[0] if len(parts) > 1 else "unknown"
            if label_regex:
                try:
                    if not re.search(label_regex, label):
                        continue
                except re.error as e:
                    raise ValueError(f"Invalid label regex: {e}")
            labels.setdefault(label, []).append(f)

        if not labels:
            print(f"[{title}] no labels matched.")
            return

        base_out = out_root / f"ex{wl}"
        base_out.mkdir(parents=True, exist_ok=True)

        for label, flist in labels.items():
            # sort again by loop index
            pairs = []
            for f in flist:
                m = LOOP_RE.search(f.name)
                if not m:
                    continue
                num = int(m.group("num"))
                pairs.append((num, f))
            pairs.sort(key=lambda x: x[0])

            frames = []
            count = 0
            singles_dir = base_out / label / "Singles"
            (base_out / label).mkdir(parents=True, exist_ok=True)
            if save_singles:
                singles_dir.mkdir(parents=True, exist_ok=True)

            for num, f in pairs:
                if count >= loops:
                    break
                arr = tiff.imread(str(f))
                if arr.ndim == 3:
                    # If a stack slipped in, take first page
                    arr = arr[0]
                frames.append(arr)
                count += 1
                if save_singles:
                    out_single = singles_dir / f"{label}_{f.stem}.tif"
                    tiff.imwrite(str(out_single), arr, photometric="minisblack")

            if not frames:
                continue

            # Stack preserving dtype
            stack = np.stack(frames, axis=0)
            out_stack = base_out / label / f"{label}_loop1-{count}_stack.tif"
            tiff.imwrite(
                str(out_stack),
                stack,
                photometric="minisblack",
                imagej=True,
                bigtiff=bigtiff_needed(stack.nbytes),
                compression=None,
                metadata=None,
            )
            print(f"[ex{wl}] {label}: -> {out_stack} | shape={stack.shape} | dtype={stack.dtype}")

def main():
    root = tk.Tk()
    try:
        root.call("source", "azure.tcl"); root.call("set_theme", "light")
    except Exception:
        pass
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()