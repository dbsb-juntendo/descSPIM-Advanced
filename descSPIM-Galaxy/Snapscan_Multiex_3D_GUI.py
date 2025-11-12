# -*- coding: utf-8 -*-
"""
Snapscan_Multiex_3D_GUI.py
Make all acquisition variables user-settable via GUI and run multi-excitation 3D imaging
(ex647 → ex561 → ex405). Camera step is auto-computed from sample step (×0.342).

What you can set from the GUI:
- IT_MS (loop count N; acquisition runs from loop 1..IT_MS)
- Per-excitation start positions for loop 1:
    START_SAMPLE[647/561/405]   (µm)  ← WRITE YOUR MEASURED FOCUS HERE
    START_CAMERA[647/561/405]   (µm)  ← WRITE YOUR MEASURED FOCUS HERE
- SAMPLE_STEP_UM (camera step = sample step × 0.342, auto)
- SAVE_ROOT, device ports/paths (Kinesis FW SN, COM ports, XML/CFG)

Acquisition order and rationale:
- Imaging proceeds from the longest to the shortest wavelength (647 → 561 → 405 nm)
  to minimize photobleaching from shorter-wavelength excitation.

Notes:
- If execution appears unstable, please prioritize running the corresponding .py file directly in your local environment instead of the .ipynb in Jupyter Notebook.

"""

import os
import sys
import time
import threading
import logging
import serial
from pathlib import Path
from typing import Tuple, Optional, Dict

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# pymmcore-plus & imec HSI Snapscan APIs
from pymmcore_plus import CMMCorePlus

# ---- imec Snapscan Python API path (edit if needed) ----
# You can also expose this via environment or a config field if desired.
SNAPSCAN_API_PATH = r"C:/imec/HSI Snapscan v2.4.13.0/python_apis"
if SNAPSCAN_API_PATH not in sys.path:
    sys.path.insert(0, SNAPSCAN_API_PATH)

import hsi_common as HSI_COMMON           # noqa: E402
import hsi_snapscan as HSI_SNAPSCAN       # noqa: E402
from hsi_common.hsi_common_types import FileFormat   # noqa: E402

# ============== Logging (file rotates per SAVE_ROOT) ==============
def setup_logging(save_root: Path):
    save_root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(save_root / "script_execution.log", encoding="utf-8", mode="a")
        ],
    )

# ==================== Hardware Interfaces ====================
import clr    # noqa: E402
from System import Decimal   # noqa: E402

# Adjust Kinesis® DLL path if needed
KINESIS_DLL_ROOT = r"C:/Program Files/Thorlabs/Kinesis"
clr.AddReference(os.path.join(KINESIS_DLL_ROOT, "Thorlabs.MotionControl.DeviceManagerCLI.dll"))
clr.AddReference(os.path.join(KINESIS_DLL_ROOT, "Thorlabs.MotionControl.KCube.StepperMotorCLI.dll"))
from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI, DeviceConfiguration   # noqa: E402
from Thorlabs.MotionControl.KCube.StepperMotorCLI import KCubeStepper                      # noqa: E402

# Filter positions (wavelength → absolute angle [deg])
FILTER_POS = {
    405: Decimal(0),
    488: Decimal(60),
    515: Decimal(120),
    561: Decimal(180),
    647: Decimal(240),
    730: Decimal(300),
}

class FilterWheel:
    def __init__(self, sn: str):
        DeviceManagerCLI.BuildDeviceList()
        self.dev = KCubeStepper.CreateKCubeStepper(sn)
        self.dev.Connect(sn)
        self.dev.LoadMotorConfiguration(sn, DeviceConfiguration.DeviceSettingsUseOptionType.UseFileSettings)
        self.dev.StartPolling(250); time.sleep(0.5)
        self.dev.EnableDevice();     time.sleep(0.5)
        self.dev.Home(60000);        time.sleep(0.5)
        logging.info("Filter-wheel homed")

    def move(self, wl: int):
        logging.info(f"Rotating filter-wheel to {wl} nm position")
        self.dev.SetMoveAbsolutePosition(FILTER_POS[wl]); self.dev.MoveAbsolute(60000)

    def close(self):
        try:
            self.dev.StopPolling()
        finally:
            self.dev.Disconnect()
        logging.info("Filter-wheel disconnected")

