## What is descSPIM-Advanced?

**descSPIM-Advanced** is an open and extensible light-sheet fluorescence microscopy (LSFM) platform for cleared-tissue imaging.

It builds on our previous system, **descSPIM-basic** (**desktop-equipped SPIM for cleared specimens**), which was developed as a low-cost and minimal-expertise LSFM platform for tissue-clearing applications. The original descSPIM-basic could be assembled within a single day at a cost of approximately **USD 20,000–50,000**, and has since been adopted in more than **50 independently built systems** worldwide.

Although descSPIM-basic provided an accessible entry point for organ-scale volumetric imaging, several limitations remained for more advanced imaging applications:

| Limitation of descSPIM-basic | Need addressed by descSPIM-Advanced |
|---|---|
| Single-side illumination | More uniform imaging of large cleared samples |
| Residual striping in large-volume imaging | Reduced attenuation and striping |
| Low-magnification detection | Higher spatial resolution |
| Three- to four-channel imaging | Ultra-multicolor / hyperspectral imaging |
| Remaining optical and cost complexity | Simpler and lower-cost configurations |

**descSPIM-Advanced was developed to overcome these limitations while preserving the accessibility of the original descSPIM concept.** Depending on the selected configuration, the platform enables expanded whole-organ field-of-view imaging, subcellular-resolution volumetric imaging, ultra-multicolor 3D imaging, and low-cost routine cleared-tissue imaging.

These capabilities are implemented through four interoperable variants — **FullMoon, DeepSky, Galaxy, and SLIM** — which extend both the conceptual and functional range of the original descSPIM-basic.
<img src="https://github.com/user-attachments/assets/73d1c159-37be-4f4f-87a0-465933087797" width="300" />
<img src="https://github.com/user-attachments/assets/49bf6eeb-6fc2-4a57-acee-92f118a8f9e9" width="350"/>


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

## Build & Operation Guides

- **Optical construction and alignment**: detailed step-by-step manuals are provided within each model-specific directory  
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

## Terms and Conditions

### Creative Commons License
<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/"><img alt="Creative Commons License" style="border-width:0" src="https://i.creativecommons.org/l/by-nc-sa/4.0/88x31.png" /></a><br />This work is licensed under a <a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/">Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License</a>.

By using **descSPIM-Advanced**, you agree to the following:

- Academic use only; commercial use requires author permission.  
- Modifications and redistribution allowed under CC BY-NC-SA 4.0.  
- Cite the original work in all publications and presentations.  
- Authors are not responsible for damages or misuse.  
- All disputes shall be governed by Japanese law.



---

## References

- **Otomo, K. et al.** *descSPIM: an affordable and easy-to-build light-sheet microscope optimized for tissue clearing techniques.* **Nat. Commun. 15, 4941 (2024).**  
- **Susaki, E. A. et al.** *Versatile whole-organ/body staining and imaging based on electrolyte-gel properties of biological tissues.* **Nat. Commun. 11, 1982 (2020).**  
- **Matsumoto, K. et al.** *Advanced CUBIC tissue clearing for whole-organ cell profiling.* **Nat. Protoc. 14, 3506–3537 (2019).**  
- [CUBIC-HistoVIsion2.0 protocol](https://www.protocols.io/view/cubic-histovision2-0-n92ld1wyxl5b/v1)  
- [CUBIC resource website](http://cubic.riken.jp)

---


