import glob

import astropy.io.fits as pyfits
from tkinter import messagebox

from spectroscopy.aperture import parse_ut


def assign_references(pipeline):
    """
    Pair each object spectrum to its nearest-UT comparison lamp, then write
    the ``REFSPEC1`` keyword directly to the object's FITS header.

    IRAF's ``dispcor`` reads ``REFSPEC1`` to know which wavelength solution
    to apply to each object spectrum.

    Parameters
    ----------
    pipeline : Pipeline
        The active pipeline instance.  Updates ``pipeline.referenced_obj``
        with the list of successfully updated object files.
    """
    # Gather files if not already populated
    if not pipeline.identified_comp:
        pipeline.identified_comp = sorted(
            glob.glob("*co*tbd.ms.fits") + glob.glob("*co*tb.ms.fits")
        )
    if not pipeline.extracted_obj:
        pipeline.extracted_obj = sorted(
            glob.glob("*obj*tbdf.ms.fits") + glob.glob("*obj*tbf.ms.fits")
        )

    if not pipeline.identified_comp or not pipeline.extracted_obj:
        messagebox.showerror(
            "Missing Files",
            "No identified comparison or object spectra found.",
        )
        return

    # Read UT timestamps from headers
    lamp_times = {}
    obj_times  = {}

    pipeline.log("\nReading timestamps from headers...")

    for f in pipeline.identified_comp:
        try:
            hdr = pyfits.getheader(f)
            val = parse_ut(hdr.get("UT", "0:0:0"))
            if val is not None:
                lamp_times[f] = val
        except Exception:
            pipeline.log(f"Warning: Could not read UT from {f}")

    for f in pipeline.extracted_obj:
        try:
            hdr = pyfits.getheader(f)
            val = parse_ut(hdr.get("UT", "0:0:0"))
            if val is not None:
                obj_times[f] = val
        except Exception:
            pipeline.log(f"Warning: Could not read UT from {f}")

    if not lamp_times:
        messagebox.showerror("Error", "Could not read 'UT' from any comparison frames.")
        return

    # Pair each object to the nearest lamp by UT
    pairs = []
    for obj_file, t_obj in obj_times.items():
        nearest_lamp = min(lamp_times, key=lambda l: abs(lamp_times[l] - t_obj))
        diff = abs(lamp_times[nearest_lamp] - t_obj)
        pipeline.log(f"Match: {obj_file} <--- {nearest_lamp} (ΔT = {diff:.1f}s)")
        pairs.append((obj_file, nearest_lamp))

    # Write REFSPEC1 keyword to FITS headers
    pipeline.log("\nApplying REFSPEC1 keywords to headers...")
    successful = 0

    for obj_file, ref_file in pairs:
        try:
            with pyfits.open(obj_file, mode="update") as hdul:
                hdul[0].header["REFSPEC1"] = (
                    f"{ref_file} 1.",
                    "Reference spectrum for dispersion correction",
                )
                hdul.flush()
            successful += 1
        except Exception as e:
            pipeline.log(f"Error updating header for {obj_file}: {e}")

    pipeline.referenced_obj = [p[0] for p in pairs]

    msg = f"Successfully assigned references for {successful} object frame(s)."
    pipeline.log(msg)
    messagebox.showinfo("Refspectra Complete", msg)