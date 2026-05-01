"""
spectroscopy/specshift.py
=========================
Post-dispersion-correction wavelength shift and lamp diagnostic utilities.

Workflow position
-----------------
  apall → identify → refspectra → dispcor → **apply_wavelength_shift** → (science)
                                                      ↓
                                           plot_lamp_spectra  (diagnostic)

The pixel shift stored in PIXSHIFT (written during the flexure measurement step)
is converted to an Ångström shift using the dispersion solution already applied by
dispcor (CD1_1 or CDELT1), then applied in-place to the WCS via iraf.specshift.
No pixel data are interpolated.
"""

import os
import glob

import numpy as np
import astropy.io.fits as fits
import matplotlib
matplotlib.use("TkAgg")           # safe default for the tkinter-based GUI
import matplotlib.pyplot as plt
from tkinter import messagebox


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_wavelength_shift(pipeline):
    """
    Apply a flexure shift to the wavelength WCS of all dispersion-corrected
    object **and** comparison spectra.

    For each file the function:

    1. Reads ``PIXSHIFT`` (pixel offset stored by the shift-measurement step).
    2. Reads the dispersion ``CD1_1`` (or ``CDELT1``) in Å/pixel.
    3. Computes ``Δλ = PIXSHIFT × dispersion``.
    4. Calls ``iraf.specshift`` to update the WCS in-place (zero interpolation).

    Files that do not carry a ``PIXSHIFT`` keyword are skipped with a warning.

    Parameters
    ----------
    pipeline : Pipeline
        Active pipeline instance.  Uses ``pipeline.corrected_obj`` and
        ``pipeline.corrected_comp`` (both set by ``run_dispcor``).
    """
    from pyraf import iraf

    iraf.noao(_doprint=0)
    iraf.twodspec(_doprint=0)
    iraf.longslit(_doprint=0)

    # Collect all calibrated files to shift (objects first, then comps)
    obj_files  = list(pipeline.corrected_obj  or [])
    comp_files = list(pipeline.corrected_comp or [])

    if not obj_files and not comp_files:
        # Fall back: auto-discover from glob if the lists are empty
        obj_files  = sorted(glob.glob("*w.ms.fits"))
        comp_files = []
        pipeline.log(
            "Warning: corrected_obj/corrected_comp are empty. "
            "Auto-discovered object files from glob."
        )

    all_files = obj_files + comp_files

    if not all_files:
        messagebox.showerror(
            "Specshift Error",
            "No dispersion-corrected spectra found.\n"
            "Run Dispersion Correction first.",
        )
        return

    pipeline.log(
        f"\n── Applying wavelength shifts to {len(all_files)} spectrum/spectra ──"
    )

    shifted_count = 0
    skipped_count = 0

    for spec_file in all_files:
        if not os.path.exists(spec_file):
            pipeline.log(f"  Skipping (file not found): {spec_file}")
            skipped_count += 1
            continue

        try:
            hdr = fits.getheader(spec_file)
        except Exception as exc:
            pipeline.log(f"  Skipping (header read error): {spec_file}: {exc}")
            skipped_count += 1
            continue

        # 1. Pixel shift from header
        pix_shift = None
        if "PIXSHIFT" in hdr:
            pix_shift = float(hdr["PIXSHIFT"])
        else:
            # Fallback: IRAF dispcor strips custom keywords. Check original .ms.fits
            orig_file = spec_file.replace("w.ms.fits", ".ms.fits")
            if orig_file != spec_file and os.path.exists(orig_file):
                try:
                    orig_hdr = fits.getheader(orig_file)
                    if "PIXSHIFT" in orig_hdr:
                        pix_shift = float(orig_hdr["PIXSHIFT"])
                except Exception:
                    pass

        if pix_shift is None:
            pipeline.log(f"  Skipping (no PIXSHIFT in {spec_file} or {orig_file}): {spec_file}")
            skipped_count += 1
            continue

        # 2. Dispersion: prefer CD1_1, fall back to CDELT1
        if "CD1_1" in hdr:
            dispersion = float(hdr["CD1_1"])
        elif "CDELT1" in hdr:
            dispersion = float(hdr["CDELT1"])
        else:
            pipeline.log(
                f"  Skipping (no CD1_1/CDELT1, cannot compute Δλ): {spec_file}"
            )
            skipped_count += 1
            continue

        # 3. Wavelength shift in Ångströms
        wave_shift = pix_shift * dispersion

        # 4. Apply via iraf.specshift (WCS-only, no interpolation)
        try:
            iraf.specshift(
                spectra=spec_file,
                shift=wave_shift,
                mode="h",
            )
            pipeline.log(
                f"  Shifted {spec_file}  "
                f"(PIXSHIFT={pix_shift:+.3f} px → Δλ={wave_shift:+.3f} Å)"
            )
            shifted_count += 1
        except Exception as exc:
            pipeline.log(f"  Error shifting {spec_file}: {exc}")
            skipped_count += 1

    summary = (
        f"Wavelength shift complete: "
        f"{shifted_count} shifted, {skipped_count} skipped."
    )
    pipeline.log(summary)
    messagebox.showinfo("Specshift Complete", summary)


