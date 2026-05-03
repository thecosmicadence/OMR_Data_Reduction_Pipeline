import glob

from tkinter import messagebox
from spectroscopy.refer import is_imagetyp


def run_dispcor(pipeline):
    """
    Apply dispersion correction to all object and comparison spectra using
    IRAF ``dispcor``.

    Corrected file names are stored in three pipeline attributes:

    * ``pipeline.corrected_files``  — combined list (backward-compatible).
    * ``pipeline.corrected_obj``    — dispersion-corrected object spectra.
    * ``pipeline.corrected_comp``   — dispersion-corrected comparison spectra.

    Parameters
    ----------
    pipeline : Pipeline
        The active pipeline instance.
    """
    from pyraf import iraf

    iraf.noao()
    iraf.imred()
    iraf.ccdred()
    iraf.specred()

    if not pipeline.referenced_obj:
        ref_obj_candidates = glob.glob("*tbdf.ms.fits")
        pipeline.referenced_obj = sorted([
            f for f in ref_obj_candidates if is_imagetyp(f, 'object')
        ])

    # Filter for identified comparison files
    if not pipeline.identified_comp:
        comp_candidates = glob.glob("*tb.ms.fits") + glob.glob("*tbd.ms.fits")
        pipeline.identified_comp = sorted([
            f for f in comp_candidates if is_imagetyp(f, 'comp')
        ])

    import os
    all_spectra = sorted(pipeline.referenced_obj + (pipeline.identified_comp or []))
    corrected_files = list(pipeline.corrected_files or [])
    corrected_obj   = list(pipeline.corrected_obj  or [])
    corrected_comp  = list(pipeline.corrected_comp or [])

    # Sanity check: Ensure that the dispersion database files are valid (not 0 bytes)
    # Sanity check: Ensure the MASTER dispersion database file is valid
    if getattr(pipeline, "master_comp", None):
        basename = pipeline.master_comp.replace(".fits", "")
        db_file = os.path.join("database", "id" + basename)
        if not os.path.exists(db_file) or os.path.getsize(db_file) == 0:
            msg = (
                f"No valid master dispersion solution found for {pipeline.master_comp}!\n\n"
                f"The database file '{db_file}' is missing or empty. "
                f"Did you forget to 'Identify' lines and fit the curve?"
            )
            messagebox.showerror("Missing Dispersion Solution", msg)
            pipeline.log(f"Aborting dispcor: Invalid master dispersion solution.")
            return

    messagebox.showinfo(
        "Update!",
        "Running dispersion correction on the following spectra:\n"
        + "\n".join(all_spectra),
    )

    for f in all_spectra:
        output_name = f.replace(".ms.fits", "w.ms.fits")
        try:
            iraf.dispcor(
                input=f,
                output=output_name,
                verbose="no",
                mode="h",
            )
            corrected_files.append(output_name)

            # Split into object vs comparison lists for downstream steps
            if f in pipeline.referenced_obj:
                corrected_obj.append(output_name)
            elif f in pipeline.identified_comp:
                corrected_comp.append(output_name)
            else:
                # This should theoretically be unreachable, but good to keep as a fallback
                pipeline.log(
                    f"  Note: could not determine origin for {f}; "
                    "added to corrected_files only."
                )

            pipeline.log(f"Dispersion correction completed: {output_name}")
        except Exception as e:
            pipeline.log(f"Error running dispcor on {f}: {e}")

    pipeline.corrected_files = corrected_files
    pipeline.corrected_obj   = corrected_obj
    pipeline.corrected_comp  = corrected_comp

    pipeline.log(
        f"\nDispcor summary: {len(corrected_obj)} object(s), "
        f"{len(corrected_comp)} comparison(s) calibrated."
    )