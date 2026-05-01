import os
import io
import sys
import subprocess

import astropy.io.fits as pyfits
from tkinter import messagebox
from tkinter.simpledialog import askstring


def start_preprocessing(pipeline):
    """
    Run the full pre-processing sequence on the raw frames held by *pipeline*.

    Steps performed (in order):
    1. Display frame summary and ask for trim coordinates.
    2. Trim all frames (``ccdproc``).
    3. Create a master bias (``zerocombine``) and subtract it (``ccdproc``).
    4. Subtract matching dark frames (``imarith``).
    5. Create a master flat (``flatcombine``), normalise it interactively
       (``response``), and flat-field all object frames (``ccdproc``).

    Note
    ----
    The ``ccdhedit`` step (DISPAXIS=1) is now run *before* this function is
    called, on all raw .fit files in the original data directory.

    Parameters
    ----------
    pipeline : Pipeline
        The pipeline instance. Updated file lists are written back to
        ``pipeline.obj``, ``pipeline.comp``, ``pipeline.dft``,
        ``pipeline.bias``, and ``pipeline.dark``.
    """
    from pyraf import iraf

    obj  = list(pipeline.obj)
    comp = list(pipeline.comp)
    dft  = list(pipeline.dft)
    dark = list(pipeline.dark)
    bias = list(pipeline.bias)

    # ── Frame summary ─────────────────────────────────────────────────────────
    msg = (
        f"\n{'='*15} Here are the list of frames {'='*15}\n"
        f"\nBias Frames ({len(bias)}):\n  " + "\n  ".join(bias) +
        f"\n\nObject Frames ({len(obj)}):\n  " + "\n  ".join(obj) +
        f"\n\nComparison Frames ({len(comp)}):\n  " + "\n  ".join(comp) +
        f"\n\nFlat Frames ({len(dft)}):\n  " + "\n  ".join(dft) +
        f"\n\nDark Frames ({len(dark)}):\n  " + "\n  ".join(dark) +
        f"\n\nRead Noise: {pipeline.readnoise}\nGain: {pipeline.gain}"
        f"\nInstrument: {pipeline.instru}\n"
        f"{'='*80}\n"
    )
    pipeline.log(msg)

    # ── Trim section input ────────────────────────────────────────────────────
    messagebox.showinfo(
        "Trimming Section",
        "Enter trimming coordinates as x1,x2,y1,y2 (leave any blank if not used).\n"
        "Example: ',,1,91' → will result in '[,1:91]'",
    )
    trim_input = askstring("Trimming", "Enter x1,x2,y1,y2 (comma-separated):")

    if trim_input is None:
        pipeline.trimmed = ""
    else:
        parts = [p.strip() for p in trim_input.split(",")]
        while len(parts) < 4:
            parts.append("")
        x1, x2, y1, y2 = parts[:4]
        xpart = f"{x1}:{x2}" if (x1 or x2) else ""
        ypart = f"{y1}:{y2}" if (y1 or y2) else ""

        if xpart and ypart:
            pipeline.trimmed = f"[{xpart},{ypart}]"
        elif xpart:
            pipeline.trimmed = f"[{xpart},]"
        elif ypart:
            pipeline.trimmed = f"[,{ypart}]"
        else:
            pipeline.trimmed = ""

    pipeline.log(f"Trimming section set to: {pipeline.trimmed}")

    pipeline.init_iraf()

    # ── Trimming ──────────────────────────────────────────────────────────────
    obj, comp, dft, dark, bias = _run_trim(pipeline, iraf, obj, comp, dft, dark, bias)

    # ── Bias correction ───────────────────────────────────────────────────────
    obj, comp, dft, dark = _run_bias_correction(pipeline, iraf, obj, comp, dft, dark, bias)

    # ── Dark correction ───────────────────────────────────────────────────────
    obj, comp, dft = _run_dark_correction(pipeline, iraf, obj, comp, dft, dark)

    # ── Flat fielding ─────────────────────────────────────────────────────────
    obj = _run_flat_fielding(pipeline, iraf, obj, dft)

    # ── Store updated lists ───────────────────────────────────────────────────
    pipeline.obj  = obj
    pipeline.comp = comp
    pipeline.dft  = dft
    pipeline.bias = bias
    pipeline.dark = dark


