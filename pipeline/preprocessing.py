import os
import io
import sys
import subprocess
import numpy as np
import astropy.io.fits as pyfits
from scipy.ndimage import gaussian_filter1d
from tkinter import messagebox
def get_auto_trimsec(flat_filepath, buffer_pixels=5):
    """
    Automatically determine the IRAF TRIMSEC string from a flat-field frame.
    The spatial profile (median-collapsed along the dispersion axis) is
    smoothed and its first derivative is computed. The steepest upward slope
    marks the bottom slit edge; the steepest downward slope marks the top.
    A *buffer_pixels* safety margin is applied so that the trimmed region
    sits comfortably inside the illuminated slit.
    Parameters
    ----------
    flat_filepath : str
        Path to any flat-field FITS file.
    buffer_pixels : int
        Number of pixels to retreat from each detected edge (default 5).
    Returns
    -------
    str or None
        IRAF-style trimsec string, e.g. ``"[1:2048, 12:87]"``.
        Returns ``None`` on read error, or a full-frame fallback string
        if edge detection fails.
    """
    try:
        data = pyfits.getdata(flat_filepath, 0)
    except Exception as e:
        print(f"Error reading {flat_filepath}: {e}")
        return None
    # Strip any degenerate leading axes (e.g. FITS shape (1, Y, X) → (Y, X))
    data = np.squeeze(data)
    if data.ndim != 2:
        print(f"Error: {flat_filepath} has unexpected shape {data.shape} after squeeze.")
        return None
    max_y, max_x = data.shape
    # Collapse dispersion axis → 1-D spatial profile
    spatial_profile = np.median(data, axis=1)
    # Mild Gaussian smoothing to suppress hot-pixel / noise spikes
    smoothed_profile = gaussian_filter1d(spatial_profile, sigma=2)
    # First derivative
    profile_gradient = np.gradient(smoothed_profile)
    # Bottom edge: steepest upward slope; top edge: steepest downward slope
    y_start_idx = int(np.argmax(profile_gradient))
    y_end_idx   = int(np.argmin(profile_gradient))
    # Convert to 1-based inclusive IRAF indices + safety buffer
    iraf_y_start = (y_start_idx + buffer_pixels) + 1
    iraf_y_end   = (y_end_idx   - buffer_pixels) + 1
    # Sanity checks
    if iraf_y_start >= iraf_y_end:
        print(
            f"Warning: Edge detection failed for {flat_filepath}. "
            "Start >= End — falling back to full frame."
        )
        return f"[1:{max_x},1:{max_y}]"
    iraf_y_start = max(1, iraf_y_start)
    iraf_y_end   = min(max_y, iraf_y_end)
    return f"[1:{max_x},{iraf_y_start}:{iraf_y_end}]"
