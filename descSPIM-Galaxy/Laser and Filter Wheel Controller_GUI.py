# -*- coding: utf-8 -*-
"""
Laser and Filter Wheel Controller.ipynb

CFLEX (Cobolt C‑FLEX) power setup (do this ONCE before running this app):
- Launch CoboltMonitor.exe.
- Click More → set Constant power to your desired value for each C‑FLEX unit.
- Close all Cobolt Monitor windows so the serial port is free.
- Then run this Python controller. This app will only toggle C‑FLEX lasers (l1/l0).

What this app does
- Homes and drives a Thorlabs KCube Stepper (filter wheel) to pre‑defined angles for each wavelength.
- Controls Cobolt Skyra (multi‑line) lasers: per‑line power (mW) is set from the GUI, and each line is toggled ON/OFF.
- Controls Cobolt C‑FLEX lasers (e.g., 405 nm, 730 nm): ON/OFF only (power is fixed by Cobolt Monitor as above).

Configuration
- Set the variables in the "USER CONFIG" section. Typical values are shown as examples only.

- KINESIS_PATH: Folder containing Thorlabs Kinesis DLLs. You can also set env var THORLABS_KINESIS_PATH.
- KSTEPSER: KCube Stepper serial number (e.g., "26006126").
- FILTER_POSITIONS_DEG: Map wavelength → absolute angle [deg].
- SKYRA_COM: Serial COM port for the Skyra (e.g., "COM6").
- CFLEX_COMS: Dict mapping wavelength → COM port for each C‑FLEX.
- SKYRA_LINES: Map Skyra line index → wavelength (Skyra command prefix uses line index).

Requirements
- Windows + Thorlabs Kinesis (DeviceManagerCLI & KCube.StepperMotorCLI .NET DLLs)
- pythonnet (for import clr), pyserial, tkinter (bundled with most Python on Windows)

Notes:
- If execution appears unstable, please prioritize running the corresponding .py file directly in your local environment instead of the .ipynb in Jupyter Notebook.
"""

import os
import sys
import time
import tkinter as tk
from tkinter import ttk, messagebox

# Python/.NET interop & serial
try:
    import clr  # pythonnet
    from System import Decimal  # .NET Decimal
except Exception as e:
    raise RuntimeError("pythonnet is required (pip install pythonnet).") from e

import serial

# =====================
# ===== USER CONFIG ===
# =====================

# (A) Thorlabs Kinesis install folder (contains the DLLs). Prefer env if set.
KINESIS_PATH = os.environ.get("THORLABS_KINESIS_PATH", r"C:\\Program Files\\Thorlabs\\Kinesis")

# (B) KCube Stepper serial number (string)
KSTEPSER = os.environ.get("KSTEPSER", "26006126")

# (C) Filter wheel absolute angles [deg] for each wavelength (customize to your wheel)
FILTER_POSITIONS_DEG = {
    405: Decimal(0),
    488: Decimal(60),
    515: Decimal(120),
    561: Decimal(180),
    647: Decimal(240),
    730: Decimal(300),
}

# (D) Cobolt Skyra COM port
SKYRA_COM = os.environ.get("SKYRA_COM", "COM6")

# (E) C‑FLEX COM ports per wavelength (only ON/OFF from this app)
CFLEX_COMS = {
    405: os.environ.get("CFLEX_405", "COM3"),
    730: os.environ.get("CFLEX_730", "COM7"),
}

# (F) Skyra line index → wavelength map (adjust for your instrument)
#     Skyra serial commands address lines by index (1..N).
SKYRA_LINES = {
    1: 561,
    2: 647,
    3: 515,
    4: 488,
}

# Default Skyra power slider ranges (mW)
SKYRA_POWER_MIN = 0.0
SKYRA_POWER_MAX = 200.0
SKYRA_DEFAULT_POWER = 50.0

# ===========================
# ===== Load Kinesis CLI =====
# ===========================
if not os.path.isdir(KINESIS_PATH):
    raise FileNotFoundError(
        f"Kinesis path not found: {KINESIS_PATH}\n"
        "Set THORLABS_KINESIS_PATH env var or edit KINESIS_PATH above."
    )

sys.path.append(KINESIS_PATH)
os.environ["PATH"] = os.environ.get("PATH", "") + os.pathsep + KINESIS_PATH

# Add references to Thorlabs .NET assemblies
clr.AddReference(os.path.join(KINESIS_PATH, "Thorlabs.MotionControl.DeviceManagerCLI.dll"))
clr.AddReference(os.path.join(KINESIS_PATH, "Thorlabs.MotionControl.KCube.StepperMotorCLI.dll"))

from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI, DeviceConfiguration
from Thorlabs.MotionControl.KCube.StepperMotorCLI import KCubeStepper

# ====================
# ===== Drivers ======
# ====================

