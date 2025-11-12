# descSPIM-Galaxy

descSPIM-Galaxy: Python Control and Image Processing Instructions

## File Overview
- **Snapscan_Multiex_3D_GUI.py** — Controls hyperspectral 3D acquisition using imec HSI Snapscan and synchronizes sample/camera stages.  
- **Laser and Filter Wheel Controller_GUI.py** — Operates Cobolt/Skyra lasers and motorized filter wheel with synchronized triggering.  
- **preprocess_endmember_gui_single_xml.py** — Interpolates endmember spectra from measured CSVs and XML camera data.  
- **Endmember_and_BandExtraction_Combined.ipynb** — Extracts wavelength bands from hyperspectral image cubes.  
- **Unmix_GUI_Multi_ex.ipynb** — Performs NNLS/FCLSU spectral unmixing for each excitation channel.  
- **Stack_and_Avg_GUI.py** — Stacks and averages multi-loop images to generate representative 3D TIFFs.  
- **tiff_Downsample_and_ECC_Registration_GUI.ipynb** — Downsamples TIFF stacks and executes ECC-based rigid/affine registration.  
- **Downsample TIFF files from 3.45 µm to 5.5 µm.py** — Performs pixel-size downsampling of CMOS TIFF data.  
- **ECC Registration.py** — Executes rigid/affine image registration using Enhanced Correlation Coefficient alignment.  
- **ANTS_Registration_GUI.py** — Runs nonlinear (SyN) registration using ANTs with GUI support.

---

Please refer to **descSPIM-Galaxy_Python Control and Image processing Instructions.pdf** for detailed setup and usage.

