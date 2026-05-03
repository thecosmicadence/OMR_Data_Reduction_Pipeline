import glob

import astropy.io.fits as pyfits
from tkinter import messagebox

from spectroscopy.aperture import parse_ut

def is_imagetyp(filepath, expected_type):
    """Helper function to check if a FITS file matches the expected IMAGETYP."""
    try:
        # Read only the primary header (extension 0) for speed
        header = pyfits.getheader(filepath, 0)
        
        # FITS header values often have trailing whitespace, so we strip() 
        # and lower() to ensure a safe comparison.
        imagetyp = str(header.get('IMAGETYP', '')).strip().lower()
        return imagetyp == expected_type.lower()
    except Exception:
        # If the file isn't a valid FITS or can't be read, skip it
        return False
    
def assign_references(pipeline):
    """
    Assign the master comparison lamp to all object spectra and all other 
    comparison lamps, writing the ``REFSPEC1`` keyword directly to their FITS headers.

    IRAF's ``dispcor`` reads ``REFSPEC1`` to know which wavelength solution
    to apply to each object spectrum.

    Parameters
    ----------
    pipeline : Pipeline
        The active pipeline instance. Updates ``pipeline.referenced_obj``.
    """
    if not getattr(pipeline, "master_comp", None):
        messagebox.showerror(
            "Missing Master Frame",
            "No master comparison frame found. Please run 'Line Identify' first to select and identify a master frame."
        )
        return

    # Gather files if not already populated
    if not getattr(pipeline, "identified_comp", None):
        comp_candidates = glob.glob("*tbd.ms.fits") + glob.glob("*tb.ms.fits")
        pipeline.identified_comp = sorted([
            f for f in comp_candidates if is_imagetyp(f, 'comp')
        ])

    # Filter for Object files
    if not getattr(pipeline, "extracted_obj", None):
        obj_candidates = glob.glob("*tbdf.ms.fits") + glob.glob("*tbf.ms.fits")
        pipeline.extracted_obj = sorted([
            f for f in obj_candidates if is_imagetyp(f, 'object')
        ])

    frames_to_update = list(pipeline.extracted_obj)

    # Also assign to all other comparison frames (so dispcor processes them with master's solution)
    if pipeline.identified_comp:
        for comp in pipeline.identified_comp:
            if comp != pipeline.master_comp:
                frames_to_update.append(comp)

    if not frames_to_update:
        messagebox.showerror(
            "Missing Files",
            "No object or comparison spectra found to reference."
        )
        return

    pipeline.log("\nApplying REFSPEC1 keywords to headers...")
    successful = 0

    master_lamp = pipeline.master_comp

    for f in frames_to_update:
        try:
            with pyfits.open(f, mode="update") as hdul:
                hdul[0].header["REFSPEC1"] = (
                    f"{master_lamp} 1.",
                    "Reference spectrum for dispersion correction",
                )
                hdul.flush()
            successful += 1
            pipeline.log(f"Match: {f} <--- {master_lamp}")
        except Exception as e:
            pipeline.log(f"Error updating header for {f}: {e}")

    pipeline.referenced_obj = list(pipeline.extracted_obj)

    msg = f"Successfully assigned reference {master_lamp} to {successful} frame(s)."
    pipeline.log(msg)
    messagebox.showinfo("Refspectra Complete", msg)