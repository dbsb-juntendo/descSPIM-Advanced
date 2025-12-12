# Mission Control Center (MCC)

A unified control framework for descSPIM-Advanced systems.

---

## Overview

The **Mission Control Center (MCC)** is a modular, Python-based control system designed to operate key hardware components across the descSPIM-Advanced microscope series.  
MCC integrates **laser sources, Thorlabs stages, Thorlabs CMOS cameras, Nikon DS50M cameras**, and other hardware elements into a unified, scalable control architecture.

MCC is built on:

- **Qt (PySide6)** for GUI and signal/slot communication  
- **Python** for backend logic  
- **SDK wrappers** for hardware control  
- A modular operator–backend–SDK design that ensures extensibility and variant-specific customization

---

## System Architecture

Below is the conceptual architecture of MCC, showing how GUI consoles, operators, backends, and hardware SDK layers interact.

<img width="613" height="334" alt="アートボード 1" src="https://github.com/user-attachments/assets/2153cf1a-4812-4118-b2d8-ea5e46f27983" />



---

## Architecture Layers

### **1. Operation Room (MainWindow / GUI)**
Each hardware module is controlled from its dedicated console:

- Camera console  
- Stage console  
- Laser console  
- Filter console  
- Galvanometric scanner console  

### **2. Qt Signal / Slot Layer**
Provides real-time communication between GUI and backend modules.

### **3. Operator Layer (Python classes)**
Implements high-level hardware actions:  
exposure control, stage movement, laser power operations, filter switching, galvo scanning.

### **4. Backend Layer**
Hardware-agnostic translation layer that:

- Converts operator instructions to SDK functions  
- Manages timing, synchronization, and error handling  

### **5. SDK Layer**
Interfaces with vendor SDKs:

- Thorlabs (Kinesis / ThorCam SDK)  
- Nikon DS50M SDK  
- Device-specific SDK wrappers  

### **6. Physical Devices**
Actual hardware components:  
camera, stage, laser, filter, galvanometric scanner.

---

## Supported Hardware Components

| Component | Supported Brands | Notes |
|----------|------------------|-------|
| Stages | Thorlabs (Kinesis) | Multi-axis control |
| Cameras (CMOS) | Thorlabs | Full integration |
| Cameras (Nikon) | DS50M | Controlled through MCC SDK layer |
| Laser Sources | Cobolt Skyra | Full operation supported |
| Filters | Motorized filter wheels, Thorlabs | SDK-level and GUI control |
| Galvanometric Scanners | Galvo mirrors | Supported in FullMoon configuration |

---

## Integration with descSPIM Variants

| descSPIM Variant | MCC Support |
|------------------|-------------|
| **Basic** | Full control (stages, camera, laser source) |
| **FullMoon** | Full control (stages, camera, laser source, galvanometric scanner) |
| **DeepSky** | Full control (stages, camera, pattern generator, laser source) |
| **Galaxy** | Partial support (Thorlabs CMOS cameras, stages, laser source) |
| **SLIM** | Full control (stages, camera) |

---

## Key Features

- **Unified GUI** for all hardware modules  
- **Modular operator–backend–SDK design**  
- **Hardware abstraction**, enabling easy expansion  
- **Real-time responsiveness** via Qt signal/slot  
- **Cross-variant deployability** across descSPIM-Advanced systems  
- **Extendibility**: new devices can be added with minimal code additions  

---

## Proposed Folder Structure

```
mcc/
 ├─ gui/
 │   ├─ mainwindow.py
 │   ├─ camera_console.py
 │   ├─ stage_console.py
 │   ├─ laser_console.py
 │   ├─ filter_console.py
 │   └─ galvo_console.py
 ├─ operators/
 │   ├─ camera_operator.py
 │   ├─ stage_operator.py
 │   ├─ laser_operator.py
 │   ├─ filter_operator.py
 │   └─ galvo_operator.py
 ├─ backend/
 │   ├─ camera_backend.py
 │   ├─ stage_backend.py
 │   ├─ laser_backend.py
 │   ├─ filter_backend.py
 │   └─ galvo_backend.py
 ├─ sdk/
 │   ├─ thorlabs/
 │   ├─ nikon/
 │   └─ wrappers/
 ├─ utils/
 ├─ config/
 └─ README.md
```

---

## Future Directions

- Optional integration with Micro-Manager ecosystem  
- Automated alignment and calibration routines  
- Improved synchronization primitives for hyperspectral (Galaxy) workflows  
- Migration to Python 3.12+ compatibility  

---

## Citation

If you use MCC in your research, please cite:


Additional citations will be added when descSPIM-Advanced is formally published.

---

## License

This project follows CC BY-NC-SA 4.0, consistent with the descSPIM-Advanced platform.

---

## Contact

For questions or contributions, please contact:  
**[Naitouk](https://github.com/Naitouk)**  
or open an Issue / Pull Request in this repository.


