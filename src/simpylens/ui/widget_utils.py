import tkinter as tk
from tkinter import ttk


def create_scrolled_treeview(parent, columns, *, show="headings", height=10, selectmode="browse"):
    """Builds a Treeview with a vertical scrollbar using a consistent layout."""
    frame = ttk.Frame(parent)
    scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    tree = ttk.Treeview(
        frame,
        columns=columns,
        show=show,
        selectmode=selectmode,
        yscrollcommand=scrollbar.set,
        height=height,
    )
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.config(command=tree.yview)
    return frame, tree, scrollbar