def start_preprocessing(pipeline):
    """
    Run the full pre-processing sequence on the raw frames held by *pipeline*.
    Steps performed (in order):
    1. Display frame summary and ask for trim coordinates.
    2. Update DISPAXIS keyword in all FITS headers.
    3. Trim all frames (``ccdproc``).
    4. Subtract matching dark frames (``imarith``).
    5. Create a master flat (``flatcombine``), normalise it interactively
       (``response``), and flat-field all object frames (``ccdproc``).
    Note: master bias subtraction (``zerocor") is performed at directory-setup
    time via ``create_masterbias()``. The ``master_bias.fit`` file is already
    present in the reduction directory when this function runs.
    Parameters
    ----------
    pipeline : Pipeline
        The pipeline instance. Updated file lists are written back to
        ``pipeline.obj``, ``pipeline.comp``, ``pipeline.dft``, and
        ``pipeline.dark``.
    """
    from pyraf import iraf
    obj  = list(pipeline.obj)
    comp = list(pipeline.comp)
    dft  = list(pipeline.dft)
    dark = list(pipeline.dark)
    # ── Frame summary ─────────────────────────────────────────────────────────
    msg = (
        f"\n{'='*15} Here are the list of frames {'='*15}\n"
        f"\nObject Frames ({len(obj)}):\n  " + "\n  ".join(obj) +
        f"\nMaster Bias: {'master_bias.fit' if os.path.exists('master_bias.fit') else 'Not found'}" +
        f"\n\nComparison Frames ({len(comp)}):\n  " + "\n  ".join(comp) +
        f"\n\nFlat Frames ({len(dft)}):\n  " + "\n  ".join(dft) +
        f"\n\nDark Frames ({len(dark)}):\n  " + "\n  ".join(dark) +
        f"\n\nRead Noise: {pipeline.readnoise}\nGain: {pipeline.gain}"
        f"\nInstrument: {pipeline.instru}\n"
        f"{'='*80}\n"
    )
    pipeline.log(msg)
    # ── Auto-detect trim section from the first flat frame ───────────────────
    if dft:
        reference_flat = dft[0]
        pipeline.log(f"Auto-detecting trim section from flat: {reference_flat} …")
        auto_trimsec = get_auto_trimsec(reference_flat)
        if auto_trimsec:
            pipeline.trimmed = auto_trimsec
            pipeline.log(f"Auto trim section detected: {pipeline.trimmed}")
        else:
            pipeline.log(
                "Warning: Auto trim detection returned None — "
                "falling back to no trimming."
            )
            pipeline.trimmed = ""
    else:
        pipeline.log(
            "Warning: No flat frames available for auto trim detection — "
            "skipping trimming."
        )
        pipeline.trimmed = ""
    pipeline.log(f"Trimming section set to: {pipeline.trimmed}")
    pipeline.init_iraf()
    # ── DISPAXIS update ───────────────────────────────────────────────────────
    pipeline.log("\nUpdating DISPAXIS to '1' for all FITS files...")
    iraf.cd(pipeline.reduction_path)
    iraf.ccdhedit.setParam("images", "*.fit")
    iraf.ccdhedit.setParam("parameter", "DISPAXIS")
    iraf.ccdhedit.setParam("value", "1")
    iraf.ccdhedit.setParam("type", "string")
    iraf.ccdhedit.setParam("mode", "h")
    iraf.ccdhedit()
    messagebox.showwarning("Update!", "Dispersion axis update successful.")
    
    # ── Trimming ──────────────────────────────────────────────────────────────
    obj, comp, dft, dark = _run_trim(pipeline, iraf, obj, comp, dft, dark)
    # ── Bias subtraction (master_bias_t.fit already present) ──────────────────
    obj, comp, dft, dark = _run_bias_subtract(pipeline, iraf, obj, comp, dft, dark)
    # ── Dark correction ───────────────────────────────────────────────────────
    obj, comp, dft = _run_dark_correction(pipeline, iraf, obj, comp, dft, dark)
    # ── Flat fielding ─────────────────────────────────────────────────────────
    obj = _run_flat_fielding(pipeline, iraf, obj, dft)
    # ── Store updated lists ───────────────────────────────────────────────────
    pipeline.obj  = obj
    pipeline.comp = comp
    pipeline.dft  = dft
    pipeline.dark = dark
# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────
def _run_trim(pipeline, iraf, obj, comp, dft, dark):
    all_frames = sorted(obj + comp + dft + dark)
    # Include master_bias.fit in the trim run so it matches the science trimsec
    master_bias = "master_bias.fit"
    has_master_bias = os.path.exists(master_bias)
    if has_master_bias:
        all_frames = sorted(all_frames + [master_bias])
        pipeline.log("master_bias.fit found — will be trimmed alongside science frames.")
    else:
        pipeline.log("Warning: master_bias.fit not found in reduction directory. Skipping bias trim.")
    with open("trim.in", "w") as f:
        for fname in all_frames:
            f.write(fname + os.linesep)
    pipeline.log(f"Created trim.in with {len(all_frames)} frames for trimming.")
    with open("trim.in") as fi, open("trim.out", "w") as fo:
        for line in fi:
            fo.write(line.strip().replace(".fit", "_t.fit") + os.linesep)
    pipeline.log("Created trim.out.")
    iraf.ccdproc.setParam("images", "@trim.in")
    iraf.ccdproc.setParam("output", "@trim.out")
    iraf.ccdproc.setParam("ccdtype", "")
    iraf.ccdproc.setParam("trim", "yes")
    iraf.ccdproc.setParam("fixpix", "no")
    iraf.ccdproc.setParam("overscan", "no")
    iraf.ccdproc.setParam("zerocor", "no")
    iraf.ccdproc.setParam("darkcor", "no")
    iraf.ccdproc.setParam("flatcor", "no")
    iraf.ccdproc.setParam("illumcor", "no")
    iraf.ccdproc.setParam("fringecor", "no")
    iraf.ccdproc.setParam("readcor", "no")
    iraf.ccdproc.setParam("scancor", "no")
    iraf.ccdproc.setParam("mode", "h")
    iraf.ccdproc.setParam("trimsec", pipeline.trimmed)
    try:
        iraf.ccdproc()
        messagebox.showwarning("Update!", "Files trimmed successfully!")
    except Exception as e:
        messagebox.showerror("Error!", f"Error trimming files: {e}")
        raise
    obj  = [f.replace(".fit", "_t.fit") for f in obj]
    comp = [f.replace(".fit", "_t.fit") for f in comp]
    dft  = [f.replace(".fit", "_t.fit") for f in dft]
    dark = [f.replace(".fit", "_t.fit") for f in dark]
    # master_bias_t.fit is now on disk; no return value needed
    return obj, comp, dft, dark