class CoboltCFLEX:
    def __init__(self, port: str, wl: int):
        self.port = port
        self.wl = wl
        self.ser: Optional[serial.Serial] = None

    def _connect(self):
        if not self.ser or not self.ser.is_open:
            self.ser = serial.Serial(self.port, 115200, timeout=1); time.sleep(0.5)

    def _w(self, cmd: str): 
        self.ser.write(f"{cmd}\r".encode()); time.sleep(0.1)

    def on(self):
        self._connect(); self._w("l1"); logging.info(f"C-FLEX {self.wl} nm ON")

    def off(self):
        if self.ser and self.ser.is_open: self._w("l0")
        logging.info(f"C-FLEX {self.wl} nm OFF")

    def close(self):
        try: self.off()
        except Exception: pass
        try:
            if self.ser: self.ser.close()
        except Exception: pass
        logging.info("C-FLEX serial closed")

class CoboltSkyra:
    MAP = {561: 1, 647: 2, 515: 3, 488: 4}  # line index mapping
    def __init__(self, port: str):
        self.port = port
        self.ser: Optional[serial.Serial] = None

    def _connect(self):
        if not self.ser or not self.ser.is_open:
            self.ser = serial.Serial(self.port, 115200, timeout=1); time.sleep(0.5)

    def _w(self, cmd: str): 
        self.ser.write(f"{cmd}\r".encode()); time.sleep(0.1)

    def on(self, wl: int):
        """Enable a Skyra line. (Assumes power is set elsewhere if needed.)"""
        self._connect(); self._w(f"{self.MAP[wl]}l1"); logging.info(f"Skyra {wl} nm ON")

    def off(self, wl: int):
        self._connect(); self._w(f"{self.MAP[wl]}l0"); logging.info(f"Skyra {wl} nm OFF")

    def all_off(self):
        for wl in self.MAP:
            try: self.off(wl)
            except Exception: pass

    def close(self):
        try: self.all_off()
        except Exception: pass
        try:
            if self.ser: self.ser.close()
        except Exception: pass
        logging.info("Skyra serial closed")

def all_off(sky: CoboltSkyra, cf: Dict[int, CoboltCFLEX]):
    """Turn off all lasers."""
    try: sky.all_off()
    except Exception: pass
    for dev in cf.values():
        try: dev.off()
        except Exception: pass
    logging.info("All lasers OFF")

# ==================== Snapscan helpers ====================
def init_camera(XML_CAMERA: Path, INTEGRATION_MS: int) -> int:
    handle = HSI_SNAPSCAN.OpenDevice(str(XML_CAMERA), dummy_api=False)
    cfg = HSI_SNAPSCAN.GetConfigurationParameters(handle)
    cfg.cube_height, cfg.cube_width, cfg.tdi_pixel_step = 1088, 2048, 5  # tune as needed
    HSI_SNAPSCAN.SetConfigurationParameters(handle, cfg)
    HSI_SNAPSCAN.Initialize(handle)
    rt = HSI_SNAPSCAN.GetRuntimeParameters(handle)
    rt.integration_time_ms = INTEGRATION_MS
    HSI_SNAPSCAN.SetRuntimeParameters(handle, rt)
    logging.info(f"Snapscan camera ready (integration_time_ms={INTEGRATION_MS})")
    return handle

def wait_stage(mmc: CMMCorePlus, label: str):
    while mmc.deviceBusy(label):
        time.sleep(0.2)

def move_to_loop(mmc: CMMCorePlus, wl: int, loop_idx: int,
                 START_SAMPLE: Dict[int, float], START_CAMERA: Dict[int, float],
                 SAMPLE_STEP_UM: float, CAMERA_STEP_UM: float):
    """Move to the sample/camera positions for this excitation and loop index."""
    sample = START_SAMPLE[wl] + SAMPLE_STEP_UM * (loop_idx - 1)
    camera = START_CAMERA[wl] + CAMERA_STEP_UM * (loop_idx - 1)
    mmc.setPosition("sampleStage", sample)
    mmc.setPosition("cameraStage", camera)
    wait_stage(mmc, "sampleStage"); wait_stage(mmc, "cameraStage")
    logging.info(f"[{wl} nm] Stage → loop{loop_idx}: sample={sample:.2f} µm, camera={camera:.2f} µm")

