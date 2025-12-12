# descSPIM-Advanced

**descSPIM-Advanced: scalable and accessible light-sheet microscopy platform for cleared-tissue imaging**



---

## What is descSPIM-Advanced aimed for?

Building on the open-hardware movement, we previously developed **descSPIM (desktop-equipped SPIM for cleared specimens)**, a minimal-expertise and low-cost LSFM platform optimized for tissue-clearing applications. The original **descSPIM-basic** could be assembled within a single day at a cost of approximately **USD 20,000–50,000**, yet achieved sufficient performance for organ-scale volumetric imaging. Since its introduction, **over fifty independently built systems** have been established worldwide and applied by non-specialist life scientists across diverse research domains.

However, the simplicity-first design of descSPIM-basic imposed several limitations in advanced imaging contexts. The **single-side illumination** configuration left residual striping when imaging large cleared samples that exceeded a single field of view, requiring multi-region acquisition followed by advanced stitching and registration. The **low-magnification detection** restricted subcellular resolution, and **multicolor imaging** was limited to three to four excitation channels. Furthermore, there remained room for **further cost optimization and optical simplification**.

**descSPIM-Advanced is aimed for overcoming these limitations**, providing expanded whole-organ field-of-view imaging, subcellular-resolution performance, ultra-multicolor capability, and a more accessible low-cost option depending on the selected configuration. These goals are realized through four interoperable variants — FullMoon, DeepSky, Galaxy, and SLIM — that extend both the conceptual and functional range of the original descSPIM-basic.

<img src="https://github.com/user-attachments/assets/73d1c159-37be-4f4f-87a0-465933087797" width="300" />
<img src="https://github.com/user-attachments/assets/cac701c9-6297-4377-a2f3-9f7a7ea3525c" width="350" />

---

## The descSPIM-Advanced Platform

The **descSPIM-Advanced platform** was developed to overcome the limitations of the initial descSPIM-basic, introducing **four interoperable variants** that expand both the conceptual and functional “space” of the system:

- **descSPIM-FullMoon** uses **dual-sided illumination** and **beam pivoting** to reduce attenuation and striping for uniform wide-field imaging.  
- **descSPIM-DeepSky** enhances both lateral and axial resolution with **high-numerical-aperture (NA) optics** for subcellular observation.  
- **descSPIM-Galaxy** integrates a **hyperspectral detection system** and dedicated analysis pipeline, enabling **>10-color 3D imaging**.  
- **descSPIM-SLIM** adopts highly affordable **laser light sources** and **simplified optics** to provide **three-color excitation** at approximately **USD 15,000**, offering the most accessible configuration in the series.

Together, the **descSPIM family** establishes a scalable platform for cleared-tissue LSFM—ranging from entry-level, low-cost builds to high-performance systems capable of **expanded whole-organ field-of-view observation, subcellular resolution, and high-channel multicolor imaging**.  
Each configuration includes step-by-step protocols for construction, alignment, acquisition, and processing, allowing both new and experienced users to achieve high-quality imaging without technical or financial barriers.

---

## System Overview

| Variant | Key Feature | Representative Application |
|----------|--------------|-----------------------------|
| **FullMoon** | Dual-sided illumination with beam pivoting | Uniform wide-field imaging of large organs |
| **DeepSky** | High-NA optics | Subcellular-resolution volumetric imaging |
| **Galaxy** | Hyperspectral detection pipeline | >10-color multiplexed imaging |
| **SLIM** | Simplified optics, low-cost lasers | Entry-level, three-color imaging (~USD 15k) |

---

## Build & Operation Guides　（要修正）

- **Optical construction and alignment**: detailed step-by-step manuals provided in the `/docs` directory  
- **Imaging parameter optimization**: recommended exposure times, laser powers, and detection filters  
- **Post-acquisition processing**: registration, stitching, and multicolor alignment (Python/ANTs-based workflows)

