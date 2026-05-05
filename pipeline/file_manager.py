import os
import io
import glob
import shutil
import numpy as np
import astropy.io.fits as pyfits
from collections import defaultdict
from tkinter import messagebox
# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _clean_name(name):
    """Convert a PI name to a filesystem-safe string."""
    return "".join([c if c.isalnum() else "_" for c in str(name)]).strip()
# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
def scan_files_by_pi(original_path, log):
    """
    Scan a directory of raw .fit files and build a two-level hierarchy:
        hierarchy[pi_key][(grating, centwave)] = {
            'obj':      [...],
            'comp':     [...],
            'exptimes': set(),
        }
    Flat frames are pooled by configuration (ignoring PI):
        flat_pool[(grating, centwave)] = {'files': [...], 'exptimes': set()}
    Bias and dark frames are pooled globally.
    Parameters
    ----------
    original_path : str
        Directory containing the raw .fit observation files.
    log : callable
        GUI log function for status messages.
    Returns
    -------
    hierarchy : defaultdict
    flat_pool : defaultdict
    all_bias : list[str]
    all_dark : list[tuple[str, int]]   – (filename, exptime)
    """
    hierarchy = defaultdict(
        lambda: defaultdict(lambda: {"obj": [], "comp": [], "exptimes": set()})
    )
    flat_pool = defaultdict(lambda: {"files": [], "exptimes": set()})
    all_bias = []
    all_dark = []  # list of (fname, exptime)
    for fname in sorted(glob.glob(os.path.join(original_path, "*.fit"))):
        try:
            with pyfits.open(fname) as hdul:
                hdr = hdul[0].header
                imagetyp = hdr.get("IMAGETYP", "").lower()
                grating  = str(hdr.get("GRATING",  "UNKNOWN"))
                centwave = str(hdr.get("CENTWAVE", "UNKNOWN"))
                exptime  = int(float(hdr.get("EXPOSURE", 0)))
                pi_raw = hdr.get("PI", "UNKNOWN")
                if not pi_raw or str(pi_raw).strip() == "":
                    pi_raw = "UNKNOWN"
                pi_key = _clean_name(pi_raw)
        except Exception as e:
            log(f"Error reading {fname}: {e}")
            continue
        if imagetyp == "zero":
            all_bias.append(fname)
        elif imagetyp == "dark":
            all_dark.append((fname, exptime))
        elif imagetyp == "flat":
            flat_pool[(grating, centwave)]["files"].append(fname)
            flat_pool[(grating, centwave)]["exptimes"].add(exptime)
        elif imagetyp in ("object", "comp"):
            group = hierarchy[pi_key][(grating, centwave)]
            if imagetyp == "object":
                group["obj"].append(fname)
            else:
                group["comp"].append(fname)
            group["exptimes"].add(exptime)
    return hierarchy, flat_pool, all_bias, all_dark
