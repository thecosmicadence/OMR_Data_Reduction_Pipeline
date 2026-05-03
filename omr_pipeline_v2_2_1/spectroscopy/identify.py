import os
import subprocess
import glob

import astropy.io.fits as pyfits
from tkinter import messagebox

from utils.signal import measure_shift_integer
from spectroscopy.refer import is_imagetyp
from spectroscopy.aperture import parse_ut

def compute_shifts(ref_flux, extracted_comp_files):
    """
    Compute integer pixel shifts of all comparison frames relative to a reference flux.

    Parameters
    ----------
    ref_flux : ndarray
        1-D reference spectrum flux array.
    extracted_comp_files : list[str]
        Paths to the extracted ``.ms.fits`` comparison spectra.

    Returns
    -------
    dict
        ``{filename: shift_pixels}`` where each shift is an integer.
    """
    shift_dict = {}
    for frame in extracted_comp_files:
        tar_data = pyfits.getdata(frame)
        tar_flux = tar_data[0] if tar_data.ndim > 1 else tar_data
        shift = measure_shift_integer(ref_flux, tar_flux)
        shift_dict[frame] = shift
    return shift_dict


def run_identify(pipeline):
    """
    Drive the interactive line-identification workflow.

    Steps:
    1. Choose a master reference frame from the extracted comparison spectra.
    2. Compute pixel shifts of all other comparison frames vs the master.
    3. Store the pixel shift in the header as PIXSHIFT.
    4. Run IRAF ``identify`` interactively on the master.
    5. Exit the identify task as requested by user.

    Parameters
    ----------
    pipeline : Pipeline
        The active pipeline instance.
    """
    if not pipeline.extracted_comp:  
        extracted_candidates = glob.glob("*tbd.ms.fits")+glob.glob("*tb.ms.fits")
        pipeline.extracted_comp = sorted(
            f for f in extracted_candidates if is_imagetyp(f, 'comp')
        )
    if not pipeline.extracted_obj:
        extracted_candidates = glob.glob("*tbdf.ms.fits") + glob.glob("*tbf.ms.fits")
        pipeline.extracted_obj = sorted(
            f for f in extracted_candidates if is_imagetyp(f, 'object')
        )

    if not pipeline.extracted_comp:
        pipeline.log("No extracted comparison frames found.")
        return

    ref_list = pipeline.gui.show_file_dropdown(
        pipeline.extracted_comp, "Choose Master Reference Frame"
    )
    if not ref_list:
        pipeline.log("No reference frame selected.")
        return

    ref_frame = ref_list[0]
    messagebox.showinfo("Processing", f"Calculating shifts relative to Master: {ref_frame}")

    # Compute shifts
    ref_data = pyfits.getdata(ref_frame)
    ref_flux = ref_data[0] if ref_data.ndim > 1 else ref_data
    shift_dict = compute_shifts(ref_flux, pipeline.extracted_comp)

    for frame, shift in shift_dict.items():
        pipeline.log(f"Measured shift vs Master: {frame} -> {shift} pixels")
        try:
            with pyfits.open(frame, mode="update") as hdul:
                hdul[0].header["PIXSHIFT"] = (
                    shift,
                    "Pixel shift relative to master lamp"
                )
                hdul.flush()
        except Exception as e:
            pipeline.log(f"Error saving PIXSHIFT to {frame}: {e}")

    # Gather UT times for all lamp frames to time-match them to objects
    comp_times = {}
    for comp in pipeline.extracted_comp:
        try:
            hdr = pyfits.getheader(comp)
            t = parse_ut(hdr.get("UT", "0:0:0"))
            if t is not None:
                comp_times[comp] = t
        except Exception as e:
            pipeline.log(f"Warning: Could not read UT from {comp}: {e}")

    # Assign PIXSHIFT to each object frame based on nearest lamp
    if pipeline.extracted_obj:
        pipeline.log("\nAssigning lamp shifts to object frames based on nearest UT:")
    for obj in pipeline.extracted_obj:
        try:
            hdr = pyfits.getheader(obj)
            obj_t = parse_ut(hdr.get("UT", "0:0:0"))
            
            nearest_comp = None
            if obj_t is not None and comp_times:
                nearest_comp = min(comp_times.keys(), key=lambda k: abs(comp_times[k] - obj_t))
            elif pipeline.extracted_comp:
                nearest_comp = pipeline.extracted_comp[0]
                pipeline.log(f"  Warning: No UT match for {obj}, defaulting to {nearest_comp}")
                
            if nearest_comp is not None:
                shift = shift_dict[nearest_comp]
                with pyfits.open(obj, mode="update") as hdul:
                    hdul[0].header["PIXSHIFT"] = (
                        shift,
                        "Pixel shift relative to master lamp"
                    )
                    hdul.flush()
                diff_str = ""
                if nearest_comp in comp_times and obj_t is not None:
                    diff_str = f" (Δt = {abs(comp_times[nearest_comp] - obj_t):.1f}s)"
                pipeline.log(f"  {obj} -> {nearest_comp} -> {shift} px{diff_str}")
                
        except Exception as e:
            pipeline.log(f"Error assigning PIXSHIFT to {obj}: {e}")

    # Set master frame to pipeline state so refer.py can pick it up
    pipeline.master_comp = ref_frame

    # Interactive identify on master
    messagebox.showinfo("Manual Identify", f"Please manually identify the Master Frame: {ref_frame}")
    env = os.environ.copy()
    env.pop("PYTHONSTARTUP", None)
    env["HOME"] = pipeline.reduction_path
    subprocess.run(
        ["pyraf", "-c",
         f"noao; imred; ccdred; specred; identify(images='{ref_frame}', autowrite='yes', mode='h')"],
        env=env,
    )

    messagebox.showinfo("Update!", f"Identification complete for master frame: {ref_frame}")
