<h1>What is the descSPIM-Advanced platform?</h1>

**descSPIM-Advanced** is an open and extensible light-sheet fluorescence microscopy (LSFM) ecosystem for cleared-tissue imaging.

It builds on our previous system, **descSPIM-basic**  
(**desktop-equipped SPIM for cleared specimens**), a low-cost and minimal-expertise LSFM platform optimized for tissue-clearing applications.

The original **descSPIM-basic** system was designed to be accessible to non-specialist users and could be:

- assembled within a single day,
- built at a cost of approximately **USD 20,000–50,000**,
- and used for organ-scale volumetric imaging.

Since its introduction, more than **50 independently built systems** have been established worldwide and applied across diverse biological research fields.

---

## Why descSPIM-Advanced?

Although descSPIM-basic provided an accessible entry point for cleared-tissue LSFM, several limitations remained for advanced imaging applications.

| Limitation of descSPIM-basic | Need addressed by descSPIM-Advanced |
|---|---|
| Single-side illumination | More uniform imaging of large cleared samples |
| Residual striping in large-volume imaging | Reduced attenuation and striping |
| Low-magnification detection | Higher spatial resolution |
| Three- to four-channel imaging | Ultra-multicolor / hyperspectral imaging |
| Remaining optical and cost complexity | Simpler and lower-cost configurations |

**descSPIM-Advanced was developed to overcome these limitations while preserving the accessibility of the original descSPIM concept.**

Depending on the selected configuration, the platform enables:

- expanded whole-organ field-of-view imaging,
- subcellular-resolution volumetric imaging,
- ultra-multicolor 3D imaging,
- and low-cost routine cleared-tissue imaging.

These capabilities are implemented through four interoperable variants — **FullMoon, DeepSky, Galaxy, and SLIM** — which extend both the conceptual and functional range of the original descSPIM-basic.

<p>
  <img src="https://github.com/user-attachments/assets/73d1c159-37be-4f4f-87a0-465933087797" width="330" />
  <img src="https://github.com/user-attachments/assets/49bf6eeb-6fc2-4a57-acee-92f118a8f9e9" width="380" />
</p>

---

<h1>The descSPIM-Advanced Platform</h1>

The **descSPIM-Advanced platform** consists of four interoperable variants, each optimized for a distinct imaging regime.

| Variant | Main capability | Representative application |
|---|---|---|
| **descSPIM-FullMoon** | Large field-of-view imaging | Uniform wide-field imaging of large cleared organs |
| **descSPIM-DeepSky** | High spatial resolution | Subcellular-resolution volumetric imaging |
| **descSPIM-Galaxy** | Ultra-multicolor / hyperspectral imaging | More than 10-color 3D imaging |
| **descSPIM-SLIM** | Low-cost simplified deployment | Entry-level three-color cleared-tissue imaging |

## Variant highlights

- **descSPIM-FullMoon** uses **dual-sided illumination** and **beam pivoting** to reduce attenuation and striping during large-volume imaging.
- **descSPIM-DeepSky** uses **high-numerical-aperture optics** to improve lateral and axial resolution for high-resolution 3D observation.
- **descSPIM-Galaxy** integrates **hyperspectral detection** and a dedicated analysis pipeline for ultra-multicolor cleared-tissue imaging.
- **descSPIM-SLIM** adopts **simplified optics** and affordable laser sources to provide a highly accessible configuration at approximately **USD 15,000**.

Together, the **descSPIM family** provides a scalable cleared-tissue LSFM ecosystem, ranging from entry-level low-cost systems to high-performance configurations for large-volume, high-resolution, and high-channel imaging.

---

<h1>Build & Operation Guides</h1>

Each configuration includes step-by-step documentation for construction, alignment, acquisition, and processing.

| Guide type | Contents |
|---|---|
| **Optical construction and alignment** | Model-specific build manuals and alignment procedures |
| **Imaging parameter optimization** | Recommended exposure times, laser powers, and detection filters |
| **Post-acquisition processing** | Registration, stitching, and multicolor alignment workflows |
| **MCC installation** | Installation guide for the Mission Control Center control GUI |

