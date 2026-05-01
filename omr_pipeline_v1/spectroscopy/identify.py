import os
import subprocess

import astropy.io.fits as pyfits
from tkinter import messagebox

from utils.signal import measure_shift_integer


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
        shift = -measure_shift_integer(ref_flux, tar_flux)
        shift_dict[frame] = shift
    return shift_dict


def run_identify(pipeline):
    """
    Drive the interactive line-identification and automated reidentification workflow.

    Steps:
    1. Choose a master reference frame from the extracted comparison spectra.
    2. Compute pixel shifts of all other comparison frames vs the master.
    3. Run IRAF ``identify`` interactively on the master.
    4. Run IRAF ``reidentify`` (non-interactively, using calculated shifts) on all others.
    5. Re-open ``identify`` for the user to verify all frames.

    Parameters
    ----------
    pipeline : Pipeline
        The active pipeline instance.
    """
    if not pipeline.extracted_comp:
        pipeline.extracted_comp = sorted(
            pipeline.extracted_comp or []
            + list(__import__("glob").glob("*co*tbd.ms.fits"))
            + list(__import__("glob").glob("*co*tb.ms.fits"))
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

    # Interactive identify on master
    messagebox.showinfo("Manual Identify", f"Please manually identify the Master Frame: {ref_frame}")
    env = os.environ.copy()
    env.pop("PYTHONSTARTUP", None)
    subprocess.run(
        ["pyraf", "-c",
         f"noao; imred; ccdred; specred; identify(images='{ref_frame}', autowrite='yes', mode='h')"],
        env=env,
    )

    # Reidentify all other frames using pre-computed shifts
    for frame in pipeline.extracted_comp:
        if frame == ref_frame:
            continue

        relative_shift = shift_dict[frame]
        # Use tight windows for small shifts, wider for large shifts
        if abs(relative_shift) < 10.0:
            fixed_search, fixed_cradius = 5, 5
        else:
            fixed_search, fixed_cradius = 2, 2

        cmd = (
            f"noao; imred; ccdred; specred; "
            f"reidentify(reference='{ref_frame}', images='{frame}', "
            f"shift={relative_shift:.4f}, "
            f"search={fixed_search}, "
            f"cradius={fixed_cradius}, "
            f"interactive=no, verbose=no)"
        )
        pipeline.log(f"Reidentifying {frame} (Shift: {relative_shift:.2f})")
        subprocess.run(["pyraf", "-c", cmd], env=env, capture_output=True, text=True)

    # Save identify list and let user verify
    with open("co_identify", "w") as f:
        for fname in sorted(pipeline.extracted_comp):
            f.write(fname + os.linesep)

    messagebox.showinfo(
        "Done!",
        "All frames processed against the Master Reference.\n\n"
        "Check the identified frames once before proceeding.\n\n",
    )
    subprocess.run(
        ["pyraf", "-c",
         f"noao; imred; ccdred; specred; identify(images='@co_identify', mode='h')"],
        env=env,
    )
    messagebox.showinfo("Update!", "Identification complete for all comparison frames.")