# ---------------------------------------------------------------------------
# Master Bias
# ---------------------------------------------------------------------------
def auto_filter_biases(bias_files, log, sigma_clip=3.0):
    """
    Automatically reject bad bias frames using sigma-clipping on per-frame
    median and standard deviation.
    The rejection threshold is expressed in units of the MAD-based robust
    sigma of the ensemble distribution, making it insensitive to a small
    number of pathologically bad frames.
    Parameters
    ----------
    bias_files : list[str]
        Full paths to all candidate bias frames.
    log : callable
        GUI log function for status/rejection messages.
    sigma_clip : float, optional
        Number of robust sigmas beyond which a frame is rejected (default 3.0).
    Returns
    -------
    good_frames : list[str]
        Bias frames that passed both the median and noise checks.
    """
    if not bias_files:
        return []
    frame_medians = []
    frame_stds    = []
    log("Auto-filtering bias frames (sigma-clipping)...")
    for f in bias_files:
        data = pyfits.getdata(f, 0).astype(float)
        frame_medians.append(np.median(data))
        frame_stds.append(np.std(data))
    frame_medians = np.array(frame_medians)
    frame_stds    = np.array(frame_stds)
    # Robust ensemble statistics (MAD-based sigma)
    group_med_of_meds = np.median(frame_medians)
    mad_meds          = np.median(np.abs(frame_medians - group_med_of_meds))
    robust_sigma_meds = 1.4826 * mad_meds
    group_med_of_stds = np.median(frame_stds)
    mad_stds          = np.median(np.abs(frame_stds - group_med_of_stds))
    robust_sigma_stds = 1.4826 * mad_stds
    # Guard against degenerate case where all values are identical
    if robust_sigma_meds == 0:
        robust_sigma_meds = 1e-5
    if robust_sigma_stds == 0:
        robust_sigma_stds = 1e-5
    log(
        f"  Ensemble median of medians = {group_med_of_meds:.2f} "
        f"(±{sigma_clip * robust_sigma_meds:.2f})"
    )
    log(
        f"  Ensemble median of stds    = {group_med_of_stds:.2f} "
        f"(±{sigma_clip * robust_sigma_stds:.2f})"
    )
    good_frames = []
    for i, f in enumerate(bias_files):
        med_dev = abs(frame_medians[i] - group_med_of_meds)
        std_dev = abs(frame_stds[i]    - group_med_of_stds)
        if (med_dev < sigma_clip * robust_sigma_meds and
                std_dev < sigma_clip * robust_sigma_stds):
            good_frames.append(f)
        else:
            log(
                f"  [REJECTED] {os.path.basename(f)}  "
                f"median={frame_medians[i]:.2f}  std={frame_stds[i]:.2f}"
            )
    log(
        f"Bias filtering done: {len(good_frames)}/{len(bias_files)} frames kept."
    )
    return good_frames
def create_masterbias(all_bias, original_path, gui, log):
    """
    Automatically filter bias frames via sigma-clipping, then combine the
    survivors into ``master_bias.fit`` using IRAF ``zerocombine``.
    No manual user interaction is required: bad frames are rejected
    statistically and the result is logged for the record.
    Parameters
    ----------
    all_bias : list[str]
        Full paths to all raw bias (IMAGETYP=zero) frames.
    original_path : str
        Directory where ``master_bias.fit`` will be written.
    gui : PipelineGUI
        Unused here (kept for API compatibility).
    log : callable
        GUI log function.
    """
    from pyraf import iraf
    bias_in_path     = os.path.join(original_path, "bias.in")
    master_bias_path = os.path.join(original_path, "master_bias.fit")
    # ── Automatic sigma-clipping rejection ────────────────────────────────────
    good_bias = auto_filter_biases(all_bias, log, sigma_clip=3.0)
    if not good_bias:
        messagebox.showerror(
            "No Good Bias Frames",
            "All bias frames were rejected by sigma-clipping. "
            "Cannot create master bias.",
        )
        raise RuntimeError("No good bias frames survived sigma-clipping.")
    # Write the filtered list for zerocombine
    with open(bias_in_path, "w") as f:
        for fname in sorted(good_bias):
            f.write(fname + os.linesep)
    log(f"\nCreating Master Bias Frame from {len(good_bias)} good frames...")
    iraf.zerocombine.setParam("input",   "@" + bias_in_path)
    iraf.zerocombine.setParam("output",  master_bias_path)
    iraf.zerocombine.setParam("combine", "median")
    iraf.zerocombine.setParam("reject",  "minmax")
    iraf.zerocombine.setParam("ccdtype", "zero")
    iraf.zerocombine.setParam("mode",    "h")
    try:
        iraf.zerocombine()
        log("Master Bias created successfully!")
        buf = io.StringIO()
        iraf.imstat(images=master_bias_path, Stdout=buf, mode="h")
        log("IRAF imstat output (master bias):\n" + buf.getvalue())
    except Exception as e:
        messagebox.showerror("Error!", f"Error creating master bias: {e}")
        raise
# ---------------------------------------------------------------------------
# Directory setup
# ---------------------------------------------------------------------------

