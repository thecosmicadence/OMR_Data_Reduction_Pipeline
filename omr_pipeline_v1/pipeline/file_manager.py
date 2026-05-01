import os
import io
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


def create_masterbias(all_bias, original_path, gui, log):
    """
    Create ``master_bias.fit`` from raw bias frames *in* ``original_path``.

    This must be called before :func:`setup_reduction_dirs` so that the
    resulting master bias can be distributed into each reduction directory.

    Parameters
    ----------
    all_bias : list[str]
        Full paths to all raw bias (IMAGETYP=zero) frames.
    original_path : str
        Directory that contains the raw frames; ``master_bias.fit`` will be
        written here.
    gui : PipelineGUI
        GUI reference used for the file-editor dialog.
    log : callable
        GUI log function.
    """
    from pyraf import iraf

    bias_in_path = os.path.join(original_path, "bias.in")
    master_bias_path = os.path.join(original_path, "master_bias.fit")

    # Write initial bias list
    with open(bias_in_path, "w") as f:
        for fname in sorted(all_bias):
            f.write(fname + os.linesep)

    # Show statistics so user can judge which frames to drop
    buf = io.StringIO()
    iraf.imstat(images="@" + bias_in_path, Stdout=buf, mode="h")
    log("IRAF imstat output (raw bias frames):\n" + buf.getvalue())

    messagebox.showinfo(
        "Edit Bias List",
        "Please edit the bias.in file to remove bad bias frames.\n"
        "After editing, save and close the window to continue.",
    )
    gui.edit_file_gui(bias_in_path, title="Edit bias.in")

    log("\nCreating Master Bias Frame...")
    iraf.zerocombine.setParam("input", "@" + bias_in_path)
    iraf.zerocombine.setParam("output", master_bias_path)
    iraf.zerocombine.setParam("combine", "median")
    iraf.zerocombine.setParam("reject", "minmax")
    iraf.zerocombine.setParam("ccdtype", "zero")
    iraf.zerocombine.setParam("mode", "h")

    try:
        iraf.zerocombine()
        messagebox.showwarning("Update!", "Master Bias created successfully!")
        buf = io.StringIO()
        iraf.imstat(images=master_bias_path, Stdout=buf, mode="h")
        log("IRAF imstat output (master bias):\n" + buf.getvalue())
    except Exception as e:
        messagebox.showerror("Error!", f"Error creating master bias: {e}")
        raise


def setup_reduction_dirs(groups, original_path, gui, sets_dict, log):
    """
    Create one reduction directory per (GRATING, CENTWAVE) group and copy files.

    Parameters
    ----------
    groups : dict
        Output of :func:`group_files_by_config`.
    original_path : str
        Path to the raw data directory (used to derive sibling directories and
        to locate ``master_bias.fit``).
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
                    _copy_group_files(group, red_dir, original_path, log)
                except Exception as e:
                    log(f"Error handling directory {red_dir}: {e}")
            else:
                log(f"Continuing with existing directory: {red_dir}")
        else:
            os.makedirs(red_dir)
            _copy_group_files(group, red_dir, original_path, log)
            log(f"Created directory {red_dir} for GRATING={grating}, CENTWAVE={centwave}")


def _copy_group_files(group, dest_dir, original_path, log):
    """
    Copy science/comp/flat/dark frames to *dest_dir*, then copy
    ``master_bias.fit`` from *original_path* into *dest_dir*.

    Raw bias frames are **not** copied — the pre-made master bias is used instead.
    """
    for ftype in ("obj", "comp", "flat", "dark"):
        for fname in group[ftype]:
            try:
                shutil.copy(fname, dest_dir)
            except Exception as e:
                log(f"Error copying {fname} to {dest_dir}: {e}")

    # Copy the master bias that was created in original_path
    master_bias_src = os.path.join(original_path, "master_bias.fit")
    if os.path.exists(master_bias_src):
        try:
            shutil.copy(master_bias_src, dest_dir)
            log(f"Copied master_bias.fit → {dest_dir}")
        except Exception as e:
            log(f"Error copying master_bias.fit to {dest_dir}: {e}")
    else:
        log(f"Warning: master_bias.fit not found in {original_path}, skipping copy.")


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