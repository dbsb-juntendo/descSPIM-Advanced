# Mission Control Center (MCC)

A unified control framework for descSPIM-Advanced systems.

---

## Overview

The **Mission Control Center (MCC)** is a modular, Python-based control framework for operating and coordinating hardware across descSPIM-basic and descSPIM-Advanced systems.
MCC provides a unified graphical interface for controlling cameras, motorized stages, laser sources, filter changers, galvanometric mirrors, and other connected devices. Device-specific backends operate independently, while operator classes coordinate these modules to perform synchronized workflows, including multicolor and multistack acquisition.

MCC is built on:

- **Qt (PySide6)** for GUI and communication through Qt signals and slots  
- **Python** for device control and workflow orchestration  
- **Device-specific backends and SDK wrappers** for communication with individual hardware components
- A modular GUI–operator–backend architecture that allows new devices and system configurations to be added without modifying the core application

Third-party dependencies, including PySide6 and hardware-manufacturer SDKs, are not distributed with MCC and must be obtained separately under their respective license terms.

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
- Filter changer console  
- Galvanometer mirror console  

### **2. Qt Signal / Slot Layer**
Provides real-time communication between consoles (GUI) and operaters.

### **3. Operator Layer (Python classes)**
Implements high-level hardware actions:  
The operator layer implements high-level device operations and coordinates multiple hardware modules through the main application. It manages synchronized workflows such as camera acquisition, stage movement, laser switching, filter changes, and multicolor or multistack imaging.

### **4. Backend Layer**
Each backend encapsulates device-specific control logic and translates operator commands into calls to the corresponding SDK, serial interface, or device API. Backends are implemented as independent modules so that additional hardware can be supported without changing the core application.

### **5. SDK Layer**
This layer interfaces with vendor SDKs and device communication protocols, including:

- Thorlabs Kinesis
- Thorlabs Scientific Camera SDK
- Nikon Digital Sight 50M SDK
- Serial and USB communication interfaces
- Device-specific Python wrappers

### **6. Physical Devices**
Actual hardware components:  
camera, stage, laser, filter changer, galvanometer mirror.

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

The original Mission Control Center (MCC) source code in this repository is licensed under the PolyForm Noncommercial License 1.0.0 (PolyForm-Noncommercial-1.0.0).

The license permits use, copying, modification, and redistribution for purposes permitted by the PolyForm Noncommercial License 1.0.0. Commercial use is not authorized under this license.

A separate written commercial license is required for the use of MCC in commercial products, paid services, commercially supplied instruments, or other commercial activities.

For commercial licensing inquiries, please contact:

naitou.k.kagoshima@gmail.com

See the following files for details:

LICENSE: the complete PolyForm Noncommercial License 1.0.0
NOTICE.md: copyright, commercial licensing, safety, and third-party software notices

MCC is source-available software and is not distributed under an OSI-approved open-source license.

Documentation and figures in this repository are licensed under CC BY-NC-SA 4.0 unless otherwise noted.

---

## Contact

For questions or contributions, please contact:  
**[Naitouk](https://github.com/Naitouk)**  
or open an Issue / Pull Request in this repository.