def setup_pi_reduction_dirs(hierarchy, flat_pool, all_bias, all_dark,
                            selected_pi, original_path, gui, log):
    """
    Create the PI folder and one sub-folder per (grating, centwave) configuration
    for the selected PI.  Files are copied into each sub-folder.
    Returns
    -------
    available_configs : dict
        Maps human-readable label → absolute path of sub-folder.
        Example: ``{"Grating: 7 | CentWave: 5765": "/data/raw_SHARMA/gr7_cw5765"}``
    """
    parent_dir = os.path.dirname(original_path)
    base_name  = os.path.basename(original_path.rstrip("/"))
    pi_folder_path = os.path.join(parent_dir, f"{base_name}_{selected_pi}")
    # ── PI-level folder handling ──────────────────────────────────────────────
    # Just check if it exists. If not, create it. No more pop-ups here.
    if not os.path.exists(pi_folder_path):
        os.makedirs(pi_folder_path)
        log(f"Created PI folder: {pi_folder_path}")
    else:
        log(f"PI folder already exists: {pi_folder_path}. Proceeding to sub-folders.")
    # ── Sub-folder per configuration ──────────────────────────────────────────
    available_configs = {}
    pi_data = hierarchy[selected_pi]
    for (grating, centwave), group_data in pi_data.items():
        sub_folder_name = f"gr{grating}_cw{centwave}"
        full_sub_path   = os.path.join(pi_folder_path, sub_folder_name)
        config_label    = f"Grating: {grating} | CentWave: {centwave}"
        available_configs[config_label] = full_sub_path
        do_copy = False
        if os.path.exists(full_sub_path):
            # This is where the user will be asked about the specific sub-folder
            overwrite_sub = messagebox.askyesno(
                "Configuration Exists",
                f"Folder '{sub_folder_name}' already exists inside {selected_pi}.\n\n"
                "Do you want to overwrite it?",
            )
            if overwrite_sub:
                try:
                    shutil.rmtree(full_sub_path)
                    os.makedirs(full_sub_path)
                    do_copy = True
                    log(f"Overwriting sub-folder: {sub_folder_name}")
                except Exception as e:
                    log(f"Error clearing sub-folder {sub_folder_name}: {e}")
            else:
                log(f"Keeping existing sub-folder: {sub_folder_name}")
                do_copy = False
        else:
            os.makedirs(full_sub_path)
            do_copy = True
            log(f"Created sub-folder: {sub_folder_name}")
        if do_copy:
            # Assumes _copy_config_files is defined elsewhere in your script
            _copy_config_files(
                group_data, flat_pool, all_bias, all_dark,
                grating, centwave, full_sub_path, original_path, log,
            )
    return available_configs
def _copy_config_files(group_data, flat_pool, all_bias, all_dark,
                       grating, centwave, dest_dir, original_path, log):
    """
    Copy science, comp, flat, bias, and matching dark frames into *dest_dir*.
    Also copies ``master_bias.fit`` from *original_path* if it exists.
    """
    files_to_copy = list(group_data["obj"]) + list(group_data["comp"])
    # Flats for this configuration
    flat_data = flat_pool.get((grating, centwave), {"files": [], "exptimes": set()})
    files_to_copy.extend(flat_data["files"])
    # All bias frames
    files_to_copy.extend(all_bias)
    # Darks whose exposure time matches science/comp/flat exptimes
    needed_exptimes = group_data["exptimes"].union(flat_data.get("exptimes", set()))
    for d_fname, d_exp in all_dark:
        if d_exp in needed_exptimes:
            files_to_copy.append(d_fname)
    for f in files_to_copy:
        try:
            shutil.copy(f, dest_dir)
        except Exception as e:
            log(f"Error copying {f}: {e}")
    # Copy pre-built master bias if available
    master_bias_src = os.path.join(original_path, "master_bias.fit")
    if os.path.exists(master_bias_src):
        try:
            shutil.copy(master_bias_src, dest_dir)
            log(f"Copied master_bias.fit → {dest_dir}")
        except Exception as e:
            log(f"Error copying master_bias.fit to {dest_dir}: {e}")
    else:
        log(f"Warning: master_bias.fit not found in {original_path}, skipping copy.")
# ---------------------------------------------------------------------------
# Pipeline list population
# ---------------------------------------------------------------------------
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
                    pipeline.gain      = pipeline.gain      or hdr.get("CCDGAIN")
                    pipeline.instru    = pipeline.instru    or hdr.get("INSTRUME")
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