> [!NOTE]
> Build time varies depending on the variant and user experience:  
> *SLIM*: ~1 week  *FullMoon / DeepSky / Galaxy*: 2–6 weeks.

---

## Control & Acquisition Software Overview
The table below summarizes the software ecosystem for each descSPIM system, specifying the role of each application (full control, camera control, stage control) and including manufacturer information. Custom-developed modules such as system-specific GUIs and the Sequence Controller are listed in dedicated columns.

| System / Variant | **Mission Control Center** | **ImSwitch** | **Custom Dedicated GUI** | **Sequence Controller (custom)** | Included Softwares (with roles & manufacturers) |
|------------------|----------------------------|--------------|---------------------------|-----------------------------------|--------------------------------------------------|
| **descSPIM-basic** | **Full control (stages + camera + laser source)** | – | – | ✔️ (Thorlabs-based integration) | ThorCam (Thorlabs, for camera); Kinesis (Thorlabs, for stages); Micro-Manager (Open-source, optional) |
| **descSPIM-FullMoon** | **Full control (stages + camera + laser source + galvanometric scanner)** | – | – | – | Kinesis (Thorlabs, for stages); NIS-Elements (Nikon, for DS50M CMOS camera) |
| **descSPIM-DeepSky** | **Full control (stages + camera + pattern generator + laser source)** | **Full control** | – | – | ThorCam (Thorlabs, for camera); Kinesis (Thorlabs, for stages) |
| **descSPIM-Galaxy** | **Partial support (Thorlabs CMOS cameras + stages + laser source)** | – | Galaxy GUI (hyperspectral imaging) | ✔️ (Thorlabs-based integration) | ThorCam (Thorlabs, for camera); Kinesis (Thorlabs, for stages); Micro-Manager (Open-source, for stages); HSI SNAPSCAN (imec, for hyperspectral detector) |
| **descSPIM-SLIM** | **Full control (stages + camera)** | – | SLIM imaging GUI | ✔️ (Thorlabs-based integration) | ThorCam (Thorlabs, for camera); Kinesis (Thorlabs, for stages) |


> **Note on descSPIM-Galaxy**
>
> The Galaxy system uses two custom software modules—the **Galaxy GUI** and the **Sequence Controller**—which operate independently to support its two detection modes (the Thorlabs CMOS camera and the hyperspectral detector).  
> Using both modules during acquisition enables ultra-multicolour imaging across complementary detection modes.

---

## Related Links

- [descSPIM-basic (GitHub)](https://github.com/dbsb-juntendo/descSPIM)  
- [CUBIC Resource Site](http://cubic.riken.jp)  
- [Data Processing Tools](https://github.com/dbsb-juntendo/descSPIM/blob/main/DOCs/Data%20processing.md)

---

## Terms and Conditions （要修正）

### Creative Commons License
<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/"><img alt="Creative Commons License" style="border-width:0" src="https://i.creativecommons.org/l/by-nc-sa/4.0/88x31.png" /></a><br />This work is licensed under a <a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/">Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License</a>.

By using **descSPIM-Advanced**, you agree to the following:

- Academic use only; commercial use requires author permission.  
- Modifications and redistribution allowed under CC BY-NC-SA 4.0.  
- Cite the original work in all publications and presentations.  
- Authors are not responsible for damages or misuse.  
- All disputes shall be governed by Japanese law.



---

## References（要修正）

- **Otomo, K. et al.** *descSPIM: an affordable and easy-to-build light-sheet microscope optimized for tissue clearing techniques.* **Nat. Commun. 15, 4941 (2024).**  
- **Susaki, E. A. et al.** *Versatile whole-organ/body staining and imaging based on electrolyte-gel properties of biological tissues.* **Nat. Commun. 11, 1982 (2020).**  
- **Matsumoto, K. et al.** *Advanced CUBIC tissue clearing for whole-organ cell profiling.* **Nat. Protoc. 14, 3506–3537 (2019).**  
- [CUBIC resource website](http://cubic.riken.jp)

---


