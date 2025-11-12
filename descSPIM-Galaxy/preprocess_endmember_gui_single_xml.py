# -*- coding: utf-8 -*-
"""
Created on Tue Sep  2 11:57:58 2025

@author: Seika2
"""

"""
preprocess_endmember_gui_single_xml.py
Generalized GUI tool to:
  1) Read a single XML (specified once) to get valid wavelengths
  2) For each excitation (488 / 561 / 647 / 730): crop reference CSVs to wl_min..wl_max
  3) Interpolate cropped spectra to the XML's valid wavelengths

Changes from previous version:
- XML file is specified ONCE (global), used for all channels
- Each channel still has editable wl_min/max and can add multiple CSVs

Dependencies: pandas, numpy, tkinter
"""

import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import numpy as np
from xml.etree import ElementTree as ET
from typing import List, Dict

# ---------------------- Core functions ----------------------

def get_valid_wavelengths(xml_path: str, wl_min: float, wl_max: float) -> List[float]:
    """Parse XML and collect band wavelengths within [wl_min, wl_max]."""
    tree = ET.parse(xml_path)
    root = tree.getroot()
    wavelengths: List[float] = []
    for band in root.findall(".//band"):
        try:
            wl = float(band.attrib.get("wavelength_nm", "0"))
        except ValueError:
            continue
        if wl_min <= wl <= wl_max and wl != 0:
            wavelengths.append(wl)
    wavelengths.sort()
    return wavelengths

def crop_reference_csv(in_path: str, wl_min: float, wl_max: float, out_path: str) -> str | None:
    """Read CSV, drop first 4 columns, keep numeric columns within [wl_min, wl_max]."""
    df = pd.read_csv(in_path)
    if df.shape[1] <= 4:
        print(f"⚠️ {os.path.basename(in_path)} : not enough columns (<=4) – skipped")
        return None

    data = df.iloc[:, 4:]  # drop first 4 metadata columns

    def _is_numeric_col(colname: str) -> bool:
        try:
            float(colname)
            return True
        except Exception:
            return False

    valid_cols = [c for c in data.columns if _is_numeric_col(c) and wl_min <= float(c) <= wl_max]
    if not valid_cols:
        print(f"⚠️ {os.path.basename(in_path)} : no wavelengths in range – skipped")
        return None

    cropped = data[valid_cols]
    cropped.to_csv(out_path, index=False)
    print(f"  ✅ Cropped → {out_path}")
    return out_path

def interpolate_to_xml_wavelengths(crop_path: str, xml_wavelengths: List[float], out_path: str):
    """Interpolate each row of cropped CSV to the wavelengths defined by the XML."""
    df = pd.read_csv(crop_path)
    x = np.array([float(c) for c in df.columns], dtype=float)
    out_records = []
    for _, row in df.iterrows():
        y = row.to_numpy(dtype=float)
        y_interp = np.interp(xml_wavelengths, x, y)
        out_records.append(y_interp)

    out_df = pd.DataFrame(out_records, columns=[f"{w:.2f}" for w in xml_wavelengths])
    out_df.to_csv(out_path, index=False)
    print(f"  ✅ Interpolated → {out_path}")

# ---------------------- GUI application ----------------------

DEFAULTS = {
    488: dict(wl_min=500.0, wl_max=700.0),
    561: dict(wl_min=575.0, wl_max=840.0),
    647: dict(wl_min=675.0, wl_max=900.0),
    730: dict(wl_min=750.0, wl_max=900.0),
}

