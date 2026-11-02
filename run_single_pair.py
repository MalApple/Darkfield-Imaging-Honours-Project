# Simple single-exposure darkfield: ONE reference image + ONE sample image.
# The GUI (gui/xrayGUI.py) calls run() and gamma_scan();

import os

import matplotlib
matplotlib.use("Agg")          # no windows: safe to run from the GUI's background thread
import matplotlib.pyplot as plt
import numpy as np
import tifffile as tiff

from EvolveDevolve_OptimalReg_Opt import (
    Single_Evolving,
    Single_Devolving,
    compute_regularisation_parameter,
    TIE_Speckle,
)

# Fixed choices (the old CONFIG values you weren't changing from the GUI)
FRAME = 0                  # frame of the stack to use
CROP_EDGE = 4              # pixels removed from every edge of both images
FLOOR_FRACTION = 0.01      # dark pixels raised to this fraction of the reference median
DISPLAY_MARGIN = 20        # border pixels ignored when choosing display contrast
COLORMAP = "viridis"
RUN_DEVOLVING = True


def _load(path):
    return tiff.imread(path, key=FRAME).astype(np.float32)


def _prepare(reference_image, sample_image, air_region):
    """Load, crop, floor and brightness-match. Returns (ref, sam)."""
    ref = _load(reference_image)
    sam = _load(sample_image)
    if ref.shape != sam.shape:
        raise ValueError(f"Reference and sample images have different shapes: {ref.shape} vs {sam.shape}")

    c = CROP_EDGE
    if c > 0:
        ref = ref[c:-c, c:-c]
        sam = sam[c:-c, c:-c]
    print(f"Image shape after cropping: {ref.shape}")

    floor = FLOOR_FRACTION * float(np.median(ref))
    ref = np.maximum(ref, floor)
    sam = np.maximum(sam, floor)

    a0, a1, a2, a3 = _check_region(air_region, ref.shape, "Air region")
    scale = float(ref[a0:a1, a2:a3].mean() / sam[a0:a1, a2:a3].mean())
    sam = np.maximum(sam * scale, floor)
    print(f"Sample scaled by {scale:.4g} to match the reference in the air patch")
    return ref, sam


def _check_region(region, shape, name):
    r0, r1, c0, c1 = region
    h, w = shape
    if not (0 <= r0 < r1 <= h and 0 <= c0 < c1 <= w):
        raise ValueError(f"{name} {region} does not fit the cropped image ({h} rows x {w} columns).")
    return r0, r1, c0, c1


def _limits(img, low=1, high=99):
    m = DISPLAY_MARGIN
    if min(img.shape) > 4 * m:
        img = img[m:-m, m:-m]
    finite = img[np.isfinite(img)]
    if finite.size == 0:
        return 0.0, 1.0
    lo, hi = np.percentile(finite, [low, high])
    if lo == hi:
        hi = lo + 1e-6
    return float(lo), float(hi)


