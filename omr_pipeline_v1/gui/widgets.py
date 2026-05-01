import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText
from utils.signal_redirect import TextRedirector


# Re-export so importers can use `from gui.widgets import TextRedirector`
__all__ = ["TextRedirector", "show_file_dropdown", "edit_file_gui"]


def show_file_dropdown(parent, file_list, title):
    """
    Display a modal Listbox popup that lets the user select one or more files.

    Parameters
    ----------
    parent : tk.Tk or tk.Toplevel
        Owner window (used for grab/transient behaviour).
    file_list : list[str]
        Items to display.
    title : str
        Window title and label text.

    Returns
    -------
    list[str]
        Selected items, or an empty list if cancelled.
    """
    if not file_list:
        messagebox.showerror("No Files", "No files available for selection.")
        return []

    win = tk.Toplevel(parent)
    win.title(title)

    tk.Label(win, text=title).pack(padx=10, pady=5)

    frame = tk.Frame(win)
    frame.pack(padx=10, pady=5)

    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    listbox = tk.Listbox(
        frame,
        selectmode=tk.MULTIPLE,
        yscrollcommand=scrollbar.set,
        width=60,
        height=15,
    )
    for item in file_list:
        listbox.insert(tk.END, item)
    listbox.pack(side=tk.LEFT, fill=tk.BOTH)

    scrollbar.config(command=listbox.yview)

    selection = {"value": []}

    def submit():
        indices = listbox.curselection()
        selection["value"] = [file_list[i] for i in indices]
        win.destroy()

    tk.Button(win, text="OK", command=submit).pack(pady=5)

    win.transient(parent)
    win.grab_set()
    win.wait_window()

    return selection["value"]


def edit_file_gui(parent, filename, title="Edit File"):
    """
    Open a modal editor popup for a plain-text file.

    The user can edit the file content and save it when done.

    Parameters
    ----------
    parent : tk.Tk or tk.Toplevel
        Owner window.
    filename : str
        Absolute path to the file to edit.
    title : str, optional
        Window title (default ``"Edit File"``).
    """
    edit_win = tk.Toplevel(parent)
    edit_win.title(title)
    edit_win.geometry("600x400")

    edit_win.rowconfigure(0, weight=1)
    edit_win.columnconfigure(0, weight=1)

    try:
        with open(filename, "r") as f:
            content = f.read()
    except Exception as e:
        messagebox.showerror("Error", f"Could not open {filename}: {e}")
        return

    text_area = ScrolledText(edit_win, font=("Consolas", 11))
    text_area.grid(row=0, column=0, sticky="nsew", padx=10, pady=(10, 5))
    text_area.insert("1.0", content)

    def save_and_close():
        try:
            with open(filename, "w") as f:
                f.write(text_area.get("1.0", "end-1c"))
        except Exception as e:
            messagebox.showerror("Error", f"Could not save {filename}: {e}")
        edit_win.destroy()

    tk.Button(edit_win, text="Save and Close", command=save_and_close).grid(
        row=1, column=0, pady=(0, 10)
    )

    edit_win.transient(parent)
    edit_win.grab_set()
    parent.wait_window(edit_win)