> [!NOTE]
> Build time varies depending on the variant and user experience:  
> **SLIM**: ~1 week  
> **FullMoon / DeepSky / Galaxy**: 2–6 weeks

---

<h1>Mission Control Center</h1>

## A shared operational architecture for the descSPIM family

The **Mission Control Center (MCC)** is a unified, Python-based control framework developed to operate the major hardware components of both **descSPIM-basic** and the **descSPIM-Advanced** systems.

MCC provides a common operational interface across the descSPIM family and enables integrated control of key microscope components, including:

- motorized stages,
- scientific cameras,
- laser sources,
- filter wheels,
- galvanometric scanners,
- and other variant-specific hardware modules.

<p>
  <img src=<img width="2114" height="1905" alt="アセット 164" src="https://github.com/user-attachments/assets/8f3f431e-e155-48d2-9521-5b7bd2948cdd"  width="100%" />
</p>

By consolidating these functions into a single control environment, MCC reduces the need for multiple independent software tools and supports reproducible operation across different descSPIM configurations.

> [!IMPORTANT]
> MCC is designed to control the principal hardware components of **descSPIM-basic** and all **descSPIM-Advanced variants**.  
> The main exception is the **hyperspectral detector in descSPIM-Galaxy**, which is operated separately using the dedicated Galaxy GUI.

---

<h1>MCC Support Across the descSPIM Family</h1>

| System / Variant | Main hardware configuration | MCC support |
|---|---|---|
| **descSPIM-basic** | Stages, camera, laser source | **Full integrated control** |
| **descSPIM-FullMoon** | Stages, camera, laser source, filter wheel, galvanometric scanner | **Full integrated control** |
| **descSPIM-DeepSky** | Stages, camera, pattern generator, laser source | **Full integrated control** |
| **descSPIM-Galaxy** | Stages, Thorlabs CMOS camera, laser source, filter wheel | **Integrated control by MCC** |
| **descSPIM-SLIM** | Stages, camera | **Full integrated control** |

> [!NOTE]
> In **descSPIM-Galaxy**, MCC controls the standard microscope hardware components, including the stages, Thorlabs CMOS camera, laser source, and filter wheel.  
> The hyperspectral detector is controlled separately using the dedicated **Galaxy GUI**.

For detailed installation, architecture, and developer information, please refer to the dedicated **Mission Control Center README**.

---

## Related Links

- [descSPIM-basic GitHub repository](https://github.com/dbsb-juntendo/descSPIM)
- [CUBIC Resource Site](http://cubic.riken.jp)
- [Data Processing Tools](https://github.com/dbsb-juntendo/descSPIM/blob/main/DOCs/Data%20processing.md)

---

## Terms and Conditions

### Creative Commons License

<a rel="license" href="http://creativecommons.org/licenses/by-nc-sa/4.0/">
  <img alt="Creative Commons License" style="border-width:0" src="https://i.creativecommons.org/l/by-nc-sa/4.0/88x31.png" />
</a>

This work is licensed under a  
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License](http://creativecommons.org/licenses/by-nc-sa/4.0/).

By using **descSPIM-Advanced**, you agree to the following:

- Academic use only; commercial use requires author permission.
- Modifications and redistribution are allowed under CC BY-NC-SA 4.0.
- Cite the original work in all publications and presentations.
- The authors are not responsible for damages or misuse.
- All disputes shall be governed by Japanese law.

---

## References

- **Otomo, K. et al.** *descSPIM: an affordable and easy-to-build light-sheet microscope optimized for tissue clearing techniques.* **Nat. Commun. 15, 4941 (2024).**
- **Susaki, E. A. et al.** *Versatile whole-organ/body staining and imaging based on electrolyte-gel properties of biological tissues.* **Nat. Commun. 11, 1982 (2020).**
- **Matsumoto, K. et al.** *Advanced CUBIC tissue clearing for whole-organ cell profiling.* **Nat. Protoc. 14, 3506–3537 (2019).**
- [CUBIC-HistoVision2.0 protocol](https://www.protocols.io/view/cubic-histovision2-0-n92ld1wyxl5b/v1)
- [CUBIC resource website](http://cubic.riken.jp)

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


