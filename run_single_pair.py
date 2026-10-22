# For exactly ONE reference image (filter only) + ONE sample image (filter +
# specimen) -- i.e. the single-exposure case, no stepping scan. Uses
# Single_Evolving / Single_Devolving from evolvedevolve.py.

import os
import numpy as np
import matplotlib.pyplot as plt
import tifffile as tiff

from EvolveDevolve_OptimalReg_Opt import Single_Evolving, Single_Devolving, compute_regularisation_parameter, TIE_Speckle

# ----------------------------- CONFIG -----------------------------
REFERENCE_IMAGE = "Darkfield-Imaging-Honours-Project/reference_images/no_mouse_200_mesh_count.btf"
SAMPLE_IMAGE = "Darkfield-Imaging-Honours-Project/sample_images/mouse_200_mesh_count.btf"
SAVE_DIR = "Darkfield-Imaging-Honours-Project/single_pair_output"

PIXEL_SIZE = 194             # Pixel size of the detector [microns]
GAMMA = 720                 # Ratio of delta to beta for your specimen's material
PROP = 1.55 * 10**6           # Propagation distance, specimen to detector [microns]
WAVELENGTH = 4.9594 * 10**-5   # X-ray wavelength [microns]

RUN_DEVOLVING = True          # also compute the devolving perspective, as a cross-check

# Image preparation (the .btf files are uncorrected stacks, so these help)
FRAME = 0                     # which frame of the stack to use (same for both images)
NORMALISE_SAMPLE = True       # rescale sample so its mean brightness matches the reference
PRINT_STATS = True            # print min/max/NaN diagnostics while running
COLORMAP = "viridis"          # colour map for the result images ("gray" = greyscale, but bright areas turn pure white)
CROP_EDGE = 4                 # pixels cut off every edge of BOTH images before processing (removes dead rows/columns).
                              # Region coordinates below then refer to the cropped image. Set 0 to disable.
DISPLAY_EDGE_MARGIN = 20      # pixels ignored at each border when choosing the display contrast (display only)
AVERAGE_FRAMES = False        # True = average ALL frames of each stack instead of using FRAME. Only safe if the
                              # frames are repeat exposures at the SAME speckle position (see notes)
INTENSITY_FLOOR_FRACTION = 0.01   # pixels below this fraction of the reference median are raised to it (stops log of <=0 -> NaN)

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
SIGNAL_REGION = (600, 650, 600, 650)
AIR_REGION = (400, 600, 0, 80)
SHOW_PLOT = True
# --------------------------------------------------------------------

# Convert the relative paths above to absolute paths right now, BEFORE anything
# changes the working directory. Single_Evolving / Single_Devolving call
# os.chdir(SAVE_DIR) internally, which would otherwise make a relative SAVE_DIR
# point to the wrong place for every file written afterwards.
REFERENCE_IMAGE = os.path.abspath(REFERENCE_IMAGE)
SAMPLE_IMAGE = os.path.abspath(SAMPLE_IMAGE)
SAVE_DIR = os.path.abspath(SAVE_DIR)
# --------------------------------------------------------------------


def percentile_limits(img, low=1, high=99):
    # Work out the display range from the interior only. The FFT-based derivatives are unreliable in the
    # outermost pixels, and a few extreme edge values would otherwise squash the contrast of everything else.
    m = DISPLAY_EDGE_MARGIN
    if m > 0 and min(img.shape) > 4 * m:
        img = img[m:-m, m:-m]
    finite = img[np.isfinite(img)]
    if finite.size == 0:
        return 0, 1
    lo, hi = np.percentile(finite, [low, high])
    if lo == hi:
        hi = lo + 1e-6
    return lo, hi


def report(name, arr):
    """Print whether an array is usable: share of finite pixels, spread and display range."""
    finite = np.isfinite(arr)
    if not finite.any():
        print(f"  [{name}] ALL VALUES ARE NaN/inf -> this panel will be blank")
        return
    vals = arr[finite]
    p1, p99 = np.percentile(vals, [1, 99])
    msg = (f"  [{name}] finite={finite.mean() * 100:.1f}%  std={vals.std():.3e}  "
           f"1-99%=[{p1:.3e}, {p99:.3e}]")
    if finite.mean() < 1:
        msg += "  <-- contains NaN/inf"
    if vals.std() == 0 or p1 == p99:
        msg += "  <-- constant image, nothing to display"
    print(msg)