def _save_panels(panels, title, prefix, save_dir):
    """Save each panel as a PNG plus one overview figure."""
    n = len(panels)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5), squeeze=False)
    for ax, (label, img) in zip(axes[0], panels):
        lo, hi = _limits(img)
        im = ax.imshow(img, cmap=COLORMAP, vmin=lo, vmax=hi)
        ax.set_title(label, fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        name = label.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_") \
                    .replace(",", "").replace(":", "")
        plt.imsave(os.path.join(save_dir, f"{prefix}_{name}.png"), img, cmap=COLORMAP, vmin=lo, vmax=hi)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(os.path.join(save_dir, f"{prefix}_overview.png"), dpi=150)
    plt.close(fig)


def run(reference_image, sample_image, save_dir, pixel_size, gamma, prop, wavelength,
        signal_region, air_region):
    """Single-exposure evolving (and devolving) Fokker-Planck darkfield."""
    save_dir = os.path.abspath(save_dir)
    os.makedirs(save_dir, exist_ok=True)

    ref, sam = _prepare(reference_image, sample_image, air_region)
    s0, s1, s2, s3 = _check_region(signal_region, ref.shape, "Signal region")
    a0, a1, a2, a3 = air_region

    ratio = sam / ref
    air_std = float(np.std(ratio[a0:a1, a2:a3]))
    snr = float(np.mean(ratio[s0:s1, s2:s3])) / air_std if air_std > 0 else float("inf")
    print(f"SNR = {snr:.4g}")
    if not np.isfinite(snr) or snr <= 0:
        raise ValueError("SNR is not usable (air patch is flat, empty or has NaN). "
                         "Move the air region onto background that still shows speckle noise.")

    trans, _ = TIE_Speckle(sam, ref, pixel_size, gamma, prop, wavelength)
    n_bad = int((~(trans > 0)).sum())
    if n_bad:
        raise ValueError(f"{n_bad} transmission pixels are <= 0, so the darkfield would be all NaN. "
                         f"Check the raw images for dead/zero areas.")

    regkr2 = compute_regularisation_parameter(sam, ref, pixel_size, signal_region, air_region,
                                              show_plot=False)
    print(f"regkr2 = {regkr2:.4g}, gamma = {gamma}")

    # The solvers os.chdir() into save_dir; restore the working directory afterwards.
    cwd = os.getcwd()
    try:
        print("Running evolving Fokker-Planck...")
        D, pos, neg, trans = Single_Evolving(sam, ref, pixel_size, gamma, prop, wavelength,
                                             save_dir, regkr2)
        tiff.imwrite(os.path.join(save_dir, "df_evolving.tiff"), D.astype(np.float32))
        _save_panels([
            ("Transmission", trans),
            ("Dark-field, evolving (signed)", D),
            ("Dark-field, evolving (positive part)", pos),
            ("Dark-field, evolving (negative part, magnitude)", -1 * neg),
        ], "Single-exposure EVOLVING Fokker-Planck", "evolving", save_dir)

        if RUN_DEVOLVING:
            print("Running devolving Fokker-Planck...")
            D, pos, neg, trans = Single_Devolving(sam, ref, pixel_size, gamma, prop, wavelength,
                                                  save_dir, regkr2)
            tiff.imwrite(os.path.join(save_dir, "df_devolving.tiff"), D.astype(np.float32))
            _save_panels([
                ("Transmission", trans),
                ("Dark-field, devolving (signed)", D),
                ("Dark-field, devolving (positive part)", pos),
                ("Dark-field, devolving (negative part, magnitude)", -1 * neg),
            ], "Single-exposure DEVOLVING Fokker-Planck", "devolving", save_dir)
    finally:
        os.chdir(cwd)

    print(f"Done. Results in: {save_dir}")


def gamma_scan(reference_image, sample_image, save_dir, pixel_size, prop, wavelength,
               air_region, gamma_values):
    """Transmission image for each candidate gamma, side by side. Pick the one with the cleanest edges."""
    save_dir = os.path.abspath(save_dir)
    os.makedirs(save_dir, exist_ok=True)

    ref, sam = _prepare(reference_image, sample_image, air_region)

    n = len(gamma_values)
    cols = min(4, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows), squeeze=False)
    axes = axes.ravel()

    for ax, g in zip(axes, gamma_values):
        trans, _ = TIE_Speckle(sam, ref, pixel_size, float(g), prop, wavelength)
        print(f"gamma {g:.3g}: NaN = {int(np.isnan(trans).sum())}, "
              f"min = {np.nanmin(trans):.4g}, max = {np.nanmax(trans):.4g}")
        lo, hi = _limits(trans)
        ax.imshow(trans, cmap="gray", vmin=lo, vmax=hi)
        ax.set_title(f"gamma = {g:.3g}")
        ax.axis("off")
    for ax in axes[n:]:
        ax.axis("off")

    fig.suptitle("Gamma scan - pick the gamma with the cleanest edges (no dark/bright halo)")
    fig.tight_layout()
    out_path = os.path.join(save_dir, "gamma_scan.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved gamma scan to: {out_path}")