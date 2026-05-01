
import astropy.io.fits as pyfits
from tkinter import messagebox
import os
import sys
import subprocess

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


def extract_objects(pipeline):
    """
    Run IRAF ``apall`` on every object frame in ``pipeline.obj`` using subprocess.

    Apertures are found interactively on the first frame; each subsequent
    frame uses IRAF's recenter/resize logic.  UT times are read from headers
    and returned so ``extract_comparisons`` can use them for time-matching.

    Parameters
    ----------
    pipeline : Pipeline
        The active pipeline instance.

    Returns
    -------
    dict
        ``{filename: ut_seconds}`` for each object frame that has a readable UT.
    """
    obj_times = {}
    messagebox.showinfo("Update!", "Running apall on object frames... Press OK to continue.")
    for selection in pipeline.obj:

        # Cache UT time
        try:
            hdr = pyfits.getheader(selection)
            # Assuming parse_ut is imported or defined in your namespace
            t = parse_ut(hdr.get("UT", "0:0:0"))
            if t is not None:
                obj_times[selection] = t
        except Exception as e:
            pipeline.log(f"Warning: Could not read UT from {selection}: {e}")

        script_path = os.path.join(pipeline.reduction_path, "run_apall_task.py")

        with open(script_path, "w") as f:
            f.write(
                "import os\n"
                "from pyraf import iraf\n"
                "iraf.noao(_doprint=0); iraf.twodspec(_doprint=0); iraf.apextract(_doprint=0)\n"
                "with open('apall_ans.txt', 'w') as f_ans:\n"
                "    f_ans.write('1\\n')\n"
                f"iraf.apall(\n"
                f"    input='{selection}',\n"
                f"    output='',\n"
                f"    apertures=1,\n"
                f"    nfind=1,\n"
                f"    interactive='no',\n"
                f"    find='yes',\n"
                f"    recenter='yes',\n"
                f"    resize='yes',\n"
                f"    edit='no',\n"
                f"    trace='yes',\n"
                f"    fittrace='yes',\n"
                f"    extract='yes',\n"
                f"    extras='yes',\n"
                f"    review='no',\n"
                f"    background='median',\n"
                f"    weights='variance',\n"
                f"    clean='yes',\n"
                f"    saturation=60000,\n"
                f"    readnoise={pipeline.readnoise},\n"
                f"    gain={pipeline.gain},\n"
                f"    reference='',\n"
                f"    mode='h',\n"
                f"    Stdin='apall_ans.txt'\n"
                f")\n"
                "if os.path.exists('apall_ans.txt'):\n"
                "    os.remove('apall_ans.txt')\n"
            )

        try:
            subprocess.run([sys.executable, script_path], check=True, env=os.environ.copy())
            extracted_name = selection.replace(".fit", ".ms.fits")
            pipeline.log(f"Finished apall (object): {extracted_name}")
        except subprocess.CalledProcessError as e:
            pipeline.log(f"Error in apall for object frame {selection}: {e}")
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)

    messagebox.showinfo("Update!", "Finished extracting all object frames.")
    return obj_times


def extract_comparisons(pipeline, obj_times):
    """
    Run IRAF ``apall`` on every comparison frame, referencing the nearest-UT object.

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
    from pyraf import iraf

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
            iraf.apall.setParam("input", comp_frame)
            iraf.apall.setParam("reference", ref_object)
            iraf.apfind.setParam("apertures", 1)
            iraf.apall.setParam("apertures", 1)
            iraf.apall.setParam("interactive", "no")
            iraf.apall.setParam("find", "no")
            iraf.apall.setParam("recenter", "yes")
            iraf.apall.setParam("resize", "no")
            iraf.apall.setParam("trace", "no")
            iraf.apall.setParam("review", "no")
            iraf.apall.setParam("background", "none")
            iraf.apall.setParam("weights", "none")
            iraf.apall.setParam("clean", "no")
            iraf.apall.setParam("mode", "h")
            iraf.apall()

            extracted_name = comp_frame.replace(".fit", ".ms.fits")
            extracted_comp.append(extracted_name)

        except Exception as e:
            pipeline.log(f"Error in apall for comp frame {comp_frame}: {e}")

    return extracted_comp