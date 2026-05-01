import glob

from tkinter import messagebox


def run_dispcor(pipeline):
    """
    Interactively apply dispersion correction to spectra using IRAF ``dispcor``.

    The user is presented with a multi-select dropdown to pick one spectrum
    at a time.  After each run the user is asked whether to continue.
    Corrected file names are appended to ``pipeline.corrected_files``.

    Parameters
    ----------
    pipeline : Pipeline
        The active pipeline instance.
    """
    from pyraf import iraf

    iraf.noao()
    iraf.imred()
    iraf.ccdred()
    iraf.specred()

    if not pipeline.referenced_obj:
        pipeline.referenced_obj = sorted(glob.glob("*obj*tbdf.ms.fits"))
    if not pipeline.identified_comp:
        pipeline.identified_comp = sorted(
            glob.glob("*co*tb.ms.fits") + glob.glob("*co*tbd.ms.fits")
        )

    all_spectra = sorted(pipeline.referenced_obj + (pipeline.identified_comp or []))
    corrected_files = list(pipeline.corrected_files or [])

    while True:
        selection = pipeline.gui.show_file_dropdown(
            all_spectra, "Choose a spectrum for dispersion correction"
        )
        if not selection:
            break

        chosen = selection[0]
        output_name = chosen.replace(".ms.fits", "w.ms.fits")

        pipeline.log(f"Running dispersion correction: {chosen} → {output_name}")
        messagebox.showinfo("Update!", "Running dispcor... Check terminal for progress.")

        try:
            iraf.dispcor.setParam("input", chosen)
            iraf.dispcor.setParam("output", output_name)
            iraf.dispcor.setParam("verbose", "no")
            iraf.dispcor()

            corrected_files.append(output_name)
            pipeline.log(f"Dispersion correction completed: {output_name}")

        except Exception as e:
            pipeline.log(f"Error running dispcor on {chosen}: {e}")

        if not messagebox.askyesno("Continue?", "Run dispcor on another file?"):
            break

    pipeline.corrected_files = corrected_files