class ChannelUI(ttk.LabelFrame):
    """Per-excitation UI block with: wl_min/max, CSV list (XML is global)."""
    def __init__(self, master, wavelength: int):
        super().__init__(master, text=f"ex{wavelength}")
        self.wl = wavelength

        # Variables
        self.var_min = tk.DoubleVar(value=DEFAULTS[wavelength]["wl_min"])
        self.var_max = tk.DoubleVar(value=DEFAULTS[wavelength]["wl_max"])

        # Selected CSV files list
        self.csv_files: List[str] = []

        # Layout
        self._build()

    def _build(self):
        pad = {"padx": 6, "pady": 3}

        # wl_min / wl_max
        row = 0
        ttk.Label(self, text="wl_min").grid(row=row, column=0, sticky="e", **pad)
        ttk.Entry(self, textvariable=self.var_min, width=10).grid(row=row, column=1, sticky="w", **pad)
        ttk.Label(self, text="wl_max").grid(row=row, column=2, sticky="e", **pad)
        ttk.Entry(self, textvariable=self.var_max, width=10).grid(row=row, column=3, sticky="w", **pad)

        # CSV file list and buttons
        row += 1
        self.listbox = tk.Listbox(self, height=5, width=70)
        self.listbox.grid(row=row, column=0, columnspan=4, sticky="we", **pad)

        row += 1
        btns = ttk.Frame(self)
        btns.grid(row=row, column=0, columnspan=4, sticky="w", **pad)
        ttk.Button(btns, text="Add CSVs…", command=self._add_csvs).grid(row=0, column=0, padx=4)
        ttk.Button(btns, text="Remove selected", command=self._remove_selected).grid(row=0, column=1, padx=4)
        ttk.Button(btns, text="Clear list", command=self._clear).grid(row=0, column=2, padx=4)

    def _add_csvs(self):
        files = filedialog.askopenfilenames(
            title=f"Add CSV reference files (ex{self.wl})",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if files:
            for f in files:
                if f not in self.csv_files:
                    self.csv_files.append(f)
                    self.listbox.insert(tk.END, f)

    def _remove_selected(self):
        sel = list(self.listbox.curselection())
        sel.reverse()
        for idx in sel:
            path = self.listbox.get(idx)
            if path in self.csv_files:
                self.csv_files.remove(path)
            self.listbox.delete(idx)

    def _clear(self):
        self.csv_files.clear()
        self.listbox.delete(0, tk.END)

    def params(self) -> Dict:
        return dict(
            wl=self.wl,
            wl_min=float(self.var_min.get()),
            wl_max=float(self.var_max.get()),
            csvs=list(self.csv_files),
        )

class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        master.title("Endmember CSV Crop & Interpolate — single XML for all (488 / 561 / 647 / 730)")
        master.protocol("WM_DELETE_WINDOW", master.destroy)
        self.grid(padx=10, pady=10, sticky="nsew")

        # Output root + Global XML
        self.var_out = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "endmember_preprocessed"))
        self.var_xml = tk.StringVar(value="")
        self._build_header()

        # Four channels
        self.channels = {}
        row = 1
        for wl in (488, 561, 647, 730):
            ch = ChannelUI(self, wl)
            ch.grid(row=row, column=0, sticky="nsew", pady=(6, 2))
            self.channels[wl] = ch
            row += 1

        # Run button
        runf = ttk.Frame(self)
        runf.grid(row=row, column=0, sticky="e", pady=(8, 0))
        ttk.Button(runf, text="Run", command=self.on_run).grid(row=0, column=0, padx=6)
        ttk.Button(runf, text="Quit", command=self.master.destroy).grid(row=0, column=1, padx=6)

        # Status
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status).grid(row=row+1, column=0, sticky="w", pady=(6, 0))

    def _build_header(self):
        f = ttk.LabelFrame(self, text="Global Settings")
        f.grid(row=0, column=0, sticky="ew")
        # Output root
        ttk.Label(f, text="Output root").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(f, textvariable=self.var_out, width=60).grid(row=0, column=1, padx=6, pady=6)
        ttk.Button(f, text="Browse", command=self._choose_out).grid(row=0, column=2, padx=6, pady=6)
        # Single XML
        ttk.Label(f, text="XML file (used for all channels)").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(f, textvariable=self.var_xml, width=60).grid(row=1, column=1, padx=6, pady=6)
        ttk.Button(f, text="Browse", command=self._choose_xml).grid(row=1, column=2, padx=6, pady=6)

    def _choose_out(self):
        d = filedialog.askdirectory(title="Choose output root")
        if d:
            self.var_out.set(d)

    def _choose_xml(self):
        f = filedialog.askopenfilename(title="Choose XML",
                                       filetypes=[("XML files", "*.xml"), ("All files", "*.*")])
        if f:
            self.var_xml.set(f)

    def on_run(self):
        out_root = self.var_out.get().strip()
        xml_path = self.var_xml.get().strip()

        if not out_root:
            messagebox.showerror("Output", "Please choose an output root.")
            return
        if not xml_path:
            messagebox.showerror("XML", "Please choose the XML file (used for all channels).")
            return

        # Check that we have at least one CSV
        any_files = any(ch.csv_files for ch in self.channels.values())
        if not any_files:
            messagebox.showwarning("No input", "No CSVs provided. Add CSV files for at least one excitation.")
            return

        # Process each channel
        try:
            for wl, ch in self.channels.items():
                p = ch.params()
                csvs   = p["csvs"]
                if not csvs:
                    continue

                wl_min = p["wl_min"]
                wl_max = p["wl_max"]

                # Create subfolder
                wl_out = os.path.join(out_root, f"ex{wl}")
                os.makedirs(wl_out, exist_ok=True)

                # Parse XML wavelengths for this channel's range
                try:
                    xml_wavelengths = get_valid_wavelengths(xml_path, wl_min, wl_max)
                except Exception as e:
                    messagebox.showerror(f"ex{wl} XML", f"Failed to parse XML: {e}")
                    return
                if not xml_wavelengths:
                    messagebox.showwarning(f"ex{wl}", "No valid wavelengths in the specified range. Skipped.")
                    continue

                # Process CSVs
                for in_csv in csvs:
                    fname = os.path.basename(in_csv)
                    crop_out   = os.path.join(wl_out, f"Crop_{fname}")
                    interp_out = os.path.join(wl_out, f"Interp_crop_{fname}")

                    # Crop
                    cropped_path = crop_reference_csv(in_csv, wl_min, wl_max, crop_out)
                    if not cropped_path:
                        continue
                    # Interpolate
                    try:
                        interpolate_to_xml_wavelengths(cropped_path, xml_wavelengths, interp_out)
                    except Exception as e:
                        print(f"❌ Interp failed for {fname}: {e}")

            self.status.set("Done. See output folders for results.")
            messagebox.showinfo("Finished", "All selected CSVs have been processed.")

        except Exception as e:
            self.status.set("Error occurred.")
            messagebox.showerror("Error", str(e))

def main():
    root = tk.Tk()
    try:
        root.call("source", "azure.tcl")
        root.call("set_theme", "light")
    except Exception:
        pass
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
