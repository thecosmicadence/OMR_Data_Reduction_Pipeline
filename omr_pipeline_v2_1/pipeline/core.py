import os
import sys
import glob
import subprocess

import pyds9
from tkinter import messagebox

from iraf_utils.iraf_init import init_iraf
from pipeline.file_manager import (
    scan_files_by_pi,
    create_masterbias,
    setup_pi_reduction_dirs,
    populate_pipeline_lists,
)
from pipeline.preprocessing import start_preprocessing
from spectroscopy.aperture import extract_objects, extract_comparisons
from spectroscopy.identify import run_identify
from spectroscopy.refer import assign_references
from spectroscopy.dispcor import run_dispcor
from spectroscopy.refer import is_imagetyp


class Pipeline:
    """
    Central pipeline state holder and action dispatcher.

    All mutable state (file lists, paths, instrument parameters) lives here.
    Each GUI button invokes a method on this object, which delegates to the
    appropriate module-level function.
    """

    def __init__(self):
        self.reduction_path = None
        self.original_path = None
        self.bias = []
        self.comp = []
        self.obj = []
        self.dft = []
        self.dark = []
        self.instru = None
        self.readnoise = None
        self.gain = None
        self.extracted_comp = None
        self.extracted_obj = None
        self.identified_comp = None
        self.referenced_obj = None
        self.corrected_files = None
        self.trimmed = None
        self.gui = None

    # ── GUI link ──────────────────────────────────────────────────────────────

    def set_gui(self, gui):
        self.gui = gui
        self.log = gui.log

    # ── IRAF initialisation ───────────────────────────────────────────────────

    def init_iraf(self):
        init_iraf(self.log)

    # ── Directory setup ───────────────────────────────────────────────────────

    def select_and_setup_directory(self):
        from tkinter.filedialog import askdirectory

        original_path = askdirectory(title="Select your raw data directory")
        if not original_path:
            messagebox.showerror("No Directory", "No directory selected. Exiting.")
            return

        self.original_path = original_path
        self.log(f"Scanning raw files in: {original_path}...")

        # ── Scan files into PI hierarchy ───────────────────────────────────────
        hierarchy, flat_pool, all_bias, all_dark = scan_files_by_pi(
            original_path, self.log
        )

        if not hierarchy:
            messagebox.showerror("No Data", "No valid object/comp frames found.")
            return

        # ── Master Bias (before segregation) ──────────────────────────────────
        if all_bias:
            # Remove any stale master_bias.fit before creating a fresh one
            mb_path = os.path.join(original_path, "master_bias.fit")
            if os.path.exists(mb_path):
                try:
                    os.remove(mb_path)
                    all_bias = [f for f in all_bias if os.path.basename(f) != "master_bias.fit"]
                    self.log("Deleted existing master_bias.fit to prevent overwrite errors.")
                except OSError as e:
                    self.log(f"Warning: Could not delete existing master_bias.fit: {e}")
            self.init_iraf()
            create_masterbias(all_bias, original_path, self.gui, self.log)
        else:
            self.log("Warning: No bias frames found — skipping master bias creation.")

        # ── PI selection ───────────────────────────────────────────────────────
        found_pis = sorted(hierarchy.keys())
        selected_pi_list = self.gui.show_file_dropdown(found_pis, "Select PI to Process")
        if not selected_pi_list:
            self.log("No PI selected.")
            return
        selected_pi = selected_pi_list[0]
        self.log(f"Selected PI: {selected_pi}")

        # ── Create PI folder and config sub-folders, copy files ───────────────
        available_configs = setup_pi_reduction_dirs(
            hierarchy, flat_pool, all_bias, all_dark,
            selected_pi, original_path, self.gui, self.log,
        )

        if not available_configs:
            self.log("No configurations found.")
            return

        # ── Configuration selection ────────────────────────────────────────────
        config_choices = sorted(available_configs.keys())
        selected_config_list = self.gui.show_file_dropdown(
            config_choices, "Select Configuration to Reduce"
        )
        if not selected_config_list:
            self.log("No configuration selected.")
            return

        final_path = available_configs[selected_config_list[0]]

        # ── Set working environment ────────────────────────────────────────────
        self.reduction_path = final_path
        os.chdir(self.reduction_path)
        self.log(f"Working directory set to: {self.reduction_path}")

        populate_pipeline_lists(self)

    # ── Pipeline steps ────────────────────────────────────────────────────────

    def start_preprocessing(self):
        start_preprocessing(self)

    def start_apall(self):
        self.init_iraf()
        if not self.comp:
            apall_candidates = glob.glob("*tbd.fit") + glob.glob("*tb.fit")
            self.comp = sorted(
                [f for f in apall_candidates if is_imagetyp(f, 'comp')]
            )
        if not self.obj:
            apall_candidates = glob.glob("*tbdf.fit") + glob.glob("*tbf.fit")
            self.obj = sorted([f for f in apall_candidates if is_imagetyp(f, 'object')])

        obj_times = extract_objects(self)
        extracted_comp = extract_comparisons(self, obj_times)

        self.extracted_obj = [
            f.replace(".fit", ".ms.fits") for f in self.obj
        ]
        self.extracted_comp = extracted_comp
        messagebox.showinfo(
            "Update!",
            "Finished extracting all objects and comparison frames. "
            "Go ahead with line identification!",
        )

    def start_identify(self):
        self.init_iraf()
        run_identify(self)

    def start_refer(self):
        self.init_iraf()
        os.chdir(self.reduction_path)
        assign_references(self)

    def start_dispcor(self):
        self.init_iraf()
        run_dispcor(self)

    # ── Display / plot helpers ────────────────────────────────────────────────

    def start_display(self):
        os.chdir(self.reduction_path)
        fits_files = sorted(glob.glob("*.fit"))
        selections = self.gui.show_file_dropdown(fits_files, "Choose file/files to display")
        if not selections:
            self.log("Display cancelled by user.")
            return

        self.log(f"Launching DS9 on {', '.join(selections)} in separate frames...")
        d = pyds9.DS9()
        for i, selection in enumerate(selections):
            if i > 0:
                d.set("frame new")
            d.set("file " + str(selection))

    def start_plot(self):
        self.init_iraf()
        os.chdir(self.reduction_path)
        fits_files = sorted(glob.glob("*.fit") + glob.glob("*.ms.fits"))
        selection = self.gui.show_file_dropdown(fits_files, "Choose a file to plot in splot")
        if not selection:
            self.log("Plot cancelled by user.")
            return

        chosen = selection[0]
        self.log(f"Launching IRAF splot on {chosen}...")
        script_path = os.path.join(self.reduction_path, "run_splot.py")

        with open(script_path, "w") as f:
            f.write(
                f"from pyraf import iraf\n"
                f"iraf.noao(_doprint=0)\n"
                f"iraf.imred(_doprint=0)\n"
                f"iraf.ccdred(_doprint=0)\n"
                f"iraf.specred(_doprint=0)\n"
                f"iraf.splot(images='{chosen}', band=1, mode='h')\n"
            )

        try:
            subprocess.run([sys.executable, script_path], check=True, env=os.environ.copy())
            messagebox.showinfo(
                "IRAF splot Task",
                "Finish the interactive fitting in xgterm.\n\nClick OK only when you're done.",
            )
        except Exception as e:
            self.log(f"Error launching splot: {e}")
        finally:
            if os.path.exists(script_path):
                os.remove(script_path)

    # ── Exit ──────────────────────────────────────────────────────────────────

    def exit_pipeline(self):
        import tkinter as tk

        msg = (
            "Do you want to exit the pipeline?\n\n"
            "Yes: Exit and close the GUI.\n"
            "Cancel: Stay in the current session."
        )
        choice = messagebox.askyesnocancel("Exit Pipeline", msg)

        if choice is None:
            self.log("Exit cancelled by user.")
            return

        if choice:
            self._closing = True
            print("User chose to exit pipeline. Closing GUI...")
            try:
                if self.gui is not None and hasattr(self.gui, "root"):
                    self.gui._closing = True
                    self.gui.root.destroy()
                    return
            except Exception as e:
                print(f"gui.root.destroy() failed: {e}")

            # Fallback
            if tk._default_root is not None:
                try:
                    tk._default_root.destroy()
                    return
                except Exception as e:
                    print(f"tk._default_root.destroy() failed: {e}")

            sys.exit(0)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup_directory(self):
        import shutil

        os.chdir(self.reduction_path)
        patterns = [
            "*_t.fit", "*_tb.fit", "*_tbd.fit", "*_tbf.fit", "*_tbdf.fit",
            "*master*", "*.ms.fits",
        ]
        for pattern in patterns:
            for fpath in sorted(glob.glob(pattern)):
                try:
                    os.remove(fpath)
                    self.log(f"Deleted: {fpath}")
                except Exception as e:
                    self.log(f"Could not delete {fpath}: {e}")

        other_files = [
            "logfile", "trim.in", "trim.out", "bias.in", "bs.in", "bs.out",
            "dark.in", "darkf.in", "darkf.out", "flat.in", "flatf.in", "flatf.out",
            "disp.in", "disp.out", "final.in", "final.out", "run_response.cl",
            "run_splot.cl", "co_identify",
        ]
        for fname in other_files:
            if os.path.exists(fname):
                try:
                    os.remove(fname)
                    self.log(f"Deleted: {fname}")
                except Exception as e:
                    self.log(f"Could not delete {fname}: {e}")

        if os.path.exists("database"):
            try:
                shutil.rmtree("database")
                self.log("Deleted: database folder")
            except Exception as e:
                self.log(f"Could not delete database folder: {e}")

        self.log("Cleanup completed.")