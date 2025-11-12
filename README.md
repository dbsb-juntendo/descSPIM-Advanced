# descSPIM-Advanced

**descSPIM-Advanced: scalable and accessible light-sheet microscopy platform for cleared-tissue imaging**

<img src="https://github.com/user-attachments/assets/fe5b47da-0e0b-48b5-a94f-35260398d481" width="300" />
<img src="https://github.com/user-attachments/assets/cac701c9-6297-4377-a2f3-9f7a7ea3525c" width="350" />

---

## What is descSPIM-Advanced?

Building on the open-hardware movement, we previously developed **descSPIM (desktop-equipped SPIM for cleared specimens)** — a minimal-expertise and low-cost LSFM platform optimized for tissue-clearing applications. The original **descSPIM-basic** could be assembled within a single day at a cost of approximately **USD 20,000–50,000**, yet achieved sufficient performance for organ-scale volumetric imaging.  
Since its introduction, **over fifty independently built systems** have been established worldwide and applied by non-specialist life scientists across diverse research domains.

However, the simplicity-first design of descSPIM-basic imposed several limitations in advanced imaging contexts.  
The **single-side illumination** configuration left residual striping when imaging large cleared samples that exceeded a single field of view, requiring multi-region acquisition followed by advanced stitching and registration. The **low-magnification detection** restricted subcellular resolution, and **multicolor imaging** was limited to three to four excitation channels. Furthermore, there remained room for **further cost optimization and optical simplification**.

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

- **Optical construction and alignment**: detailed step-by-step manuals provided in the `/docs` directory  
- **Imaging parameter optimization**: recommended exposure times, laser powers, and detection filters  
- **Post-acquisition processing**: registration, stitching, and multicolor alignment (Python/ANTs-based workflows)

> [!NOTE]
> Build time varies depending on the variant and user experience:  
> *SLIM*: ~1 week  *FullMoon / DeepSky / Galaxy*: 2–6 weeks.

---

## Related Links

- [descSPIM-basic (GitHub)](https://github.com/dbsb-juntendo/descSPIM)  
- [CUBIC Resource Site](http://cubic.riken.jp)  
- [Data Processing Tools](https://github.com/dbsb-juntendo/descSPIM/blob/main/DOCs/Data%20processing.md)

---

## Terms and Conditions （要修正）

### Creative Commons License
This work is licensed under a Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License.

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
- [CUBIC resource website](http://cubic.riken.jp)

---


