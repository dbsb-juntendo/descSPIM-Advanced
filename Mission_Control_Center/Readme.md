# Mission Control Center (MCC)

A unified control framework for descSPIM-basic and descSPIM-Advanced systems.

---

## Installation and Setup

Detailed instructions for installing MCC, setting up the Python environment, installing vendor-provided SDKs and drivers, configuring connected devices, and launching the application are provided in the instruction manual:

* [MCC Installation Manual](https://github.com/dbsb-juntendo/descSPIM-Advanced/blob/main/Mission_Control_Center/20251217%20Mission%20Control%20Center%20Installation%20Manual.pdf)

Users must obtain all required vendor-provided SDKs and drivers separately from the respective manufacturers.

## Running MCC

After completing the installation and hardware configuration, launch MCC by double-clicking the MCC shortcut icon on the desktop.

:::writing{variant="document" id="13974"}
## Safety Notice

MCC is research software and is not intended for clinical, diagnostic, or safety-critical applications.

MCC can control lasers, motorized stages, cameras, filter changers, and galvanometric mirrors. Users are responsible for confirming hardware compatibility and implementing appropriate laser-safety measures, motion limits, emergency-stop procedures, and other safeguards before operating the system.
:::

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
Each hardware module is controlled through a dedicated console:

- Camera console  
- Stage console  
- Laser console  
- Filter changer console  
- Galvanometer mirror console  

### **2. Qt Signals and Slots**
Provides real-time communication between the GUI consoles and operator classes.

### **3. Operator Layer (Python classes)**
The operator layer implements high-level device operations and coordinates multiple hardware modules through the main application. It manages synchronized workflows such as camera acquisition, stage movement, laser switching, filter changes, galvanometric mirror scanning, and multicolor or multistack imaging.

### **4. Backend Layer**
Each backend encapsulates device-specific control logic and translates operator commands into calls to the corresponding SDK, serial interface, or device API. Backends are implemented as independent modules so that additional hardware can be supported without modifying the core application.

### **5. SDK and Communication Layer**
This layer interfaces with vendor SDKs and device communication protocols, including:

- Thorlabs Kinesis
- Thorlabs Scientific Camera SDK
- Nikon Digital Sight 50M SDK
- Serial and USB communication interfaces
- Device-specific Python wrappers

Vendor-provided SDKs, drivers, and related software are not distributed in this repository. Users must obtain them separately from the respective manufacturers and comply with their applicable license terms. Detailed installation and setup instructions are provided in the PDF instruction manual included in this repository.

### **6. Physical Devices**
The physical devices controlled by MCC include cameras, motorized stages, laser sources, filter changers, and galvanometric mirrors.

---
## Supported Hardware Components

### Cameras

| Manufacturer | Model / Series               | Control Interface              |
| ------------ | ---------------------------- | ------------------------------ |
| Thorlabs     | CS126MU, LP126MU/M           | Thorlabs Scientific Camera SDK |
| Nikon        | Digital Sight 50M (DS50M)    | Nikon Digital Sight 50M SDK    |

### Motorized Stages

| Manufacturer | Model / Series                            | Control Interface |
| ------------ | ----------------------------------------- | ----------------- |
| Thorlabs     | KDC101 with DC servo motor actuator       | XA SDK            |
| Thorlabs     | KST101 with ZFS25B stepper motor actuator | XA SDK            |

### Laser Sources

| Manufacturer | Model / Series                   | Control Interface    |
| ------------ | -------------------------------- | -------------------- |
| Cobolt       | Skyra                            | Serial communication |

### Filter Changers

| Manufacturer   | Model / Series  | Control Interface    |
| -------------- | --------------- | -------------------- |
| Thorlabs       | KST201 with SW6 | XA SDK               |
| Thorlabs       | ELL9            | Serial communication |

### Pattern and Function Generators for Galvanometer Mirror Control

| Manufacturer | Model / Series | Control Interface    |
| ------------ | -------------- | -------------------- |
| Joy-IT       | JDS6600        | Serial communication |
| RIGOL        | DG822          | USB communication    |

---

## Integration with descSPIM Variants

| descSPIM Variant | MCC Support |
|------------------|-------------|
| **Basic** | Full control (Thorlabs CMOS camera, stages, laser) |
| **Galaxy** | Partial support (Thorlabs CMOS camera, stages, laser, filter changer) |
| **Deepsky** | Full control (Thorlabs CMOS camera, stages, laser, filter changer, galvanometer mirror) |
| **Fullmoon** | Full control (Nikon CMOS camera, stages,  laser, galvanometer mirror) |
| **SLIM** | Full control (Thorlabs CMOS camera, stages) |

---

## Key Features

- **Unified GUI** controlling connected hardware modules
- **Modular operator–backend–SDK architecture**  
- **Hardware abstraction** for supporting different device configurations
- **Real-time communication** through Qt signals and slots
- **Cross-variant deployment** across descSPIM-basic and descSPIM-Advanced systems
- **Extensibility**, allowing new devices to be added with minimal changes to the core application

---

## Future Directions

- Optional integration with Micro-Manager ecosystem  
- Automated alignment and calibration routines  
- Improved synchronization primitives for hyperspectral (Galaxy) workflows  
- Compatibility with future Python releases

---

## Citation

If you use MCC in your research, please cite:

Citation information will be added after the formal publication of descSPIM-Advanced.

---

## License

The original Mission Control Center (MCC) source code in this repository is licensed under the PolyForm Noncommercial License 1.0.0 (PolyForm-Noncommercial-1.0.0).

The license permits use, copying, modification, and redistribution for purposes permitted by the PolyForm Noncommercial License 1.0.0. Commercial use is not authorized under this license.

A separate written commercial license is required for the use of MCC in commercial products, paid services, commercially supplied instruments, or other commercial activities.

For commercial licensing inquiries, please contact:

naitou.k.kagoshima@gmail.com

See the following files for details:
- `LICENSE`: complete text of the PolyForm Noncommercial License 1.0.0
- `NOTICE.md`: copyright, commercial licensing, and safety notices

MCC is source-available software and is not distributed under an OSI-approved open-source license.

Documentation and figures in this repository are licensed under CC BY-NC-SA 4.0 unless otherwise noted.

---

## Contact

For questions or contributions, please contact:  
**[Naitouk](https://github.com/Naitouk)**  
or open an Issue / Pull Request in this repository.


