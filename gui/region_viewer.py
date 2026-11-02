# Pop-up window that shows the sample/reference image with the air and signal regions

import tkinter as tk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

REGIONS = (('Air', 'cyan'), ('Signal', 'red'))


def open_region_viewer(root, ratio, air_vars, signal_vars):
    win = tk.Toplevel(root)
    win.title("Selected regions - sample / reference")
    win.geometry("760x840")

    top = tk.Frame(win)
    top.pack(fill=tk.X, padx=8, pady=4)
    message = tk.Label(top, anchor='w', justify='left', font=("Helvetica", 9))
    message.pack(side=tk.LEFT, fill=tk.X, expand=True)

    fig = Figure(figsize=(7, 7))
    ax = fig.add_subplot(111)
    finite = ratio[np.isfinite(ratio)]
    lo, hi = np.percentile(finite, [1, 99]) if finite.size else (0, 1)
    if lo == hi:
        hi = lo + 1e-6
    ax.imshow(ratio, cmap='gray', vmin=lo, vmax=hi, interpolation='nearest')
    ax.set_xlabel("column")
    ax.set_ylabel("row")

    canvas = FigureCanvasTkAgg(fig, master=win)
    toolbar = NavigationToolbar2Tk(canvas, win)
    toolbar.update()
    canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    patches = []
    h, w = ratio.shape

    def refresh():
        for p in patches:
            p.remove()
        patches.clear()
        for t in list(ax.texts):
            t.remove()
        notes = [f"Image: {h} rows x {w} columns."]
        for (name, colour), vars_ in zip(REGIONS, (air_vars, signal_vars)):
            try:
                r0, r1, c0, c1 = (int(v.get()) for v in vars_)
            except ValueError:
                notes.append(f"{name}: boxes are empty or not whole numbers.")
                continue
            if not (0 <= r0 < r1 <= h and 0 <= c0 < c1 <= w):
                notes.append(f"{name} ({r0}, {r1}, {c0}, {c1}) does not fit inside the image.")
            patches.append(ax.add_patch(Rectangle((c0, r0), c1 - c0, r1 - r0, fill=False,
                                                  edgecolor=colour, linewidth=2)))
            ax.text(c0, r0 - 4, name, color=colour, fontsize=10, fontweight='bold')
        message.config(text="  ".join(notes) + "   Cyan = air, red = signal.")
        canvas.draw_idle()

    tk.Button(top, text="Refresh", command=refresh).pack(side=tk.RIGHT)
    fig.tight_layout()
    refresh()
