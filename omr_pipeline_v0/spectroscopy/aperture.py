import os
import subprocess

import astropy.io.fits as pyfits
from tkinter import messagebox


def parse_ut(ut_str):
    """
    Convert a ``HH:MM:SS`` string to total seconds since midnight.

    Parameters
    ----------
    ut_str : str
        Time string in ``HH:MM:SS`` (or ``HH:MM:SS.s``) format.

    Returns
    -------
    float or None
        Seconds since midnight, or ``None`` if parsing fails.
    """
    try:
        parts = ut_str.split(":")
        h = float(parts[0])
        m = float(parts[1])
        s = float(parts[2])
        return h * 3600 + m * 60 + s
    except Exception:
        return None


def _apall_obj_cmd(selection, readnoise, gain):
    """
    Build the IRAF CL command string for ``apall`` on an object frame.

    Parameters
    ----------
    selection : str
        Path to the object FITS frame.
    readnoise : float or str
        CCD read-noise value forwarded to ``apall``.
    gain : float or str
        CCD gain value forwarded to ``apall``.

    Returns
    -------
    str
        A semicolon-separated IRAF CL command string ready to be passed
        to ``pyraf -c``.
    """
    return (
        "noao; imred; ccdred; specred; "
        f"apall("
        f"input='{selection}', "
        f"output='', "
        f"apertures=1, "
        f"nfind=1, "
        f"interactive=no, "
        f"find=yes, "
        f"recenter=yes, "
        f"resize=yes, "
        f"trace=yes, "
        f"background='median', "
        f"weights='variance', "
        f"clean=yes, "
        f"saturation=60000, "
        f"readnoise={readnoise}, "
        f"gain={gain}, "
        f"reference='', "
        f"mode='h')"
    )


def _apall_comp_cmd(comp_frame, ref_object):
    """
    Build the IRAF CL command string for ``apall`` on a comparison frame.

    Parameters
    ----------
    comp_frame : str
        Path to the comparison FITS frame.
    ref_object : str
        Path to the reference object frame whose aperture is reused.

    Returns
    -------
    str
        A semicolon-separated IRAF CL command string ready to be passed
        to ``pyraf -c``.
    """
    return (
        "noao; imred; ccdred; specred; "
        f"apall("
        f"input='{comp_frame}', "
        f"reference='{ref_object}', "
        f"apertures=1, "
        f"interactive=no, "
        f"find=no, "
        f"recenter=yes, "
        f"resize=no, "
        f"trace=no, "
        f"review=no, "
        f"background='none', "
        f"weights='none', "
        f"clean=no, "
        f"mode='h')"
    )


def extract_objects(pipeline):
    """
    Run IRAF ``apall`` on every object frame in ``pipeline.obj``.

    Apertures are found interactively on the first frame; each subsequent
    frame uses IRAF's recenter/resize logic.  UT times are read from headers
    and returned so ``extract_comparisons`` can use them for time-matching.

    ``apall`` is invoked via ``subprocess`` using ``pyraf -c`` so that the
    call is isolated in its own process and does not require importing
    ``pyraf`` inside this Python session.

    Parameters
    ----------
    pipeline : Pipeline
        The active pipeline instance.

    Returns
    -------
    dict
        ``{filename: ut_seconds}`` for each object frame that has a readable UT.
    """
    env = os.environ.copy()
    env.pop("PYTHONSTARTUP", None)

    obj_times = {}

    for selection in pipeline.obj:
        messagebox.showinfo(
            "Update!",
            f"Running apall on object frame {selection}...\n"
            "Check the terminal window to proceed.",
        )

        # Cache UT time
        try:
            hdr = pyfits.getheader(selection)
            t = parse_ut(hdr.get("UT", "0:0:0"))
            if t is not None:
                obj_times[selection] = t
        except Exception as e:
            pipeline.log(f"Warning: Could not read UT from {selection}: {e}")

        try:
            cmd = _apall_obj_cmd(selection, pipeline.readnoise, pipeline.gain)
            result = subprocess.run(
                ["pyraf", "-c", cmd],
                env=env,
                text=True,
                capture_output=True,
            )
            if result.returncode != 0:
                pipeline.log(
                    f"apall (object) stderr for {selection}:\n{result.stderr.strip()}"
                )

            extracted_name = selection.replace(".fit", ".ms.fits")
            pipeline.log(f"Finished apall (object): {extracted_name}")

        except Exception as e:
            pipeline.log(f"Error in apall for object frame {selection}: {e}")

    messagebox.showinfo("Update!", "Finished extracting all object frames.")
    return obj_times


def extract_comparisons(pipeline, obj_times):
    """
    Run IRAF ``apall`` on every comparison frame, referencing the nearest-UT object.

    ``apall`` is invoked via ``subprocess`` using ``pyraf -c`` so that the
    call is isolated in its own process and does not require importing
    ``pyraf`` inside this Python session.

    Parameters
    ----------
    pipeline : Pipeline
        The active pipeline instance.
    obj_times : dict
        ``{obj_filename: ut_seconds}`` as returned by :func:`extract_objects`.

    Returns
    -------
    list[str]
        Paths to the extracted ``.ms.fits`` comparison spectra.
    """
    env = os.environ.copy()
    env.pop("PYTHONSTARTUP", None)

    if not obj_times:
        pipeline.log(
            "Warning: No object UT times found. "
            "Comparison frames will default to the first object."
        )

    extracted_comp = []

    for comp_frame in pipeline.comp:
        # Time-match to nearest object
        try:
            hdr = pyfits.getheader(comp_frame)
            comp_t = parse_ut(hdr.get("UT", "0:0:0"))
        except Exception:
            comp_t = None

        ref_object = None
        if comp_t is not None and obj_times:
            ref_object = min(obj_times, key=lambda k: abs(obj_times[k] - comp_t))
            diff = abs(obj_times[ref_object] - comp_t)
            pipeline.log(f"Matching Lamp {comp_frame} → Star {ref_object} (Δt={diff:.1f}s)")
        elif pipeline.obj:
            ref_object = pipeline.obj[0]
            pipeline.log(
                f"Warning: Time matching failed for {comp_frame}. Using {ref_object} as default."
            )

        if ref_object is None:
            pipeline.log(f"Skipping {comp_frame}: no reference object available.")
            continue

        pipeline.log(
            f"Running apall on comparison frame {comp_frame} "
            f"(reference: {ref_object})..."
        )
        try:
            cmd = _apall_comp_cmd(comp_frame, ref_object)
            result = subprocess.run(
                ["pyraf", "-c", cmd],
                env=env,
                text=True,
                capture_output=True,
            )
            if result.returncode != 0:
                pipeline.log(
                    f"apall (comp) stderr for {comp_frame}:\n{result.stderr.strip()}"
                )

            extracted_name = comp_frame.replace(".fit", ".ms.fits")
            extracted_comp.append(extracted_name)

        except Exception as e:
            pipeline.log(f"Error in apall for comp frame {comp_frame}: {e}")

    return extracted_comp