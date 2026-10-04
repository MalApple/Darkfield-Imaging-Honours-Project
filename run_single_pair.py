
# For exactly ONE reference image (filter only) + ONE sample image (filter +
# specimen) -- i.e. the single-exposure case, no stepping scan. Uses
# Single_Evolving / Single_Devolving from evolvedevolve.py.

import os
import numpy as np
import matplotlib.pyplot as plt
import tifffile as tiff

from EvolveDevolve_OptimalReg_Opt import Single_Evolving, Single_Devolving, compute_regularisation_parameter

# ----------------------------- CONFIG -----------------------------
REFERENCE_IMAGE = "reference.tif"   # filter only, no specimen
SAMPLE_IMAGE = "sample.tif"         # filter + specimen
SAVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "single_pair_output")

PIXEL_SIZE = 6.5             # Pixel size of the detector [microns]
GAMMA = 2335                 # Ratio of delta to beta for your specimen's material
PROP = 0.7 * 10**6           # Propagation distance, specimen to detector [microns]
WAVELENGTH = 4.9594 * 10**-5   # X-ray wavelength [microns]

RUN_DEVOLVING = True          # also compute the devolving perspective, as a cross-check

# --- Gamma scan (optional, run this BEFORE trusting GAMMA above) ---
# If you don't know gamma (delta/beta) for your specimen, set RUN_GAMMA_SCAN = True.
# This computes the TIE-based transmission image across several candidate gamma
# values and displays them side-by-side. The correct gamma gives clean, smooth
# edges at material boundaries; an incorrect gamma shows dark/bright halo
# fringing right at the edges. Once you've picked a value by eye, set GAMMA
# above to it and set RUN_GAMMA_SCAN = False to run the full pipeline.
RUN_GAMMA_SCAN = False
GAMMA_SCAN_VALUES = np.geomspace(100, 10000, 8)   # candidate gamma values to compare, edit as needed
# --------------------------------------------------------------------

# Region used to estimate the regularisation parameter via SNR.
# Format: (row_start, row_end, col_start, col_end).
# SIGNAL_REGION: a patch INSIDE your specimen.
# AIR_REGION: a patch with NO specimen (background/air), same image.
# You must look at your ratio image (sample/reference) and pick real coordinates --
# set SHOW_PLOT = True once to check them visually before trusting the result.
SIGNAL_REGION = (0, 100, 0, 100)
AIR_REGION = (0, 100, 1400, 1600)
SHOW_PLOT = True
# --------------------------------------------------------------------


def run_gamma_scan(sam, ref, gamma_values, save_dir):
    """
    Compute the TIE-based transmission image for each candidate gamma and
    display them side-by-side so you can pick the one with the cleanest
    (least fringed) material edges.
    """
    os.makedirs(save_dir, exist_ok=True)

    n = len(gamma_values)
    cols = min(4, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
    axes = np.atleast_1d(axes).flatten()

    for ax, g in zip(axes, gamma_values):
        transmission, phase = TIE_Speckle(sam, ref, PIXEL_SIZE, g, PROP, WAVELENGTH)
        ax.imshow(transmission, cmap="gray")
        ax.set_title(f"gamma = {g:.3g}")
        ax.axis("off")

    for ax in axes[len(gamma_values):]:
        ax.axis("off")

    fig.suptitle("Gamma scan -- pick the gamma with the cleanest edges (no dark/bright halo)")
    fig.tight_layout()
    out_path = os.path.join(save_dir, "gamma_scan.png")
    fig.savefig(out_path, dpi=150)
    plt.show()

    print(f"\nSaved gamma scan comparison to: {out_path}")
    print("Inspect the images (zoom in on a specimen edge in each). Once you've picked the")
    print("best gamma, set GAMMA in CONFIG to that value and set RUN_GAMMA_SCAN = False, then re-run.")


def main():
    os.makedirs(SAVE_DIR, exist_ok=True)

    ref = tiff.imread(REFERENCE_IMAGE).astype(np.float32)
    sam = tiff.imread(SAMPLE_IMAGE).astype(np.float32)

    print(f"reference: {REFERENCE_IMAGE}  shape={ref.shape}")
    print(f"sample:    {SAMPLE_IMAGE}  shape={sam.shape}")

    if ref.shape != sam.shape:
        raise ValueError(f"Reference and sample images have different shapes: {ref.shape} vs {sam.shape}")

    if RUN_GAMMA_SCAN:
        print(f"Running gamma scan over: {list(GAMMA_SCAN_VALUES)}")
        run_gamma_scan(sam, ref, GAMMA_SCAN_VALUES, SAVE_DIR)
        return

    # Quick look at the ratio image to help you judge/adjust SIGNAL_REGION and AIR_REGION
    if SHOW_PLOT:
        plt.imshow(sam / ref, cmap="gray", vmin=0.6, vmax=1)
        plt.title("sample / reference -- use this to pick signal/air regions")
        plt.colorbar()
        plt.show()

    print(f"Estimating regularisation parameter "
          f"(signal_region={SIGNAL_REGION}, air_region={AIR_REGION})...")
    regkr2 = compute_regularisation_parameter(
        sam, ref, PIXEL_SIZE, SIGNAL_REGION, AIR_REGION, show_plot=SHOW_PLOT
    )

    print("Running single-exposure evolving Fokker-Planck...")
    D_ev, pos_ev, neg_ev, transmission_ev = Single_Evolving(
        sam, ref, PIXEL_SIZE, GAMMA, PROP, WAVELENGTH, SAVE_DIR, regkr2
    )
    tiff.imwrite(os.path.join(SAVE_DIR, "df_evolving.tiff"), D_ev.astype(np.float32))

    if RUN_DEVOLVING:
        print("Running single-exposure devolving Fokker-Planck...")
        D_dev, pos_dev, neg_dev, transmission_dev = Single_Devolving(
            sam, ref, PIXEL_SIZE, GAMMA, PROP, WAVELENGTH, SAVE_DIR, regkr2
        )
        tiff.imwrite(os.path.join(SAVE_DIR, "df_devolving.tiff"), D_dev.astype(np.float32))

    print(f"\nDone. Results in: {os.path.abspath(SAVE_DIR)}")


if __name__ == "__main__":
    main()