def plot_lamp_spectra(pipeline):
    """
    Overplot all dispersion-corrected comparison lamp spectra on one figure.

    This is a diagnostic to check that all lamp frames share a consistent
    wavelength solution after the shift has been applied (or to reveal any
    remaining offsets before the shift step).

    The figure is also saved as ``lamp_comparison.png`` in the current working
    directory.

    Parameters
    ----------
    pipeline : Pipeline
        Active pipeline instance.  Uses ``pipeline.corrected_comp``.
    """
    comp_files = list(pipeline.corrected_comp or [])

    if not comp_files:
        # Auto-discover
        comp_files = sorted(glob.glob("*w.ms.fits"))
        pipeline.log(
            "Warning: corrected_comp is empty. "
            "Auto-discovered calibrated files from glob."
        )

    if not comp_files:
        messagebox.showerror(
            "Plot Error",
            "No dispersion-corrected lamp spectra found.\n"
            "Run Dispersion Correction first.",
        )
        return

    pipeline.log(
        f"\n── Plotting {len(comp_files)} lamp spectrum/spectra ──"
    )

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.set_title("Dispersion-Corrected Lamp Spectra (Comparison)", fontsize=13)
    ax.set_xlabel("Wavelength (Å)")
    ax.set_ylabel("Counts / Flux")

    plotted = 0
    for spec_file in comp_files:
        if not os.path.exists(spec_file):
            pipeline.log(f"  Skipping (not found): {spec_file}")
            continue

        try:
            with fits.open(spec_file) as hdul:
                data = hdul[0].data
                hdr  = hdul[0].header

            # Flatten to 1-D (dispcor output can be 1×1×N or 1×N or N)
            flux = data.squeeze()
            if flux.ndim != 1:
                pipeline.log(
                    f"  Warning: unexpected data shape {data.shape} for {spec_file}. "
                    "Using first row."
                )
                flux = flux[0]

            npts = flux.size

            # Build wavelength axis from WCS
            crval = float(hdr.get("CRVAL1", 0.0))
            crpix = float(hdr.get("CRPIX1", 1.0))
            if "CD1_1" in hdr:
                cdelt = float(hdr["CD1_1"])
            else:
                cdelt = float(hdr.get("CDELT1", 1.0))

            wavelength = crval + (np.arange(npts) - (crpix - 1)) * cdelt

            label = os.path.basename(spec_file)
            ax.plot(wavelength, flux, label=label, lw=0.8, alpha=0.85)
            plotted += 1

        except Exception as exc:
            pipeline.log(f"  Error reading {spec_file}: {exc}")

    if plotted == 0:
        messagebox.showerror("Plot Error", "Could not read any lamp spectra.")
        plt.close(fig)
        return

    ax.legend(fontsize=7, loc="upper right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    # Save
    outpath = os.path.join(os.getcwd(), "lamp_comparison.png")
    try:
        fig.savefig(outpath, dpi=150)
        pipeline.log(f"  Lamp comparison plot saved → {outpath}")
    except Exception as exc:
        pipeline.log(f"  Warning: could not save lamp plot: {exc}")

    pipeline.log(f"Plotted {plotted} lamp spectra.")
    plt.show()