def _run_bias_subtract(pipeline, iraf, obj, comp, dft, dark):
    """
    Subtract ``master_bias_t.fit`` from all trimmed frames using ``ccdproc``.
    This is a lightweight operation — no ``zerocombine``, no user dialog.
    The master bias was already created (and trimmed) at directory-setup time.
    Output files replace the ``_t.fit`` suffix with ``_tb.fit``.
    """
    master_bias_t = "master_bias_t.fit"
    if not os.path.exists(master_bias_t):
        pipeline.log(
            "Warning: master_bias_t.fit not found. Skipping bias subtraction."
        )
        return obj, comp, dft, dark
    pipeline.log("\nSubtracting master bias from trimmed frames...")
    with open("bs.in", "w") as f:
        for fname in sorted(obj + comp + dft + dark):
            f.write(fname + os.linesep)
    with open("bs.in") as fi, open("bs.out", "w") as fo:
        for line in fi:
            fo.write(line.strip().replace("_t.fit", "_tb.fit") + os.linesep)
    iraf.ccdproc.setParam("images", "@bs.in")
    iraf.ccdproc.setParam("output", "@bs.out")
    iraf.ccdproc.setParam("ccdtype", "")
    iraf.ccdproc.setParam("trim", "no")
    iraf.ccdproc.setParam("fixpix", "no")
    iraf.ccdproc.setParam("overscan", "no")
    iraf.ccdproc.setParam("zerocor", "yes")
    iraf.ccdproc.setParam("darkcor", "no")
    iraf.ccdproc.setParam("flatcor", "no")
    iraf.ccdproc.setParam("illumcor", "no")
    iraf.ccdproc.setParam("fringecor", "no")
    iraf.ccdproc.setParam("readcor", "no")
    iraf.ccdproc.setParam("scancor", "no")
    iraf.ccdproc.setParam("zero", master_bias_t)
    iraf.ccdproc.setParam("mode", "h")
    try:
        iraf.ccdproc()
        messagebox.showwarning("Update!", "Bias subtraction completed successfully!")
    except Exception as e:
        messagebox.showerror("Error!", f"Error during bias subtraction: {e}")
        raise
    obj  = [f.replace("_t.fit", "_tb.fit") for f in obj]
    comp = [f.replace("_t.fit", "_tb.fit") for f in comp]
    dft  = [f.replace("_t.fit", "_tb.fit") for f in dft]
    dark = [f.replace("_t.fit", "_tb.fit") for f in dark]
    return obj, comp, dft, dark
def _run_dark_correction(pipeline, iraf, obj, comp, dft, dark):
    pipeline.log("\nPreparing for dark correction...")
    not_found = []
    dark_correction_map = {}
    try:
        with open("dark.in", "w") as dark_in, open("darkf.in", "w") as darkf_in:
            for dark_file in sorted(dark):
                with pyfits.open(dark_file) as dh:
                    dark_exptime = int(dh[0].header["EXPOSURE"])
                found_match = False
                for target_file in sorted(obj + comp + dft):
                    with pyfits.open(target_file) as th:
                        if int(th[0].header["EXPOSURE"]) == dark_exptime:
                            dark_in.write(dark_file + os.linesep)
                            darkf_in.write(target_file + os.linesep)
                            pipeline.log(f"Matched {dark_file} → {target_file}")
                            found_match = True
                if not found_match:
                    not_found.append(dark_file)
        with open("darkf.in") as fi, open("darkf.out", "w") as fo:
            for line in fi:
                fo.write(line.strip().replace(".fit", "d.fit") + os.linesep)
        pipeline.log("\nSubtracting dark frames...")
        iraf.imarith.setParam("op", "-")
        iraf.imarith.setParam("operand1", "@darkf.in")
        iraf.imarith.setParam("operand2", "@dark.in")
        iraf.imarith.setParam("result", "@darkf.out")
        iraf.imarith.setParam("mode", "h")
        iraf.imarith()
        messagebox.showwarning("Update!", "Dark frame subtraction successful!")
        buf = io.StringIO()
        iraf.imstat(images="@darkf.out", Stdout=buf, mode="h")
        pipeline.log("IRAF imstat output:\n" + buf.getvalue())
        with open("darkf.in") as fi, open("darkf.out") as fo:
            for old, new in zip(fi, fo):
                dark_correction_map[old.strip()] = new.strip()
        obj  = [dark_correction_map.get(f, f) for f in obj]
        comp = [dark_correction_map.get(f, f) for f in comp]
        dft  = [dark_correction_map.get(f, f) for f in dft]
        if not_found:
            messagebox.showinfo(
                "Warning!", f"No matching dark frame found for {len(not_found)} file(s)."
            )
    except Exception as e:
        messagebox.showerror("Error!", f"Error during dark subtraction: {e}")
        raise
    return obj, comp, dft