def capture_reference(handle: int, wl: int) -> Tuple[int, int, int]:
    """Capture Dark + White + Correction at loop1 and keep device RUNNING."""
    logging.info(f"[{wl} nm] Capturing reference at loop1 (device stays RUNNING)")
    HSI_SNAPSCAN.Start(handle)
    dark  = HSI_SNAPSCAN.AcquireDarkReferenceFrame(handle)
    white = HSI_SNAPSCAN.AcquireCube(handle, dark)
    corr  = HSI_SNAPSCAN.GetCorrectionMatrix(handle)
    white_c = HSI_SNAPSCAN.ApplySpectralCorrection(white, corr)
    HSI_COMMON.DeallocateCube(white)
    logging.info(f"[{wl} nm] Reference captured")
    return dark, white_c, corr

def acquire_cube(handle: int, wl: int, lp: int, dark: int, white_c: int, corr: int, out_dir: Path, it_ms_label: str):
    cube = HSI_SNAPSCAN.AcquireCube(handle, dark)
    prefix = f"loop{lp}_{wl}nm"
    HSI_COMMON.SaveCube(cube, str(out_dir), f"{prefix}_object_{it_ms_label}", FileFormat.FF_TIFF)
    cube_c = HSI_SNAPSCAN.ApplySpectralCorrection(cube, corr); HSI_COMMON.DeallocateCube(cube)
    refl   = HSI_SNAPSCAN.ApplyWhiteReference(cube_c, white_c)
    HSI_COMMON.SaveCube(refl, str(out_dir), f"{prefix}_reflectance_{it_ms_label}", FileFormat.FF_TIFF)
    HSI_COMMON.DeallocateCube(cube_c); HSI_COMMON.DeallocateCube(refl)

def run_one_excitation(
    mmc: CMMCorePlus,
    handle: int,
    fw: FilterWheel,
    sky: CoboltSkyra,
    cflex: Dict[int, CoboltCFLEX],
    wl: int,
    it_ms: int,
    out_root: Path,
    START_SAMPLE: Dict[int, float],
    START_CAMERA: Dict[int, float],
    SAMPLE_STEP_UM: float,
    CAMERA_STEP_UM: float,
):
    """Acquire 1..it_ms loops for a single excitation `wl`."""
    # Safety: all lasers OFF → rotate filter
    all_off(sky, cflex)
    fw.move(wl)

    # Laser ON
    if wl in cflex:
        cflex[wl].on()           # CFLEX line (e.g., 405)
    else:
        sky.on(wl)               # Skyra line (e.g., 561, 647) — assumes power set elsewhere

    # Output folder
    out_dir = out_root / f"ex{wl}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Reference at loop1
    move_to_loop(mmc, wl, 1, START_SAMPLE, START_CAMERA, SAMPLE_STEP_UM, CAMERA_STEP_UM)
    dark, white_c, corr = capture_reference(handle, wl)

    # Continuous loops
    it_ms_label = f"{it_ms}loops"  # clarify in filenames (e.g., 300loops)
    for lp in range(1, it_ms + 1):
        if lp != 1:
            move_to_loop(mmc, wl, lp, START_SAMPLE, START_CAMERA, SAMPLE_STEP_UM, CAMERA_STEP_UM)
        acquire_cube(handle, wl, lp, dark, white_c, corr, out_dir, it_ms_label)
        time.sleep(0.2)

    # Free reference buffers
    try:
        HSI_COMMON.DeallocateFrame(dark)
        HSI_COMMON.DeallocateCube(white_c)
        HSI_SNAPSCAN.DeallocateCorrectionMatrix(corr)
    except Exception:
        pass

    # Laser OFF for the next excitation
    all_off(sky, cflex)