#Save every result as a viewable PNG and show them together in one labelled figure.
def save_and_show_results(panels, figure_title, file_prefix, save_dir):

    print(f"Panel check for {file_prefix}:")
    n = len(panels)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 5))
    axes = np.atleast_1d(axes)

    for ax, (label, img) in zip(axes, panels):
        report(label, img)
        lo, hi = percentile_limits(img)
        im = ax.imshow(img, cmap=COLORMAP, vmin=lo, vmax=hi)
        ax.set_title(label, fontsize=10)
        ax.set_xticks([])   # keep the black frame so a bright image doesn't blend into a white page
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

        safe_name = label.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
        plt.imsave(os.path.join(save_dir, f"{file_prefix}_{safe_name}.png"), img,
                   cmap=COLORMAP, vmin=lo, vmax=hi)

    fig.suptitle(figure_title)
    fig.tight_layout()
    overview_path = os.path.join(save_dir, f"{file_prefix}_overview.png")
    fig.savefig(overview_path, dpi=150)
    plt.show()
    print(f"Saved viewable images ({file_prefix}) to: {save_dir}")


#Compute the TIE-based transmission image for each candidate gamma and display them side-by-side so you can pick the one with the cleanest
def run_gamma_scan(sam, ref, gamma_values, save_dir):
    os.makedirs(save_dir, exist_ok=True)

    n = len(gamma_values)
    cols = min(4, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
    axes = np.atleast_1d(axes).flatten()

    for ax, g in zip(axes, gamma_values):
        transmission, phase = TIE_Speckle(sam, ref, PIXEL_SIZE, g, PROP, WAVELENGTH)

        if PRINT_STATS:
            print(f"gamma {g:.3g}: NaN = {np.isnan(transmission).sum()}, "
                  f"min = {np.nanmin(transmission):.4g}, max = {np.nanmax(transmission):.4g}")

        lo, hi = percentile_limits(transmission)
        ax.imshow(transmission, cmap="gray", vmin=lo, vmax=hi)
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

    def load_image(path):
        stack = tiff.imread(path)
        if stack.ndim == 2:
            return stack.astype(np.float32)
        if AVERAGE_FRAMES:
            print(f"  averaging {stack.shape[0]} frames of {os.path.basename(path)}")
            return stack.mean(axis=0, dtype=np.float32)
        return stack[FRAME].astype(np.float32)

    ref = load_image(REFERENCE_IMAGE)
    sam = load_image(SAMPLE_IMAGE)

    print(f"reference: {REFERENCE_IMAGE}  shape={ref.shape}")
    print(f"sample:    {SAMPLE_IMAGE}  shape={sam.shape}")

    if ref.shape != sam.shape:
        raise ValueError(f"Reference and sample images have different shapes: {ref.shape} vs {sam.shape}")

    # Cut dead rows/columns off the edges. A strip of zeros that gets raised to the floor is a sharp step
    # against the real image, and the FFT derivatives turn that step into a bright band in the dark-field.
    if CROP_EDGE > 0:
        c = CROP_EDGE
        ref = ref[c:-c, c:-c]
        sam = sam[c:-c, c:-c]
        print(f"Cropped {c} px from every edge -> shape={ref.shape}")

    # Raise zero / very dark pixels to a small fraction of the typical reference level.
    # A floor of 1e-6 is not enough: the transmission step (an FFT filter) then returns tiny
    # NEGATIVE values next to zero pixels, log(negative) = NaN, and every dark-field panel goes blank.
    floor = INTENSITY_FLOOR_FRACTION * float(np.median(ref))
    print(f"Raw zero/dark pixels: reference {(ref < floor).sum()}, sample {(sam < floor).sum()} "
          f"(raised to {floor:.4g})")
    ref = np.maximum(ref, floor)
    sam = np.maximum(sam, floor)

    # Brightness match using the AIR patch (no specimen) so that air has a ratio of 1.
    # Matching whole-image means is wrong when the specimen covers much of the frame: it brightens
    # the sample and pushes the air ratio (and the transmission image) well above 1.
    if NORMALISE_SAMPLE:
        a0, a1, a2, a3 = AIR_REGION
        if ref[a0:a1, a2:a3].size == 0:
            raise ValueError(f"AIR_REGION={AIR_REGION} is empty for an image of shape {ref.shape}.")
        scale = float(ref[a0:a1, a2:a3].mean() / sam[a0:a1, a2:a3].mean())
        sam = np.maximum(sam * scale, floor)
        print(f"Sample scaled by {scale:.4g} so it matches the reference in the air patch")

    if PRINT_STATS:
        ratio = sam / ref
        print(f"ref min/max: {ref.min():.4g} / {ref.max():.4g}")
        print(f"sam min/max: {sam.min():.4g} / {sam.max():.4g}")
        print(f"ratio NaN count: {np.isnan(ratio).sum()}, "
              f"min/max: {np.nanmin(ratio):.4g} / {np.nanmax(ratio):.4g}")

    if RUN_GAMMA_SCAN:
        print(f"Running gamma scan over: {list(GAMMA_SCAN_VALUES)}")
        run_gamma_scan(sam, ref, GAMMA_SCAN_VALUES, SAVE_DIR)
        return

    # Quick look at the ratio image to judge/adjust SIGNAL_REGION and AIR_REGION
    if SHOW_PLOT:
        ratio = sam / ref
        lo, hi = percentile_limits(ratio)
        plt.imshow(ratio, cmap="gray", vmin=lo, vmax=hi)
        plt.title("sample / reference -- use this to pick signal/air regions")
        plt.colorbar()
        plt.show()

    # Check the two SNR regions BEFORE the solver uses them. The regularisation value is
    # 1 / (SNR * pixel_size^2) with SNR = mean(signal) / std(air). If the air patch is perfectly
    # flat (std = 0) or contains NaN, the value becomes inf/NaN and every dark-field panel is blank.
    ratio = sam / ref
    s0, s1, s2, s3 = SIGNAL_REGION
    a0, a1, a2, a3 = AIR_REGION
    signal_patch = ratio[s0:s1, s2:s3]
    air_patch = ratio[a0:a1, a2:a3]
    if signal_patch.size == 0 or air_patch.size == 0:
        raise ValueError(f"A region is empty (image shape {ratio.shape}). "
                         f"Check SIGNAL_REGION={SIGNAL_REGION} and AIR_REGION={AIR_REGION}.")
    air_std = float(np.std(air_patch))
    snr = float(np.mean(signal_patch)) / air_std if air_std > 0 else float("inf")
    print(f"Signal patch mean = {np.mean(signal_patch):.4g}, air patch std = {air_std:.4g}, SNR = {snr:.4g}")
    if not np.isfinite(snr) or snr <= 0:
        raise ValueError("SNR is not a usable number (air patch is flat, empty or contains NaN). "
                         "Move AIR_REGION onto a background area that still shows speckle noise.")

    # The solver takes log() of the transmission image, so it must be strictly positive.
    trans_check, _ = TIE_Speckle(sam, ref, PIXEL_SIZE, GAMMA, PROP, WAVELENGTH)
    n_bad = int((~(trans_check > 0)).sum())
    print(f"Transmission check: min = {np.nanmin(trans_check):.4g}, max = {np.nanmax(trans_check):.4g}, "
          f"non-positive pixels = {n_bad}")
    if n_bad:
        raise ValueError(f"{n_bad} transmission pixels are <= 0, so the dark-field would be all NaN. "
                         f"Increase INTENSITY_FLOOR_FRACTION (now {INTENSITY_FLOOR_FRACTION}) or check "
                         f"the raw images for dead/zero areas.")
    del trans_check

    print(f"Estimating regularisation parameter "
          f"(signal_region={SIGNAL_REGION}, air_region={AIR_REGION})...")
    regkr2 = compute_regularisation_parameter(
        sam, ref, PIXEL_SIZE, SIGNAL_REGION, AIR_REGION, show_plot=SHOW_PLOT
    )
    print(f"regkr2 = {regkr2:.4g}, gamma = {GAMMA}")

    print("Running single-exposure evolving Fokker-Planck...")
    D_ev, pos_ev, neg_ev, transmission_ev = Single_Evolving(
        sam, ref, PIXEL_SIZE, GAMMA, PROP, WAVELENGTH, SAVE_DIR, regkr2
    )
    tiff.imwrite(os.path.join(SAVE_DIR, "df_evolving.tiff"), D_ev.astype(np.float32))
    save_and_show_results(
        [
            ("Transmission (attenuation image)", transmission_ev),
            ("Dark-field, evolving (signed: + and -)", D_ev),
            ("Dark-field, evolving (positive part only)", pos_ev),
            ("Dark-field, evolving (negative part, magnitude)", -1 * neg_ev),
        ],
        "Single-exposure EVOLVING Fokker-Planck results",
        "evolving",
        SAVE_DIR,
    )

    if RUN_DEVOLVING:
        print("Running single-exposure devolving Fokker-Planck...")
        D_dev, pos_dev, neg_dev, transmission_dev = Single_Devolving(
            sam, ref, PIXEL_SIZE, GAMMA, PROP, WAVELENGTH, SAVE_DIR, regkr2
        )
        tiff.imwrite(os.path.join(SAVE_DIR, "df_devolving.tiff"), D_dev.astype(np.float32))
        save_and_show_results(
            [
                ("Transmission (attenuation image)", transmission_dev),
                ("Dark-field, devolving (signed: + and -)", D_dev),
                ("Dark-field, devolving (positive part only)", pos_dev),
                ("Dark-field, devolving (negative part, magnitude)", -1 * neg_dev),
            ],
            "Single-exposure DEVOLVING Fokker-Planck results",
            "devolving",
            SAVE_DIR,
        )

    print(f"\nDone. Results in: {os.path.abspath(SAVE_DIR)}")


if __name__ == "__main__":
    main()