class CoboltSkyraLaser:
    """Cobolt Skyra serial control (per-line power + ON/OFF)."""

    def __init__(self, port: str):
        self.port = port
        self.ser: serial.Serial | None = None
        # Reverse lookup: wavelength → line index
        self.line_by_wl = {wl: line for line, wl in SKYRA_LINES.items()}

    # --- Low-level IO ---
    def connect(self) -> bool:
        if self.ser and self.ser.is_open:
            return True
        try:
            self.ser = serial.Serial(self.port, 115200, timeout=1)
            time.sleep(0.5)
            print(f"✅ Connected to {self.port} (Skyra)")
            return True
        except Exception as e:
            messagebox.showerror("Skyra Connection Error", str(e))
            return False

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"🔌 Disconnected from {self.port} (Skyra)")

    def _send(self, cmd: str, delay: float = 0.1) -> str:
        if not (self.ser and self.ser.is_open) and not self.connect():
            return ""
        try:
            payload = f"{cmd}\r".encode()
            self.ser.write(payload)
            time.sleep(delay)
            resp = self.ser.read_all().decode(errors="ignore").strip()
            print(f"➡️ Sent: {cmd} | ⬅️ Response: {resp}")
            return resp
        except Exception as e:
            print(f"Skyra send error for `{cmd}`: {e}")
            return ""

    # --- Commands ---
    def set_power_mw(self, wavelength: int, power_mw: float) -> str:
        line = self.line_by_wl.get(wavelength)
        if line is None:
            messagebox.showerror("Skyra", f"No Skyra line configured for {wavelength} nm")
            return ""
        power_w = max(0.0, float(power_mw)) / 1000.0
        self._send(f"{line}p {power_w:.6f}")  # set power in Watts
        self._send(f"{line}l1")               # ensure line is enabled
        time.sleep(1.5)
        return self._send(f"{line}pa?")        # query actual power

    def laser_on(self, wavelength: int):
        line = self.line_by_wl.get(wavelength)
        if line is not None:
            self._send(f"{line}l1")

    def laser_off(self, wavelength: int | None = None):
        if wavelength is None:
            # all lines off
            for line in SKYRA_LINES.keys():
                self._send(f"{line}l0")
            return
        line = self.line_by_wl.get(wavelength)
        if line is not None:
            self._send(f"{line}l0")


class CoboltCFLEXLaser:
    """Cobolt C‑FLEX serial (ON/OFF only; power fixed via Cobolt Monitor)."""

    def __init__(self, port: str, wavelength: int):
        self.port = port
        self.wavelength = wavelength
        self.ser: serial.Serial | None = None

    def connect(self) -> bool:
        if self.ser and self.ser.is_open:
            return True
        try:
            self.ser = serial.Serial(self.port, 115200, timeout=1)
            time.sleep(0.5)
            print(f"✅ Connected to {self.port} (C‑FLEX {self.wavelength} nm)")
            return True
        except Exception as e:
            messagebox.showerror("C‑FLEX Connection Error", str(e))
            return False

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print(f"🔌 Disconnected from {self.port} (C‑FLEX {self.wavelength} nm)")

    def _send(self, cmd: str, delay: float = 0.1) -> str:
        if not (self.ser and self.ser.is_open) and not self.connect():
            return ""
        try:
            self.ser.write(f"{cmd}\r".encode())
            time.sleep(delay)
            resp = self.ser.read_all().decode(errors="ignore").strip()
            print(f"➡️ Sent: {cmd} | ⬅️ Response: {resp}")
            return resp
        except Exception as e:
            print(f"C‑FLEX send error for `{cmd}`: {e}")
            return ""

    def laser_on(self):
        self._send("l1")

    def laser_off(self):
        self._send("l0")


# ===========================
# ===== KCube Stepper =======
# ===========================

def init_stepper(serial_no: str) -> KCubeStepper:
    DeviceManagerCLI.BuildDeviceList()
    dev = KCubeStepper.CreateKCubeStepper(serial_no)
    dev.Connect(serial_no)
    use_file = DeviceConfiguration.DeviceSettingsUseOptionType.UseFileSettings
    dev.LoadMotorConfiguration(serial_no, use_file)
    dev.StartPolling(250)
    time.sleep(0.5)
    dev.EnableDevice()
    time.sleep(0.5)
    print("🏠 Homing KCube Stepper...")
    dev.Home(60000)
    time.sleep(0.5)
    return dev


# =====================
# ===== GUI App =======
# =====================

