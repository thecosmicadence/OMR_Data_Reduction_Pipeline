import tkinter as tk
from tkinter import Label, Button, Frame, messagebox
from tkinter.scrolledtext import ScrolledText

from gui.widgets import show_file_dropdown, edit_file_gui


class PipelineGUI:
    """
    Main Tkinter window for the OMR Spectroscopic Data Reduction Pipeline.

    Owns the toolbar buttons wired to Pipeline callbacks and a scrollable
    log area that captures stdout/stderr output from IRAF and pipeline steps.

    Parameters
    ----------
    root : tk.Tk
        The root Tkinter window.
    pipeline : Pipeline
        The pipeline back-end instance. ``set_gui`` is called on it here.
    """

    def __init__(self, root, pipeline):
        self.root = root
        self.pipeline = pipeline
        self.pipeline.set_gui(self)
        self._closing = False

        self.root.title("OMR Spectroscopic Data Reduction Pipeline")
        self.root.geometry("960x600")

        Label(
            self.root,
            text="OMR Spectroscopic Data Reduction Pipeline",
            font=("Arial", 16, "bold"),
        ).pack(pady=15)

        # ── Toolbar ──────────────────────────────────────────────────────────
        btn_frame = Frame(self.root)
        btn_frame.pack(pady=5)

        buttons = [
            ("Select \nWorking Directory", pipeline.select_and_setup_directory),
            ("Display \nFrame",            pipeline.start_display),
            ("Start \nPreProcessing",      pipeline.start_preprocessing),
            ("Aperture \nExtraction",      pipeline.start_apall),
            ("Line \nIdentify",            pipeline.start_identify),
            ("Reference to \nSpectra",     pipeline.start_refer),
            ("Dispersion \nCorrection",    pipeline.start_dispcor),
            ("Apply\nWave Shift",          pipeline.start_specshift),
            ("Plot Lamp\nSpectra",         pipeline.start_lamp_plot),
            ("Plot \nany Spectra",         pipeline.start_plot),
            ("Exit",                       pipeline.exit_pipeline),
        ]
        for label, cmd in buttons:
            Button(btn_frame, text=label, command=cmd).pack(side="left", padx=10)

        # ── Log area ─────────────────────────────────────────────────────────
        self.output_area = ScrolledText(
            self.root, width=80, height=20, font=("Consolas", 11)
        )
        self.output_area.pack(padx=10, pady=10, fill="both", expand=True)
        self.output_area.config(state="disabled")

    # ── Public helpers ────────────────────────────────────────────────────────

    def log(self, text):
        """Append *text* to the scrollable log area (thread-safe via Tkinter)."""
        if self._closing:
            print(text)
            return

        self.output_area.config(state="normal")

        if isinstance(text, list):
            text = "\n".join(map(str, text))
        else:
            text = str(text)

        self.output_area.insert("end", text + "\n")
        self.output_area.see("end")
        self.output_area.config(state="disabled")

    def show_file_dropdown(self, file_list, title):
        """Thin wrapper so Pipeline code can call ``self.gui.show_file_dropdown(...)``."""
        return show_file_dropdown(self.root, file_list, title)

    def edit_file_gui(self, filename, title="Edit File"):
        """Thin wrapper so Pipeline code can call ``self.gui.edit_file_gui(...)``."""
        edit_file_gui(self.root, filename, title)