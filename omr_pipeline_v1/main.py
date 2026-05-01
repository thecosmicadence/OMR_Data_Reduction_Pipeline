import tkinter as tk
from pipeline.core import Pipeline
from gui.app import PipelineGUI

if __name__ == "__main__":
    root = tk.Tk()
    pipeline = Pipeline()
    gui = PipelineGUI(root, pipeline)
    root.mainloop()