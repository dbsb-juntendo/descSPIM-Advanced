# -*- coding: utf-8 -*-
"""
Created on Tue Sep  2 15:22:13 2025

@author: Seika2
"""

import os
import shutil
import cv2
import numpy as np
import tifffile
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import List

class ECCRegistrationGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("ECC Registration Tool")
        self.root.geometry("800x600")
        
        # Variables
        self.fixed_image_path = tk.StringVar()
        self.reference_image_path = tk.StringVar()
        self.moving_images = []
        self.output_dir = tk.StringVar()
        
        self.create_widgets()
    
    def create_widgets(self):
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Title
        title_label = ttk.Label(main_frame, text="ECC Registration Tool",
                                font=("Arial", 16, "bold"))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20), sticky="w")
        
        # Fixed image (template)
        ttk.Label(main_frame, text="Fixed Image (Template):").grid(row=1, column=0, sticky="w", pady=(10, 5))
        
        fixed_frame = ttk.Frame(main_frame)
        fixed_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        
        ttk.Entry(fixed_frame, textvariable=self.fixed_image_path, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(fixed_frame, text="Browse", command=self.select_fixed_image).pack(side="right", padx=(10, 0))
        
        # Reference image (for ECC calculation)
        ttk.Label(main_frame, text="Reference Image (for ECC matrix calculation):").grid(row=3, column=0, sticky="w", pady=(10, 5))
        
        ref_frame = ttk.Frame(main_frame)
        ref_frame.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        
        ttk.Entry(ref_frame, textvariable=self.reference_image_path, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(ref_frame, text="Browse", command=self.select_reference_image).pack(side="right", padx=(10, 0))
        
        # Moving images list
        ttk.Label(main_frame, text="Moving Images (to apply ECC matrix):").grid(row=5, column=0, sticky="w", pady=(10, 5))
        
        self.moving_listbox = tk.Listbox(main_frame, height=6, width=80)
        self.moving_listbox.grid(row=6, column=0, columnspan=2, pady=(0, 10), sticky="ew")
        
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=6, column=2, padx=(10, 0), sticky="n")
        
        ttk.Button(btn_frame, text="Add Files", command=self.add_moving_files).pack(pady=2, fill="x")
        ttk.Button(btn_frame, text="Remove", command=self.remove_moving_files).pack(pady=2, fill="x")
        ttk.Button(btn_frame, text="Clear All", command=self.clear_moving_files).pack(pady=2, fill="x")
        
        # Output directory
        ttk.Label(main_frame, text="Output Directory:").grid(row=7, column=0, sticky="w", pady=(10, 5))
        
        output_frame = ttk.Frame(main_frame)
        output_frame.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        
        ttk.Entry(output_frame, textvariable=self.output_dir, width=60).pack(side="left", fill="x", expand=True)
        ttk.Button(output_frame, text="Browse", command=self.select_output_dir).pack(side="right", padx=(10, 0))
        
        # (ECC Options removed — params are fixed internally)
        
        # Run button
        ttk.Button(main_frame, text="Start ECC Registration",
                   command=self.start_processing).grid(row=10, column=0, columnspan=3, pady=20)
        
        # Log display
        ttk.Label(main_frame, text="Log:").grid(row=11, column=0, sticky="w")
        self.log_text = tk.Text(main_frame, height=8, width=80)
        self.log_text.grid(row=12, column=0, columnspan=3, sticky="ew")
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=12, column=3, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        
        # Grid config
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(12, weight=1)
        fixed_frame.columnconfigure(0, weight=1)
        ref_frame.columnconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
    
    def select_fixed_image(self):
        file = filedialog.askopenfilename(
            title="Select fixed image (template)",
            filetypes=[("TIFF files", "*.tif *.tiff"), ("All files", "*.*")]
        )
        if file:
            self.fixed_image_path.set(file)
    
    def select_reference_image(self):
        file = filedialog.askopenfilename(
            title="Select reference image for ECC calculation",
            filetypes=[("TIFF files", "*.tif *.tiff"), ("All files", "*.*")]
        )
        if file:
            self.reference_image_path.set(file)
    
    def add_moving_files(self):
        files = filedialog.askopenfilenames(
            title="Select moving images",
            filetypes=[("TIFF files", "*.tif *.tiff"), ("All files", "*.*")]
        )
        for file in files:
            if file not in self.moving_images:
                self.moving_images.append(file)
                self.moving_listbox.insert(tk.END, Path(file).name)
    
    def remove_moving_files(self):
        selected = self.moving_listbox.curselection()
        for idx in reversed(selected):
            self.moving_listbox.delete(idx)
            self.moving_images.pop(idx)
    
    def clear_moving_files(self):
        self.moving_listbox.delete(0, tk.END)
        self.moving_images.clear()
    
    def select_output_dir(self):
        directory = filedialog.askdirectory(title="Select output directory")
        if directory:
            self.output_dir.set(directory)
    
    def log(self, message):
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update()
    
    def ecc_euclidean(self, mov, fix, n_iter=5000, eps=1e-8):
        """Compute the ECC Euclidean transform matrix (fixed params)."""
        W = np.eye(2, 3, dtype=np.float32)
        criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, n_iter, eps)
        try:
            cv2.findTransformECC(fix, mov, W, cv2.MOTION_EUCLIDEAN, criteria)
        except cv2.error as e:
            self.log(f"ECC calculation failed: {e}")
            raise
        return W
    
    def start_processing(self):
        # Input checks
        if not self.fixed_image_path.get():
            messagebox.showerror("Error", "Please select fixed image")
            return
        if not self.reference_image_path.get():
            messagebox.showerror("Error", "Please select reference image")
            return
        if not self.moving_images:
            messagebox.showerror("Error", "Please select moving images")
            return
        if not self.output_dir.get():
            messagebox.showerror("Error", "Please select output directory")
            return
        
        try:
            # Prepare output directories
            base_dir = Path(self.output_dir.get())
            before_dir = base_dir / "ECC_Euclid_before"
            after_dir = base_dir / "ECC_Euclid_after"
            before_dir.mkdir(parents=True, exist_ok=True)
            after_dir.mkdir(parents=True, exist_ok=True)
            
            self.log("Starting ECC registration process...")
            
            # Paths
            mean_tif = Path(self.fixed_image_path.get())
            ecc_ref_tif = Path(self.reference_image_path.get())
            moving_tifs = [Path(f) for f in self.moving_images]
            
            # 1) Copy originals to the "before" directory
            self.log("Copying original files...")
            for src in [mean_tif] + moving_tifs:
                if src.exists():
                    shutil.copy(src, before_dir / src.name)
            self.log(f"Original TIFFs copied → {before_dir}")
            
            # 2) Calculate ECC matrix using MIP of stacks (if 3D)
            self.log("Loading images for ECC calculation...")
            mean_stack = tifffile.imread(mean_tif)
            ref_stack = tifffile.imread(ecc_ref_tif)
            
            mean_mip = mean_stack.max(axis=0) if mean_stack.ndim == 3 else mean_stack
            ref_mip = ref_stack.max(axis=0) if ref_stack.ndim == 3 else ref_stack
            
            fix = mean_mip.astype(np.float32)
            fix /= (fix.max() or 1)
            mov = ref_mip.astype(np.float32)
            mov /= (mov.max() or 1)
            
            self.log("Calculating ECC matrix with fixed params (iter=5000, eps=1e-8)...")
            W = self.ecc_euclidean(mov, fix, 5000, 1e-8)
            self.log(f"Estimated warp matrix:\n{W}")
            
            # 3) Apply ECC transform to each moving image (per slice if 3D)
            h_fix, w_fix = mean_mip.shape
            
            for mov_tif in moving_tifs:
                self.log(f"Processing: {mov_tif.name}")
                mov_stack = tifffile.imread(mov_tif)
                if mov_stack.ndim == 2:
                    mov_stack = mov_stack[None, ...]
                z, h_src, w_src = mov_stack.shape
                
                aligned = np.empty((z, h_fix, w_fix), dtype=mov_stack.dtype)
                
                for i in range(z):
                    page = mov_stack[i].astype(np.float32)
                    page /= (page.max() or 1)
                    # Convert to 8-bit for warpAffine and write back
                    ali8 = cv2.warpAffine(
                        (page * 255).astype(np.uint8),
                        W, (w_fix, h_fix),
                        flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
                    )
                    aligned[i] = ali8  # stored as uint8; adjust if you wish to preserve original dtype
                
                out_path = after_dir / f"aligned_{mov_tif.name}"
                tifffile.imwrite(
                    out_path, aligned,
                    photometric="minisblack",
                    imagej=True,
                    bigtiff=(aligned.nbytes >= 4 * 1024**3)
                )
                self.log(f"  ✓ saved: {out_path}")
            
            self.log("\nECC registration completed!")
            messagebox.showinfo("Complete", "ECC registration process completed!")
        
        except Exception as e:
            self.log(f"Error: {str(e)}")
            messagebox.showerror("Error", f"An error occurred: {str(e)}")

# GUI launcher
def run_ecc_gui():
    root = tk.Tk()
    app = ECCRegistrationGUI(root)
    root.mainloop()

# Run
run_ecc_gui()
