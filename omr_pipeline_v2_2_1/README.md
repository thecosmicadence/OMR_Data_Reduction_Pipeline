# 🔭 VBO OMR Spectroscopic Data Reduction Pipeline

> **Instrument:** Low-resolution Optomechanical Research (OMR) Spectrograph — Vainu Bappu Observatory ([VBO](https://www.iiap.res.in/centers/vbo/))  
> **Pipeline version:** v2.2.1 
> **Purpose:** Automated low-resolution spectroscopic data reduction — from raw FITS frames to wavelength-calibrated 1-D spectra

---

## Table of Contents

- [Overview](#overview)
- [Pipeline Stages](#pipeline-stages)
- [File Naming Convention](#file-naming-convention)
- [Requirements](#requirements)
- [Running with Docker (Recommended)](#running-with-docker-recommended)
- [Running Natively (Advanced)](#running-natively-advanced)
- [Typical Workflow](#typical-workflow)
- [Directory Structure](#directory-structure)
- [Troubleshooting](#troubleshooting)

---

## Overview

This pipeline takes a night's worth of raw VBO/OMR FITS files and processes them through six automated phases, producing wavelength-calibrated 1-D spectra. It uses a **Tkinter GUI** for user interaction and **PyRAF/IRAF** for the core reduction tasks.

```
Raw .fit frames  →  [6 phases]  →  *w.ms.fits (wavelength-calibrated spectra)
```

---

## Pipeline Stages

| # | Phase | What it does | Output files |
|---|-------|-------------|-------------|
| **0** | **Startup & IRAF Init** | Launches the GUI and loads IRAF packages | — |
| **1** | **File Ingestion** | Scans FITS headers, segregates by PI / grating / centwave, auto-clips bad bias frames (3-sigma clipping), builds master bias | `master_bias.fit` |
| **2** | **Preprocessing** | Trims (`trimsec` chosen based on edge-gradient detection method)), bias-subtracts, dark-corrects, flat-fields all frames | `*_tbdf.fit` (objects), `*_tbd.fit` (comps) |
| **3** | **Spectral Extraction** | Runs IRAF `apall` interactively on object and comparison lamp frames | `*.ms.fits` |
| **4** | **Line Identification** | User selects a master lamp; pipeline computes FFT cross-correlation shifts for all comp frames, then runs IRAF `identify` interactively on the master | `PIXSHIFT` in headers, `database/` solution |
| **5** | **Dispersion Correction** | Assigns `REFSPEC1` to all frames, applies `dispcor`, corrects WCS shifts with `specshift`, plots final lamp comparison | `*w.ms.fits` |

---

## File Naming Convention

Each reduction step appends a letter to the filename so provenance is always clear:

```
raw.fit
 └── *_t.fit           ← Trimmed
      └── *_tb.fit     ← Bias-subtracted
           ├── *_tbd.fit       ← Dark-corrected (comp frames)
           └── *_tbdf.fit      ← Dark + Flat-fielded (object frames)
                ├── *_tbd.ms.fits    ← Extracted comp spectrum
                ├── *_tbdf.ms.fits   ← Extracted object spectrum
                ├── *_tbdw.ms.fits   ← Wavelength-calibrated comp
                └── *_tbdfw.ms.fits  ← Wavelength-calibrated object
```

> After `specshift`, the WCS of `*w.ms.fits` files is updated **in-place** — no extra copy is made.

---

## Requirements

### Running with Docker (easiest — no IRAF or Python setup needed)
- [Docker](https://docs.docker.com/get-docker/) or [Podman](https://podman.io/getting-started/installation) (Fedora ships with Podman)
- A Linux desktop with an X11 display (for the GUI)

### Running natively
- Python **3.11**
- IRAF (v2.17+) installed and accessible
- SAOImage DS9 (for `pyds9` display)
- All packages listed in `requirements.txt`

---

## Running with Docker (Recommended)

This is the **recommended method** for running on any system. Docker bundles Python, IRAF, DS9, and all dependencies — you don't need to install anything else.

### Step 1 — Install Docker / Podman

**Fedora:**
```bash
sudo dnf install docker
sudo systemctl enable --now docker
sudo usermod -aG docker $USER   # log out and back in after this
```

**Ubuntu / Debian:**
```bash
sudo apt-get install docker.io
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

**macOS / Windows:** Install [Docker Desktop](https://www.docker.com/products/docker-desktop/)

---

### Step 2 — Get the pipeline

```bash
git clone https://github.com/thecosmicadence/OMR_Data_Reduction_Pipeline/omr_pipeline_v2_2_1.git
cd omr_pipeline_v2_2
```

---

### Step 3 — Build the Docker image

> ⚠️ This only needs to be done **once**. It downloads and installs everything (~2 GB, takes 5–15 minutes).

```bash
docker build -t omr-pipeline .
```

---

### Step 4 — Allow the GUI to display on your screen

```bash
xhost +local:docker
```

> Run this once per login session. To undo it afterwards: `xhost -local:docker`

---

### Step 5 — Run the pipeline

Because GUI applications and data permissions handle security differently across Linux distributions, choose the command that matches your setup. Replace /path/to/your/fits/data with the full path to your observation folder.

#### For Ubuntu / Debian (using Docker):
```bash
docker run --rm -it \
  -e DISPLAY=$DISPLAY \
  -u $(id -u):$(id -g) \
  -e USER=$USER \
  -e MPLCONFIGDIR=/tmp/matplotlib \
  -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
  -v /path/to/your/fits/data:/data:z \
  --network host \
  --security-opt label=disable \
  omr-pipeline
```
#### For Fedora / RHEL (using Podman):
```bash
podman run --rm -it \
  -e DISPLAY=$DISPLAY \
  -e USER=$(id -un) \
  -e MPLCONFIGDIR=/tmp/matplotlib \
  -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
  -v /path/to/your/fits/data:/data:z \
  --network host \
  --userns=keep-id \
  --security-opt label=disable \
  localhost/omr-pipeline
```

Replace `/path/to/your/fits/data` with the **full path to your night's observation folder** (e.g. the folder containing your `.fit` files).

Inside the GUI, navigate to `/data/` when prompted to select the data directory.

---

### Sharing the image (so others skip the build step)

```bash
# Anyone else can then run it using the appropriate OS-specific command from Step 5, 
# simply replacing 'omr-pipeline' or 'localhost/omr-pipeline' with the pulled image:
thecosmicadence/omr-pipeline
docker run --rm -it \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /path/to/data:/data \
  --network host \
  thecosmicadence/omr-pipeline
```

---

## Running Natively (Advanced)

If you already have IRAF installed and prefer not to use Docker:

### 1. Create a virtual environment with `uv`

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create a Python 3.11 environment
uv venv --python 3.11 .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Set IRAF environment variables

```bash
export iraf=/usr/lib/iraf/      # or wherever IRAF is installed
export IRAFARCH=linux64
```

### 3. Run

```bash
python main.py
```

---

## Typical Workflow

Once the GUI is open, follow these steps in order:

```
1. Click "Select Directory"
   → Navigate to your night's raw data folder
   → The pipeline auto-creates the reduction directory structure

2. Select your PI name from the dropdown

3. Select the grating / centwave configuration

4. Click "Preprocess"
   → Automatic: bias combination, trimming, bias subtraction,
                 dark correction, flat-fielding
   → Interactive: flat response fitting (IRAF window opens)

5. Click "Aperture Extraction"
   → Fully Automatic.

6. Click "Identify"
   → Select the master lamp frame from the dropdown
   → Automatically calculates the pixel shift wrt master lamp frame and writes to the header. The corresponding lamp spectra to that of the object frame is also updated in the header.
   → Interactive: IRAF identify window opens — mark arc lines. (place the cursor on the line, press 'm' and type the corresponding wavelength value from the line identification chart. Then press enter. Do this for all the lines. Make sure to press 'f' to fit the polynomial after every 5-10 lines are marked. Delete outliers by placing the cursor at the outlier and pressing 'd'. Press 'f' again before going back to marking lines. Press 'q' to quit the identify window)

7. Click "Reference Spectra"
   → Fully automatic: assigns reference spectra

8. Click "Dispersion Correction"
   → Fully automatic: assigns reference spectra, runs dispcor

9. Click "Apply Waveshift"
   → Fully automatic: runs specshift based on the pixel shift noted down in the header

10. Click "Plot Lamp Spectra"
   → Fully automatic: to ensure that the lamp spectra are line identified properly using the master frame as reference

10. Click "Plot any Spectra" or "Display" (optional)
   → Opens IRAF splot for interactive spectrum inspection (or) opens any frame on DS9 for manual inspection during any stage of the processing.
```

---

## Directory Structure

After running on a night's data, the reduction directory looks like this:

```
<observation_night>/
├── <PI_name>/
│   └── <grating>_<centwave>/
│       ├── bias/             ← bias frames
│       ├── flat/             ← flat frames
│       ├── comp/             ← comparison lamp frames
│       ├── object/           ← science object frames
│       ├── dark/             ← dark frames (if any)
│       ├── master_bias.fit
│       ├── master_flat.fit
│       ├── database/         ← IRAF wavelength solution
│       ├── lamp_comparison.png
│       └── *.ms.fits / *w.ms.fits  ← final spectra
```

---

## Troubleshooting

### GUI doesn't open — "cannot open display"
```bash
# Make sure you ran xhost first:
xhost +local:docker
# Check that DISPLAY is set:
echo $DISPLAY    # should show :1 or similar (not empty)
```

### "No such file: login.cl" error from PyRAF
PyRAF auto-generates `login.cl` on first run in the working directory. This is normal and handled automatically. If it persists, check that `/app/pyraf/` (or your working directory) is writable.

### DS9 / pyds9 connection fails
The container uses `--network host` so DS9 inside can talk to itself over XPA. If DS9 still fails to connect:
```bash
# Test that all Python imports work:
docker run --rm omr-pipeline python3 -c \
  "import pyraf, astropy, scipy, matplotlib, pyds9; print('All OK')"
```

### Build fails on `imexam`
The `imexam` package is installed directly from its GitHub repository. If there's a network error during build, retry:
```bash
docker build --no-cache -t omr-pipeline .
```

### Updating after code changes
```bash
# Rebuild the image (fast — Docker caches unchanged layers)
docker build -t omr-pipeline .
```

### Updating dependencies after adding a new package
```bash
# In your local venv:
pip freeze > requirements.txt
# Then rebuild:
docker build -t omr-pipeline .
```

---

## Citation / Acknowledgement

If you use this pipeline for published work, please acknowledge the **Vainu Bappu Observatory** and reference this repository.

---

## Contact

For issues or questions, please open a [GitHub Issue](https://github.com/YOUR_USERNAME/VBO_Data_Reduction_Pipeline/issues).