class LaserFilterApp(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master)
        master.title("Laser & Filter Wheel Controller")
        master.protocol("WM_DELETE_WINDOW", self.on_quit)

        # Devices
        self.stepper = init_stepper(KSTEPSER)
        self.skyra = CoboltSkyraLaser(SKYRA_COM)
        self.cflex = {wl: CoboltCFLEXLaser(port, wl) for wl, port in CFLEX_COMS.items()}

        # GUI State
        self.current_wavelength: int | None = None
        self.skyra_power_vars: dict[int, tk.DoubleVar] = {}

        # Layout
        self._build_widgets()

    # ----- UI Building -----
    def _build_widgets(self):
        pad = {"padx": 10, "pady": 6}

        # Skyra Control Panel
        skyra_frame = ttk.LabelFrame(self, text="Cobolt Skyra (per‑line power & ON)")
        skyra_frame.grid(row=0, column=0, sticky="nsew", **pad)

        row = 0
        for line, wl in sorted(SKYRA_LINES.items()):
            ttk.Label(skyra_frame, text=f"{wl} nm (Line {line})").grid(row=row, column=0, sticky="w")
            var = tk.DoubleVar(value=SKYRA_DEFAULT_POWER)
            self.skyra_power_vars[wl] = var
            scale = ttk.Scale(
                skyra_frame, from_=SKYRA_POWER_MIN, to=SKYRA_POWER_MAX,
                orient=tk.HORIZONTAL, variable=var, length=220
            )
            scale.grid(row=row, column=1, sticky="ew", padx=6)
            entry = ttk.Entry(skyra_frame, width=7, textvariable=var)
            entry.grid(row=row, column=2, padx=4)
            ttk.Label(skyra_frame, text="mW").grid(row=row, column=3, sticky="w")
            btn = ttk.Button(
                skyra_frame, text=f"ON {wl} nm",
                command=lambda w=wl: self.activate_laser_and_filter(w)
            )
            btn.grid(row=row, column=4, padx=6)
            row += 1

        # C‑FLEX Panel
        cflex_frame = ttk.LabelFrame(self, text="Cobolt C‑FLEX (ON/OFF; power fixed via Cobolt Monitor)")
        cflex_frame.grid(row=1, column=0, sticky="nsew", **pad)
        c_row = 0
        for wl in sorted(self.cflex.keys()):
            ttk.Label(cflex_frame, text=f"{wl} nm").grid(row=c_row, column=0, sticky="w")
            ttk.Button(cflex_frame, text=f"ON {wl} nm", command=lambda w=wl: self.activate_laser_and_filter(w)).grid(
                row=c_row, column=1, padx=6
            )
            ttk.Button(cflex_frame, text=f"OFF {wl} nm", command=lambda w=wl: self.turn_off_specific(w)).grid(
                row=c_row, column=2, padx=6
            )
            c_row += 1

        # Global Controls
        global_frame = ttk.LabelFrame(self, text="Global")
        global_frame.grid(row=2, column=0, sticky="nsew", **pad)
        ttk.Button(global_frame, text="🚫 All OFF", command=self.turn_all_lasers_off).grid(row=0, column=0, padx=6)
        ttk.Button(global_frame, text="Quit", command=self.on_quit).grid(row=0, column=1, padx=6)

        self.grid(padx=10, pady=10)

    # ----- Actions -----
    def activate_laser_and_filter(self, wavelength: int):
        """Rotate filter, switch previous laser OFF, then turn requested laser ON.
        Skyra lines use GUI‑set power; C‑FLEX is ON only.
        """
        # 1) Turn off previously active laser (if any)
        if self.current_wavelength is not None:
            self.turn_off_specific(self.current_wavelength)

        # 2) Rotate filter wheel
        angle = FILTER_POSITIONS_DEG.get(wavelength)
        if angle is None:
            messagebox.showerror("Filter Wheel", f"No angle configured for {wavelength} nm")
            return
        print(f"↻ Moving to {angle} degrees for {wavelength} nm")
        self.stepper.SetMoveAbsolutePosition(angle)
        self.stepper.MoveAbsolute(60000)

        # 3) Turn ON new laser (Skyra: set power, C‑FLEX: ON only)
        if wavelength in self.cflex:
            if self.cflex[wavelength].connect():
                self.cflex[wavelength].laser_on()
        else:
            # Skyra line
            power_mw = float(self.skyra_power_vars.get(wavelength, tk.DoubleVar(value=SKYRA_DEFAULT_POWER)).get())
            self.skyra.set_power_mw(wavelength, power_mw)

        self.current_wavelength = wavelength
        print(f"🟢 {wavelength} nm laser ON")

    def turn_off_specific(self, wavelength: int):
        if wavelength in self.cflex:
            try:
                if self.cflex[wavelength].connect():
                    self.cflex[wavelength].laser_off()
            except Exception as e:
                print(f"⚠️ Could not turn off {wavelength} nm C‑FLEX: {e}")
        else:
            self.skyra.laser_off(wavelength)
        print(f"🔴 {wavelength} nm laser OFF")

    def turn_all_lasers_off(self):
        # Skyra: all lines off
        self.skyra.laser_off(None)
        # C‑FLEX: off each
        for wl, dev in self.cflex.items():
            try:
                if dev.connect():
                    dev.laser_off()
            except Exception as e:
                print(f"⚠️ Could not turn off {wl} nm C‑FLEX: {e}")
        self.current_wavelength = None
        print("🚫 All lasers OFF")

    def on_quit(self):
        try:
            self.turn_all_lasers_off()
        finally:
            try:
                self.stepper.StopPolling()
                self.stepper.Disconnect()
            except Exception:
                pass
            try:
                self.skyra.disconnect()
            except Exception:
                pass
            for dev in self.cflex.values():
                try:
                    dev.disconnect()
                except Exception:
                    pass
            self.master.destroy()


# =====================
# ===== Entrypoint =====
# =====================

def main():
    root = tk.Tk()
    # ttk theme
    try:
        root.call("source", "azure.tcl")  # if available
        root.call("set_theme", "light")
    except Exception:
        pass
    app = LaserFilterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