# ─────────────────────────────────────────────────────────────────────────────
# Private helpers
# ─────────────────────────────────────────────────────────────────────────────

def _run_trim(pipeline, iraf, obj, comp, dft, dark, bias):
    all_frames = sorted(obj + comp + dft + dark + bias)

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
    iraf.ccdproc.setParam("trim", "yes")
    iraf.ccdproc.setParam("zerocor", "no")
    iraf.ccdproc.setParam("flatcor", "no")
    iraf.ccdproc.setParam("fixfile", "badpix")
    iraf.ccdproc.setParam("biassec", "image")
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
    return obj, comp, dft, dark, bias


def _run_bias_correction(pipeline, iraf, obj, comp, dft, dark, bias):
    pipeline.log("\nPreparing for bias correction...")

    with open("bias.in", "w") as f:
        for fname in sorted(bias):
            f.write(fname + os.linesep)

    with open("bs.in", "w") as f:
        for fname in sorted(obj + comp + dft + dark):
            f.write(fname + os.linesep)

    with open("bs.in") as fi, open("bs.out", "w") as fo:
        for line in fi:
            fo.write(line.strip().replace(".fit", "b.fit") + os.linesep)

    # Show imstat before editing bias list
    buf = io.StringIO()
    iraf.imstat(images="@bias.in", Stdout=buf, mode="h")
    pipeline.log("IRAF imstat output:\n" + buf.getvalue())

    messagebox.showinfo(
        "Edit Bias List",
        "Please edit the bias.in file to remove bad bias frames.\n"
        "After editing, save and close the window to continue.",
    )
    pipeline.gui.edit_file_gui("bias.in", title="Edit bias.in")

    # Master bias
    pipeline.log("\nCreating Master Bias Frame...")
    iraf.zerocombine.setParam("input", "@bias.in")
    iraf.zerocombine.setParam("output", "master_bias.fit")
    iraf.zerocombine.setParam("combine", "median")
    iraf.zerocombine.setParam("reject", "minmax")
    iraf.zerocombine.setParam("ccdtype", "zero")
    iraf.zerocombine.setParam("rdnoise", pipeline.readnoise)
    iraf.zerocombine.setParam("gain", pipeline.gain)
    iraf.zerocombine.setParam("mode", "h")

    try:
        iraf.zerocombine()
        messagebox.showwarning("Update!", "Master Bias created successfully!")
        buf = io.StringIO()
        iraf.imstat(images="master_bias.fit", Stdout=buf, mode="h")
        pipeline.log("IRAF imstat output:\n" + buf.getvalue())
    except Exception as e:
        messagebox.showerror("Error!", f"Error creating master bias: {e}")
        raise

    # Bias subtraction
    pipeline.log("\nSubtracting master bias from other frames...")
    iraf.ccdproc.setParam("images", "@bs.in")
    iraf.ccdproc.setParam("output", "@bs.out")
    iraf.ccdproc.setParam("trim", "no")
    iraf.ccdproc.setParam("zerocor", "yes")
    iraf.ccdproc.setParam("flatcor", "no")
    iraf.ccdproc.setParam("zero", "master_bias.fit")
    iraf.ccdproc.setParam("mode", "h")

    try:
        iraf.ccdproc()
        messagebox.showwarning("Update!", "Bias subtraction completed successfully!")
    except Exception as e:
        messagebox.showerror("Error!", f"Error during bias subtraction: {e}")
        raise

    obj  = [f.replace(".fit", "b.fit") for f in obj]
    comp = [f.replace(".fit", "b.fit") for f in comp]
    dft  = [f.replace(".fit", "b.fit") for f in dft]
    dark = [f.replace(".fit", "b.fit") for f in dark]
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
            f"    interactive='yes',\n"
            f"    threshold='INDEF',\n"
            f"    sample='*',\n"
            f"    function='spline3',\n"
            f"    order=6\n"
            f")\n"
        )

    try:
        subprocess.run([sys.executable, script_path], check=True, env=os.environ.copy())
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