def _run_flat_fielding(pipeline, iraf, obj, dft):
    pipeline.log("\nCreating Master Flat...")
    with open("flat.in", "w") as f:
        for fname in sorted(dft):
            f.write(fname + os.linesep)
    buf = io.StringIO()
    iraf.imstat(images="@flat.in", Stdout=buf, mode="h")
    pipeline.log("IRAF imstat output:\n" + buf.getvalue())
    messagebox.showinfo(
        "Edit Flat List",
        "Please edit the flat.in file to remove bad flat frames.\n"
        "After editing, save and close the window to continue.",
    )
    pipeline.gui.edit_file_gui("flat.in", title="Edit flat.in")
    messagebox.showwarning("Update!", "Updated flat files for flatcombine successfully!")
    master_flat  = "master_flat.fit"
    nmaster_flat = "nmaster_flat.fit"
    iraf.flatcombine.setParam("input", "@flat.in")
    iraf.flatcombine.setParam("output", master_flat)
    iraf.flatcombine.setParam("combine", "median")
    iraf.flatcombine.setParam("reject", "avsigclip")
    iraf.flatcombine.setParam("ccdtype", "flat")
    iraf.flatcombine.setParam("rdnoise", pipeline.readnoise)
    iraf.flatcombine.setParam("gain", pipeline.gain)
    iraf.flatcombine.setParam("mode", "h")
    iraf.flatcombine()
    pipeline.log("Master flat created.")
    buf = io.StringIO()
    iraf.imstat(images=master_flat, Stdout=buf, mode="h")
    pipeline.log("IRAF imstat output:\n" + buf.getvalue())
    # Interactive response fitting in subprocess (needs its own graphics context)
    pipeline.log("\nLaunching interactive response fitting in a separate window...")
    script_path = os.path.join(pipeline.reduction_path, "run_response_task.py")
    with open(script_path, "w") as f:
        f.write(
            "from pyraf import iraf\n"
            "iraf.noao(_doprint=0); iraf.imred(_doprint=0)\n"
            "iraf.ccdred(_doprint=0); iraf.specred(_doprint=0)\n"
            f"iraf.response(\n"
            f"    calibration='{master_flat}',\n"
            f"    normalization='{master_flat}',\n"
            f"    response='{nmaster_flat}',\n"
            f"    interactive='YES',\n"
            f"    threshold='INDEF',\n"
            f"    sample='*',\n"
            f"    function='spline3',\n"
            f"    mode='h',\n"
            f"    order=6,\n"
            f"    Stdin=['yes']\n"
            f")\n"
        )
    # Use a custom environment so PyRAF doesn't try to write uparm to read-only /app/.iraf
    sub_env = os.environ.copy()
    sub_env["HOME"] = pipeline.reduction_path
    
    try:
        subprocess.run([sys.executable, script_path], check=True, env=sub_env)
        pipeline.log("Interactive fitting complete.")
    except subprocess.CalledProcessError as e:
        messagebox.showerror("Error!", f"Interactive task failed or was cancelled: {e}")
        raise
    finally:
        if os.path.exists(script_path):
            os.remove(script_path)
    # Flat-field all object frames
    pipeline.log("\nFlat-fielding object frames...")
    for objfile in obj:
        outname = objfile.replace(".fit", "f.fit")
        iraf.ccdproc.setParam("images", objfile)
        iraf.ccdproc.setParam("output", outname)
        iraf.ccdproc.setParam("trim", "no")
        iraf.ccdproc.setParam("zerocor", "no")
        iraf.ccdproc.setParam("flatcor", "yes")
        iraf.ccdproc.setParam("flat", nmaster_flat)
        iraf.ccdproc.setParam("mode", "h")
        iraf.ccdproc()
    pipeline.log("Flat-fielding complete.")
    messagebox.showwarning("Update!", "Flat-fielded all star frames successfully!")
    buf = io.StringIO()
    iraf.imstat(images="*f.fit", Stdout=buf, mode="h")
    pipeline.log("IRAF imstat output:\n" + buf.getvalue())
    obj = [f.replace(".fit", "f.fit") for f in obj]
    return obj