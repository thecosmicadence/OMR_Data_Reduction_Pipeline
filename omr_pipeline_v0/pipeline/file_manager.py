import os
import glob
import shutil

import astropy.io.fits as pyfits
from collections import defaultdict
from tkinter import messagebox


def group_files_by_config(original_path, log):
    """
    Scan a directory of raw .fit files and group them by (GRATING, CENTWAVE).

    Parameters
    ----------
    original_path : str
        Directory containing the raw .fit observation files.
    log : callable
        GUI log function for status messages.

    Returns
    -------
    dict
        ``{(grating, centwave): {'obj': [...], 'comp': [...], 'flat': [...],
                                  'bias': [...], 'dark': [...], 'exptimes': set()}}``
    """
    groups = defaultdict(
        lambda: {"obj": [], "comp": [], "flat": [], "exptimes": set(), "bias": [], "dark": []}
    )
    all_bias = []
    all_dark = []  # list of (fname, exptime)

    for fname in sorted(glob.glob(os.path.join(original_path, "*.fit"))):
        try:
            with pyfits.open(fname) as hdul:
                hdr = hdul[0].header
                imagetyp = hdr.get("IMAGETYP", "").lower()
                grating = str(hdr.get("GRATING", ""))
                centwave = str(hdr.get("CENTWAVE", ""))
                exptime = int(hdr.get("EXPOSURE", 0))
        except Exception as e:
            log(f"Error reading {fname}: {e}")
            continue

        key = (grating, centwave)
        if imagetyp == "object":
            groups[key]["obj"].append(fname)
            groups[key]["exptimes"].add(exptime)
        elif imagetyp == "comp":
            groups[key]["comp"].append(fname)
            groups[key]["exptimes"].add(exptime)
        elif imagetyp == "flat":
            groups[key]["flat"].append(fname)
            groups[key]["exptimes"].add(exptime)
        elif imagetyp == "zero":
            all_bias.append(fname)
        elif imagetyp == "dark":
            all_dark.append((fname, exptime))

    # Propagate bias & matching dark frames into every group
    for key in groups:
        groups[key]["bias"] = list(all_bias)
        groups[key]["dark"] = [
            fname
            for fname, dark_exptime in all_dark
            if dark_exptime in groups[key]["exptimes"]
        ]

    return dict(groups)


def setup_reduction_dirs(groups, original_path, gui, sets_dict, log):
    """
    Create one reduction directory per (GRATING, CENTWAVE) group and copy files.

    Parameters
    ----------
    groups : dict
        Output of :func:`group_files_by_config`.
    original_path : str
        Path to the raw data directory (used to derive sibling directories).
    gui : PipelineGUI
        GUI reference (for messagebox dialogs).
    sets_dict : dict
        Mutable dict that maps ``(grating, centwave)`` → ``reduction_dir``.
        Updated in-place.
    log : callable
        GUI log function.
    """
    parent_dir = os.path.dirname(original_path)
    base_name = os.path.basename(original_path.rstrip("/"))

    for (grating, centwave), group in groups.items():
        dir_name = f"{base_name}_gr{grating}_cw{centwave}"
        red_dir = os.path.join(parent_dir, dir_name)
        sets_dict[(grating, centwave)] = red_dir

        if os.path.exists(red_dir):
            answer = messagebox.askyesno(
                "Directory Exists",
                f"Reduction directory '{red_dir}' already exists for "
                f"GRATING={grating}, CENTWAVE={centwave}.\n"
                "Do you want to start over (delete and recreate)?\n"
                "Click 'No' to continue with the existing directory.",
            )
            if answer:
                try:
                    shutil.rmtree(red_dir)
                    os.makedirs(red_dir)
                    log(f"Deleted and recreated directory: {red_dir}")
                    _copy_group_files(group, red_dir, log)
                except Exception as e:
                    log(f"Error handling directory {red_dir}: {e}")
            else:
                log(f"Continuing with existing directory: {red_dir}")
        else:
            os.makedirs(red_dir)
            _copy_group_files(group, red_dir, log)
            log(f"Created directory {red_dir} for GRATING={grating}, CENTWAVE={centwave}")


def _copy_group_files(group, dest_dir, log):
    """Copy all files in a group dict to *dest_dir*."""
    for ftype in ("obj", "comp", "flat", "bias", "dark"):
        for fname in group[ftype]:
            try:
                shutil.copy(fname, dest_dir)
            except Exception as e:
                log(f"Error copying {fname} to {dest_dir}: {e}")


def populate_pipeline_lists(pipeline):
    """
    Scan the chosen reduction directory and fill pipeline file lists.

    Reads ``IMAGETYP``, ``RDNOISE``, ``CCDGAIN``, and ``INSTRUME`` from headers.

    Parameters
    ----------
    pipeline : Pipeline
        The pipeline instance whose lists will be populated in-place.
    """
    for fname in sorted(glob.glob(os.path.join(pipeline.reduction_path, "*.fit"))):
        try:
            with pyfits.open(fname) as hdul:
                hdr = hdul[0].header
                imagetyp = hdr.get("IMAGETYP", "").lower()
                base = os.path.basename(fname)

                if imagetyp == "object":
                    pipeline.obj.append(base)
                    pipeline.readnoise = pipeline.readnoise or hdr.get("RDNOISE")
                    pipeline.gain = pipeline.gain or hdr.get("CCDGAIN")
                    pipeline.instru = pipeline.instru or hdr.get("INSTRUME")
                elif imagetyp == "comp":
                    pipeline.comp.append(base)
                elif imagetyp == "flat":
                    pipeline.dft.append(base)
                elif imagetyp == "zero":
                    pipeline.bias.append(base)
                elif imagetyp == "dark":
                    pipeline.dark.append(base)

        except Exception as e:
            pipeline.log(f"Error reading {fname}: {e}")