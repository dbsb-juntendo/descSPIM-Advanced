Please first refer to **descSPIM_SLIM_construction_manual.pdf**, which provides an overview of the construction procedure and overall hardware setup.

# descSPIM-SLIM

Please note that **full control and imaging of this model are available through the Mission Control Center (MCC)**.  
This document provides a manual for the **simplest Python-based imaging workflow**.  
For **more reproducible image acquisition**, we recommend using **MCC**.

## descSPIM-SLIM: Python Control Installation Instructions  

### File Overview
- **251109_descSPIM-SLIM_Python Control GUI.ipynb** — Main notebook for controlling descSPIM-SLIM via Python on Windows 11.  
- **Homing Cell** — Connects to KST201 controllers, initializes environment, and performs stage homing.  
- **ThorCam Configuration** — Describes camera setup (exposure 300 ms, continuous mode, trigger off).  
- **Velocity Setting GUI Cell** — Opens GUI to set velocity / acceleration for sample and camera stages.  
- **Focusing Procedure** — Guides manual positioning to determine the imaging start plane.  
- **Synchronized Imaging** — Executes synchronized stage motion and ThorCam recording for multicolor 3D imaging.  
- **Troubleshooting Section** — Lists common issues (connection errors, serial mismatch, stage limit stops, interrupted runs) and solutions.

---

Please refer to **descSPIM-SLIM_Python Control Installation Instructions.pdf** for detailed setup and usage.

