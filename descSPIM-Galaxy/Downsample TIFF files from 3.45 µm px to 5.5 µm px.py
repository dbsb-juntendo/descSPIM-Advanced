# -*- coding: utf-8 -*-
"""
Created on Tue Sep  2 15:21:44 2025

@author: Seika2
"""

import os
import cv2
import tifffile as tiff
import numpy as np
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from typing import List

class DownsampleGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("TIFF Downsampling: 3.45 µm/px → 5.5 µm/px")
        self.root.geometry("700x500")
        
        # Fixed values
        self.SCALE = 5.5 / 3.45  # ≈1.5943
        
        # Variables
        self.input_files = []
        self.output_dir = tk.StringVar()
        
        self.create_widgets()
    
    def create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="TIFF Downsampling Tool", 
                               font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20), sticky="w")
        
        # Scale information
        scale_label = ttk.Label(main_frame, 
                               text=f"Scale: 3.45 µm/px → 5.5 µm/px (ratio: {self.SCALE:.4f})")
        scale_label.grid(row=1, column=0, columnspan=3, pady=(0, 10), sticky="w")
        
        # Input files
        ttk.Label(main_frame, text="Input TIFF Files:").grid(row=2, column=0, sticky="w", pady=(10, 5))
        
        # File list
        self.file_listbox = tk.Listbox(main_frame, height=8, width=80)
        self.file_listbox.grid(row=3, column=0, columnspan=2, pady=(0, 10), sticky="ew")
        
        # File operation buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=3, column=2, padx=(10, 0), sticky="n")
        
        ttk.Button(btn_frame, text="Add Files", command=self.add_files).pack(pady=2, fill="x")
        ttk.Button(btn_frame, text="Remove", command=self.remove_files).pack(pady=2, fill="x")
        ttk.Button(btn_frame, text="Clear All", command=self.clear_files).pack(pady=2, fill="x")
        
        # Output directory
        ttk.Label(main_frame, text="Output Directory:").grid(row=4, column=0, sticky="w", pady=(10, 5))
        
        output_frame = ttk.Frame(main_frame)
        output_frame.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        
        ttk.Entry(output_frame, textvariable=self.output_dir, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(output_frame, text="Browse", command=self.select_output_dir).pack(side="right", padx=(10, 0))
        
        # Run button
        ttk.Button(main_frame, text="Start Downsampling", 
                  command=self.start_processing).grid(row=6, column=0, columnspan=3, pady=20)
        
        # Log display
        ttk.Label(main_frame, text="Log:").grid(row=7, column=0, sticky="w")
        self.log_text = tk.Text(main_frame, height=8, width=80)
        self.log_text.grid(row=8, column=0, columnspan=3, sticky="ew")
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=8, column=3, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        # Grid configuration
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(8, weight=1)
        output_frame.columnconfigure(0, weight=1)
    
    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Select TIFF files",
            filetypes=[("TIFF files", "*.tif *.tiff"), ("All files", "*.*")]
        )
        for file in files:
            if file not in self.input_files:
                self.input_files.append(file)
                self.file_listbox.insert(tk.END, Path(file).name)
    
    def remove_files(self):
        selected = self.file_listbox.curselection()
        for idx in reversed(selected):
            self.file_listbox.delete(idx)
            self.input_files.pop(idx)
    
    def clear_files(self):
        self.file_listbox.delete(0, tk.END)
        self.input_files.clear()
    
    def select_output_dir(self):
        directory = filedialog.askdirectory(title="Select output directory")
        if directory:
            self.output_dir.set(directory)
    
    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update()
    
    def downsample_tiff(self, src_path: Path, scale: float, dst_folder: Path) -> None:
        """Downsample a multipage TIFF by the given scale and save it"""
        try:
            with tiff.TiffFile(src_path) as tif:
                pages = [p.asarray() for p in tif.pages]

            stack = np.stack(pages) if len(pages) > 1 else pages[0][None, ...]
            z, h, w = stack.shape
            new_h, new_w = int(round(h / scale)), int(round(w / scale))

            self.log(f"{src_path.name}: {z} pages  {h}x{w}px  ->  {new_h}x{new_w}px")

            out = np.empty((z, new_h, new_w), dtype=stack.dtype)
            for i in range(z):
                out[i] = cv2.resize(stack[i], (new_w, new_h), interpolation=cv2.INTER_AREA)

            dst_path = dst_folder / f"{src_path.stem}_binned_5p5um.tif"
            tiff.imwrite(
                dst_path,
                out,
                photometric="minisblack",
                imagej=True,
                bigtiff=(out.nbytes >= 4 * 1024**3),
                compression=None,
                metadata=None,
            )
            self.log(f"  ✓ saved: {dst_path}")
            
        except Exception as e:
            self.log(f"  ❌ Error processing {src_path.name}: {str(e)}")
    
    def start_processing(self):
        if not self.input_files:
            messagebox.showerror("Error", "Please select input files")
            return
        
        if not self.output_dir.get():
            messagebox.showerror("Error", "Please select output directory")
            return
        
        dst_dir = Path(self.output_dir.get())
        dst_dir.mkdir(exist_ok=True)
        
        self.log("Starting downsampling process...")
        
        for src_file in self.input_files:
            src_path = Path(src_file)
            if not src_path.exists():
                self.log(f"⚠ missing: {src_path}")
                continue
            self.downsample_tiff(src_path, self.SCALE, dst_dir)
        
        self.log("Downsampling finished.")
        messagebox.showinfo("Complete", "Downsampling process completed!")

# GUI launcher
def run_downsample_gui():
    root = tk.Tk()
    app = DownsampleGUI(root)
    root.mainloop()

# Run
run_downsample_gui()
