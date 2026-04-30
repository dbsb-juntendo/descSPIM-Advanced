<h1>What is the descSPIM-Advanced platform?</h1>

**descSPIM-Advanced** is an open and extensible light-sheet fluorescence microscopy (LSFM) ecosystem for cleared-tissue imaging.

It builds on our previous open-hardware platform, **[descSPIM-basic](https://github.com/dbsb-juntendo/descSPIM)**  
(**desktop-equipped SPIM for cleared specimens**), a low-cost and easy-to-build LSFM system for tissue-clearing applications.

As of **April 2026**, more than **50 independently built descSPIM-basic systems** have been established worldwide, demonstrating the accessibility and broad deployability of the original platform.

---

<h1>Platform concept</h1>

<p>
  <img src="https://github.com/user-attachments/assets/73d1c159-37be-4f4f-87a0-465933087797" width="330" />
  <img src="https://github.com/user-attachments/assets/49bf6eeb-6fc2-4a57-acee-92f118a8f9e9" width="380" />
</p>

descSPIM-Advanced extends the original descSPIM-basic concept from a single accessible LSFM design into a scalable imaging ecosystem.

The platform addresses key limitations of descSPIM-basic while preserving its accessibility:

| Limitation of descSPIM-basic | Need addressed by descSPIM-Advanced |
|---|---|
| Single-side illumination | More uniform imaging of large cleared samples |
| Residual striping in large-volume imaging | Reduced attenuation and striping |
| Low-magnification detection | Higher spatial resolution |
| Three- to four-channel imaging | Ultra-multicolor / hyperspectral imaging |
| Remaining optical and cost complexity | Simpler and lower-cost configurations |

Depending on the selected configuration, descSPIM-Advanced enables:

- expanded whole-organ field-of-view imaging,
- subcellular-resolution volumetric imaging,
- ultra-multicolor 3D imaging,
- and low-cost routine cleared-tissue imaging.

These capabilities are implemented through four interoperable variants — **FullMoon, DeepSky, Galaxy, and SLIM** — which extend both the conceptual and functional range of descSPIM-basic.

---

<h1>Common control architecture</h1>

A key feature of descSPIM-Advanced is the **Mission Control Center (MCC)**, a shared operational architecture for the descSPIM family.

MCC provides a common Python-based control interface for the major hardware components of both **descSPIM-basic** and **descSPIM-Advanced** systems. It integrates core microscope operations such as stage movement, camera acquisition, laser control, filter switching, and galvanometric scanner operation into a unified GUI.

<p>
  <img src="https://github.com/user-attachments/assets/8f3f431e-e155-48d2-9521-5b7bd2948cdd" width="100%" alt="Mission Control Center GUI" />
</p>

By combining multiple hardware-control functions into a single interface, MCC reduces the need for separate software environments and supports reproducible operation across different descSPIM configurations.

> [!IMPORTANT]
> MCC is designed to control the principal hardware components of **descSPIM-basic** and all **descSPIM-Advanced variants**.  
> The main exception is the **hyperspectral detector in descSPIM-Galaxy**, which is operated separately using the dedicated Galaxy GUI.

---

<h1>The descSPIM-Advanced variants</h1>

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

<h1>Mission Control Center Overview</h1>

The **Mission Control Center (MCC)** is a unified, Python-based control framework for the descSPIM family.

It provides centralized operation of the main hardware modules used across **descSPIM-basic** and **descSPIM-Advanced**, including:

- motorized stages,
- scientific cameras,
- laser sources,
- filter wheels,
- galvanometric scanners,
- and other variant-specific hardware modules.

The table below summarizes how MCC supports the main hardware configurations across the descSPIM family.

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

For detailed installation, architecture, and developer information, please refer to the dedicated **[Mission Control Center README](https://github.com/dbsb-juntendo/descSPIM-Advanced/tree/main/Mission%20Control%20Center)**.

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


