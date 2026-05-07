<h1>What is descSPIM-Advanced?</h1>

**descSPIM-Advanced** is an open, extensible light-sheet fluorescence microscopy (LSFM) ecosystem designed for cleared-tissue imaging.

It builds on **[descSPIM-basic](https://github.com/dbsb-juntendo/descSPIM)**  
(**desktop-equipped SPIM for cleared specimens**), our previously developed open-hardware LSFM platform for tissue-clearing applications. descSPIM-basic was designed to make cleared-tissue LSFM easier to build, operate, and adopt in individual laboratories.

As of **April 2026**, more than **50 descSPIM-basic systems** have been independently built worldwide, demonstrating the accessibility and broad deployability of the original platform.

<p>
  <img width="1806" height="862" alt="GitHub figures" src="https://github.com/user-attachments/assets/4d9cdc04-36ee-414c-bde5-31b967f492d4" />
</p>

While descSPIM-basic provided an accessible entry point to cleared-tissue LSFM, advanced applications still require greater imaging flexibility, including larger fields of view, higher spatial resolution, improved illumination, expanded color capability, and simplified deployment.

| Limitation of descSPIM-basic | Need addressed by descSPIM-Advanced |
|---|---|
| Single-side illumination | Dual-side illumination |
| Residual striping in large-volume imaging | Reduced attenuation and striping |
| Low-magnification detection | Higher spatial resolution |
| Three- to four-channel imaging | Super-multicolor / hyperspectral imaging (7–11 colors) |
| Remaining optical and cost complexity | Simpler and lower-cost configurations |

> [!IMPORTANT]
> **descSPIM-Advanced expands descSPIM from a single accessible LSFM design into a scalable imaging ecosystem.**

Depending on the selected configuration, descSPIM-Advanced supports:

- large field-of-view whole-organ imaging,
- high-resolution volumetric imaging,
- super-multicolor 3D imaging,
- and low-cost routine cleared-tissue imaging.

These capabilities are realized through four interoperable variants — **FullMoon, DeepSky, Galaxy, and SLIM** — each extending the descSPIM platform toward a distinct imaging regime.

---

<h1>Common control architecture</h1>

A central feature of descSPIM-Advanced is the **Mission Control Center (MCC)**, a shared operational architecture for the descSPIM family.

MCC provides a Python-based control interface that standardizes operation across both **descSPIM-basic** and **descSPIM-Advanced** systems. It brings together key microscope functions — including stage movement, camera acquisition, laser control, filter switching, and galvanometric scanner operation — within a unified GUI.

<p>
  <img src="https://github.com/user-attachments/assets/8f3f431e-e155-48d2-9521-5b7bd2948cdd" width="100%" alt="Mission Control Center GUI" />
</p>

By consolidating hardware control into a single interface, MCC reduces the need for separate software environments and supports reproducible operation across different descSPIM configurations.

> [!IMPORTANT]
> MCC is designed to control the principal hardware components of **descSPIM-basic** and all **descSPIM-Advanced variants**.  
> The main exception is the **hyperspectral detector in descSPIM-Galaxy**, which is operated separately using the dedicated Galaxy GUI.

---

<h1>The descSPIM-Advanced variants</h1>

The **descSPIM-Advanced platform** consists of four interoperable variants, each optimized for a distinct imaging regime.

| Variant | Main capability | Representative application |
|---|---|---|
| **descSPIM-FullMoon** | Large field-of-view imaging | Single-field volumetric imaging enabled by a 43-mm sensor-diagonal field of view |
| **descSPIM-DeepSky** | High spatial resolution | High-resolution volumetric imaging for three-dimensional histology |
| **descSPIM-Galaxy** | Super-multicolor / hyperspectral imaging | 7–11-color three-dimensional imaging of cleared tissues and optical phantoms |
| **descSPIM-SLIM** | Low-cost simplified deployment | Rapid, low-cost deployment for 3–4-color cleared-tissue imaging |

## Variant highlights

**descSPIM-FullMoon** combines dual-side illumination, light-sheet pivoting, and a 60-MP camera with a 43-mm sensor diagonal to enable large-FOV, single-field volumetric imaging.

**descSPIM-DeepSky** combines light-sheet pivoting, high-resolution imaging optics, a four-slot filter changer, and a variable slit to support high-resolution 3D histology with improved lateral and axial resolution.

**descSPIM-Galaxy** integrates dual-camera detection, hyperspectral imaging, a six-slot filter changer, and a dedicated spectral unmixing pipeline to enable super-multicolor cleared-tissue imaging of up to 11 colors.

**descSPIM-SLIM** adopts an open-top configuration, simplified optics, a variable slit, and affordable laser sources to provide a rapidly deployable and highly accessible configuration at approximately USD 15,000.

Together, the **descSPIM family** provides a scalable cleared-tissue LSFM ecosystem, ranging from entry-level, low-cost systems to high-performance configurations for large-volume, high-resolution, and high-channel imaging.

---

<h1>Build and operation guides</h1>

Each configuration includes step-by-step documentation for system construction, optical alignment, image acquisition, and post-acquisition processing.

| Guide type | Contents |
|---|---|
| **Optical construction and alignment** | Model-specific build manuals and alignment procedures |
| **Imaging parameter optimization** | Recommended exposure times, laser powers, and detection filters |
| **Post-acquisition processing** | Registration, stitching, and multicolor alignment workflows |
| **MCC installation** | Installation guide for the Mission Control Center control GUI |

> [!NOTE]
> Build time varies depending on the variant and user experience:  
> **SLIM**: 2–5 h from scratch  
> **FullMoon**: 9–18 h from scratch  
> **DeepSky**: 9–15 h from scratch  
> **Galaxy**: 8–14 h from scratch

---

<h1>Mission Control Center overview</h1>

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
| **descSPIM-basic** | Stages, camera, laser source | **Fully integrated control** |
| **descSPIM-FullMoon** | Stages, camera, laser source, filter wheel, galvanometric scanner | **Fully integrated control** |
| **descSPIM-DeepSky** | Stages, camera, pattern generator, laser source | **Fully integrated control** |
| **descSPIM-Galaxy** | Stages, Thorlabs CMOS camera, laser source, filter wheel | **Integrated control by MCC** |
| **descSPIM-SLIM** | Stages, camera | **Fully integrated control** |

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