# ==================== GUI Application ====================
class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        master.title("Snapscan Multi-Excitation 3D Imaging")
        master.protocol("WM_DELETE_WINDOW", self.on_quit)

        # ----- Input variables (Tk Variables) -----
        self.v_save_root = tk.StringVar(value=r"E:/250609_trial_of_7_color_imaging")
        self.v_it_ms = tk.IntVar(value=300)
        self.v_integration_ms = tk.IntVar(value=300)

        self.v_sample_step = tk.DoubleVar(value=20.0)
        self.v_camera_step = tk.DoubleVar(value=20.0 * 0.342)  # auto

        # per-excitation start positions (WRITE YOUR MEASURED FOCUS HERE)
        self.v_start_sample_647 = tk.DoubleVar(value=12716.92)
        self.v_start_camera_647 = tk.DoubleVar(value=19558.64)
        self.v_start_sample_561 = tk.DoubleVar(value=12716.92)
        self.v_start_camera_561 = tk.DoubleVar(value=19558.64)
        self.v_start_sample_405 = tk.DoubleVar(value=12716.92)
        self.v_start_camera_405 = tk.DoubleVar(value=19558.64)

        # Devices / ports / paths
        self.v_fw_sn = tk.StringVar(value="26006126")
        self.v_port_cflex_405 = tk.StringVar(value="COM3")
        self.v_port_skyra = tk.StringVar(value="COM6")
        self.v_xml_camera = tk.StringVar(value=r"F:/cfg/B150U-0035.xml")
        self.v_cfg_mm = tk.StringVar(value=r"F:/cfg/241130_stage_YN.cfg")

        # State
        self._running = False
        self._worker: Optional[threading.Thread] = None

        # UI
        self._build_widgets()
        self.grid(padx=10, pady=10)

        # auto-update camera step when sample step changes
        self.v_sample_step.trace_add("write", self._update_camera_step)

    # ---------- UI builder ----------
    def _build_widgets(self):
        pad = {"padx": 8, "pady": 4}

        # Paths
        f_paths = ttk.LabelFrame(self, text="Paths")
        f_paths.grid(row=0, column=0, sticky="nsew", **pad)
        ttk.Label(f_paths, text="SAVE_ROOT").grid(row=0, column=0, sticky="e")
        ttk.Entry(f_paths, textvariable=self.v_save_root, width=48).grid(row=0, column=1, sticky="we")
        ttk.Button(f_paths, text="Browse", command=self._choose_save_root).grid(row=0, column=2, sticky="w")

        ttk.Label(f_paths, text="XML_CAMERA").grid(row=1, column=0, sticky="e")
        ttk.Entry(f_paths, textvariable=self.v_xml_camera, width=48).grid(row=1, column=1, sticky="we")
        ttk.Button(f_paths, text="Browse", command=lambda: self._choose_file(self.v_xml_camera)).grid(row=1, column=2)

        ttk.Label(f_paths, text="CFG_MM").grid(row=2, column=0, sticky="e")
        ttk.Entry(f_paths, textvariable=self.v_cfg_mm, width=48).grid(row=2, column=1, sticky="we")
        ttk.Button(f_paths, text="Browse", command=lambda: self._choose_file(self.v_cfg_mm)).grid(row=2, column=2)

        # Acquisition
        f_acq = ttk.LabelFrame(self, text="Acquisition")
        f_acq.grid(row=1, column=0, sticky="nsew", **pad)
        ttk.Label(f_acq, text="IT_MS (loop count N)").grid(row=0, column=0, sticky="e")
        ttk.Entry(f_acq, textvariable=self.v_it_ms, width=10).grid(row=0, column=1, sticky="w")
        ttk.Label(f_acq, text="Integration (ms)").grid(row=0, column=2, sticky="e")
        ttk.Entry(f_acq, textvariable=self.v_integration_ms, width=10).grid(row=0, column=3, sticky="w")

        ttk.Label(f_acq, text="Sample step (µm)").grid(row=1, column=0, sticky="e")
        ttk.Entry(f_acq, textvariable=self.v_sample_step, width=10).grid(row=1, column=1, sticky="w")
        ttk.Label(f_acq, text="Camera step (µm) = sample × 0.342").grid(row=1, column=2, sticky="e")
        e_cam = ttk.Entry(f_acq, textvariable=self.v_camera_step, width=12, state="readonly")
        e_cam.grid(row=1, column=3, sticky="w")

        # Start positions per excitation (WRITE YOUR MEASURED FOCUS HERE)
        f_pos = ttk.LabelFrame(self, text="Start positions for loop 1 (WRITE YOUR MEASURED FOCUS HERE)")
        f_pos.grid(row=2, column=0, sticky="nsew", **pad)
        # 647
        ttk.Label(f_pos, text="ex647 sample Z (µm)").grid(row=0, column=0, sticky="e")
        ttk.Entry(f_pos, textvariable=self.v_start_sample_647, width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(f_pos, text="ex647 camera Z (µm)").grid(row=0, column=2, sticky="e")
        ttk.Entry(f_pos, textvariable=self.v_start_camera_647, width=12).grid(row=0, column=3, sticky="w")
        # 561
        ttk.Label(f_pos, text="ex561 sample Z (µm)").grid(row=1, column=0, sticky="e")
        ttk.Entry(f_pos, textvariable=self.v_start_sample_561, width=12).grid(row=1, column=1, sticky="w")
        ttk.Label(f_pos, text="ex561 camera Z (µm)").grid(row=1, column=2, sticky="e")
        ttk.Entry(f_pos, textvariable=self.v_start_camera_561, width=12).grid(row=1, column=3, sticky="w")
        # 405
        ttk.Label(f_pos, text="ex405 sample Z (µm)").grid(row=2, column=0, sticky="e")
        ttk.Entry(f_pos, textvariable=self.v_start_sample_405, width=12).grid(row=2, column=1, sticky="w")
        ttk.Label(f_pos, text="ex405 camera Z (µm)").grid(row=2, column=2, sticky="e")
        ttk.Entry(f_pos, textvariable=self.v_start_camera_405, width=12).grid(row=2, column=3, sticky="w")

        # Devices
        f_dev = ttk.LabelFrame(self, text="Devices & Ports")
        f_dev.grid(row=3, column=0, sticky="nsew", **pad)
        ttk.Label(f_dev, text="KCube FW SN").grid(row=0, column=0, sticky="e")
        ttk.Entry(f_dev, textvariable=self.v_fw_sn, width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(f_dev, text="C-FLEX (405) COM").grid(row=0, column=2, sticky="e")
        ttk.Entry(f_dev, textvariable=self.v_port_cflex_405, width=10).grid(row=0, column=3, sticky="w")
        ttk.Label(f_dev, text="Skyra COM").grid(row=1, column=0, sticky="e")
        ttk.Entry(f_dev, textvariable=self.v_port_skyra, width=10).grid(row=1, column=1, sticky="w")

        # Controls
        f_ctrl = ttk.Frame(self)
        f_ctrl.grid(row=4, column=0, sticky="ew", **pad)
        ttk.Button(f_ctrl, text="Start", command=self.on_start).grid(row=0, column=0, padx=4)
        ttk.Button(f_ctrl, text="All OFF", command=self.on_all_off).grid(row=0, column=1, padx=4)
        ttk.Button(f_ctrl, text="Quit", command=self.on_quit).grid(row=0, column=2, padx=4)

    # ---------- small helpers ----------
    def _choose_save_root(self):
        d = filedialog.askdirectory()
        if d:
            self.v_save_root.set(d)

    def _choose_file(self, var: tk.StringVar):
        f = filedialog.askopenfilename()
        if f:
            var.set(f)

    def _update_camera_step(self, *args):
        try:
            s = float(self.v_sample_step.get())
            self.v_camera_step.set(round(s * 0.342, 6))
        except Exception:
            self.v_camera_step.set("")

    def _gather_params(self):
        # Basic validation and dict assembly
        try:
            it_ms = int(self.v_it_ms.get())
            integ = int(self.v_integration_ms.get())
            sample_step = float(self.v_sample_step.get())
            camera_step = float(self.v_camera_step.get())
        except Exception as e:
            raise ValueError(f"Invalid numeric input: {e}")

        START_SAMPLE = {
            647: float(self.v_start_sample_647.get()),
            561: float(self.v_start_sample_561.get()),
            405: float(self.v_start_sample_405.get()),
        }
        START_CAMERA = {
            647: float(self.v_start_camera_647.get()),
            561: float(self.v_start_camera_561.get()),
            405: float(self.v_start_camera_405.get()),
        }

        params = dict(
            SAVE_ROOT=Path(self.v_save_root.get()),
            IT_MS=it_ms,
            INTEGRATION_MS=integ,
            SAMPLE_STEP_UM=sample_step,
            CAMERA_STEP_UM=camera_step,
            START_SAMPLE=START_SAMPLE,
            START_CAMERA=START_CAMERA,
            FW_SN=self.v_fw_sn.get(),
            PORT_CFLEX={405: self.v_port_cflex_405.get()},
            PORT_SKYRA=self.v_port_skyra.get(),
            XML_CAMERA=Path(self.v_xml_camera.get()),
            CFG_MM=Path(self.v_cfg_mm.get()),
        )
        return params

    def _toggle_inputs(self, enable: bool):
        state = "normal" if enable else "disabled"
        for child in self.winfo_children():
            for sub in child.winfo_children():
                if isinstance(sub, (ttk.Entry, ttk.Button, ttk.Combobox)):
                    # Keep Quit and All OFF enabled
                    if getattr(sub, "cget", None) and sub.cget("text") in ("Quit", "All OFF"):
                        continue
                    sub.configure(state=state)

    # ---------- actions ----------
    def on_start(self):
        if self._running:
            messagebox.showinfo("Busy", "Acquisition is already running.")
            return
        try:
            params = self._gather_params()
        except Exception as e:
            messagebox.showerror("Input error", str(e))
            return

        self._toggle_inputs(False)
        self._running = True

        def worker():
            try:
                setup_logging(params["SAVE_ROOT"])

                # Initialize devices
                fw  = FilterWheel(params["FW_SN"])
                sky = CoboltSkyra(params["PORT_SKYRA"])
                cflex = {405: CoboltCFLEX(params["PORT_CFLEX"][405], 405)}

                handle = init_camera(params["XML_CAMERA"], params["INTEGRATION_MS"])
                mmc = CMMCorePlus.instance()
                mmc.loadSystemConfiguration(str(params["CFG_MM"]))

                try:
                    # Acquisition order: ex647 → ex561 → ex405
                    for wl in [647, 561, 405]:
                        run_one_excitation(
                            mmc=mmc,
                            handle=handle,
                            fw=fw,
                            sky=sky,
                            cflex=cflex,
                            wl=wl,
                            it_ms=params["IT_MS"],
                            out_root=params["SAVE_ROOT"],
                            START_SAMPLE=params["START_SAMPLE"],
                            START_CAMERA=params["START_CAMERA"],
                            SAMPLE_STEP_UM=params["SAMPLE_STEP_UM"],
                            CAMERA_STEP_UM=params["CAMERA_STEP_UM"],
                        )

                    # Stop after final excitation
                    HSI_SNAPSCAN.Stop(handle)

                except Exception as exc:
                    logging.exception(f"Acquisition aborted: {exc}")
                    try: HSI_SNAPSCAN.Stop(handle)
                    except Exception: pass
                    raise

                finally:
                    all_off(sky, cflex)
                    try: fw.close()
                    except Exception: pass
                    try: sky.close()
                    except Exception: pass
                    try: cflex[405].close()
                    except Exception: pass
                    try: HSI_SNAPSCAN.CloseDevice(handle)
                    except Exception: pass
                    logging.info("Acquisition finished")

                messagebox.showinfo("Done", "Acquisition finished.")

            except Exception as e:
                messagebox.showerror("Error", str(e))

            finally:
                self._running = False
                self._toggle_inputs(True)

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def on_all_off(self):
        # Best-effort emergency OFF using current port settings
        try:
            sky = CoboltSkyra(self.v_port_skyra.get())
            sky.all_off(); sky.close()
        except Exception:
            pass
        try:
            cf = CoboltCFLEX(self.v_port_cflex_405.get(), 405)
            cf.off(); cf.close()
        except Exception:
            pass
        messagebox.showinfo("All OFF", "Tried to switch all lasers OFF.")

    def on_quit(self):
        if self._running:
            if not messagebox.askyesno("Quit", "Acquisition is running. Stop and exit?"):
                return
        self.master.destroy()

# ==================== Entry point ====================
def main():
    root = tk.Tk()
    try:
        root.call("source", "azure.tcl")
        root.call("set_theme", "light")
    except Exception:
        pass
    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()

