import glob

from tkinter import messagebox
from spectroscopy.refer import is_imagetyp


def run_dispcor(pipeline):
    """
    Interactively apply dispersion correction to spectra using IRAF ``dispcor``.

    The user is presented with a multi-select dropdown to pick one spectrum
    at a time.  After each run the user is asked whether to continue.
    Corrected file names are appended to ``pipeline.corrected_files``.

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
        
    # Filter for Identified Comparison files
    if not pipeline.identified_comp:
        comp_candidates = glob.glob("*tb.ms.fits") + glob.glob("*tbd.ms.fits")
        pipeline.identified_comp = sorted([
            f for f in comp_candidates if is_imagetyp(f, 'comp')
        ])

    all_spectra = sorted(pipeline.referenced_obj + (pipeline.identified_comp or []))
    corrected_files = list(pipeline.corrected_files or [])
    messagebox.showinfo(
        "Update!", "Running dispersion correction on the following spectra:\n" + "\n".join(all_spectra))

    for f in all_spectra:
        output_name = f.replace(".ms.fits", "w.ms.fits")
        try:
            iraf.dispcor(
                input=f,
                output=output_name,
                verbose="no",
                mode="h"
            )
            corrected_files.append(output_name)
            pipeline.log(f"Dispersion correction completed: {output_name}")
        except Exception as e:
            pipeline.log(f"Error running dispcor on {f}: {e}")


    pipeline.corrected_files = corrected_files