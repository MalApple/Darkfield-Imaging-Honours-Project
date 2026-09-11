# ---------------------------------------------------------------------------------
# Written by Samantha Alloo // Date 4.11.2024
# Memory-optimized version //
# ---------------------------------------------------------------------------------
# Importing required modules
import numpy as np
import matplotlib.pyplot as plt
import os
import math
import gc
import scipy
from scipy import ndimage, misc
from PIL import Image
import time
import matplotlib.patches as patches
from scipy.ndimage import median_filter, gaussian_filter
import fabio
import pyedflib
import h5py
import csv
import re
from scipy.optimize import minimize
import tifffile as tiff
# ---------------------------------------------------------------------------------
def mirror_pad(image):
    """
    Equivalent to:
        h = np.concatenate((image, np.fliplr(image)), axis=1)
        v = np.concatenate((h, np.flipud(h)), axis=0)
    but built with one np.pad call, so the axis=1-only intermediate `h` is
    never materialised. Also enforces float32 so FFTs downstream don't
    silently upcast to float64.
    """
    return np.pad(
        np.asarray(image, dtype=np.float32),
        ((0, image.shape[0]), (0, image.shape[1])),
        mode='symmetric',
    )
def kspace_kykx(image_shape: tuple, pixel_size: float = 1):
    rows = image_shape[0]
    columns = image_shape[1]
    ky = 2 * math.pi * scipy.fft.fftfreq(rows, d=pixel_size)
    kx = 2 * math.pi * scipy.fft.fftfreq(columns, d=pixel_size)
    return ky.astype(np.float32), kx.astype(np.float32)
def invLaplacian(image, regkr2, pixel_size):
    row, column = image.shape
    flip = mirror_pad(image)

    ky, kx = kspace_kykx(flip.shape, pixel_size)
    kr2 = np.add.outer(ky ** 2, kx ** 2).astype(np.float32)

    ftimage = scipy.fft.fft2(flip).astype(np.complex64)
    del flip

    regdiv = (1 / (kr2 + regkr2)).astype(np.float32)
    del kr2
    invlapimageflip = (-1 * scipy.fft.ifft2(regdiv * ftimage)).astype(np.complex64)
    del ftimage, regdiv
    gc.collect()

    invlap = invlapimageflip[:row, :column].real.astype(np.float32).copy()
    del invlapimageflip
    gc.collect()
    return invlap, regkr2
def xderivative(image, pixel_size):
    h, w = image.shape
    im_mirror_v = mirror_pad(image)

    ky, kx = kspace_kykx(im_mirror_v.shape, pixel_size)
    i_kx = (1j * kx).astype(np.complex64)

    fft_im = scipy.fft.fft2(im_mirror_v).astype(np.complex64)
    del im_mirror_v
    fft_im *= i_kx[None, :]
    dx_im = np.real(scipy.fft.ifft2(fft_im)).astype(np.float32)
    del fft_im
    gc.collect()

    dx_im_crop = dx_im[:h, :w].copy()
    del dx_im
    return dx_im_crop
def yderivative(image, pixel_size):
    h, w = image.shape
    im_mirror_v = mirror_pad(image)

    ky, kx = kspace_kykx(im_mirror_v.shape, pixel_size)
    i_ky = (1j * ky).astype(np.complex64)

    fft_im = scipy.fft.fft2(im_mirror_v).astype(np.complex64)
    del im_mirror_v
    fft_im *= i_ky[:, None]
    dy_im = np.real(scipy.fft.ifft2(fft_im)).astype(np.float32)
    del fft_im
    gc.collect()

    dy_im_crop = dy_im[:h, :w].copy()
    del dy_im
    return dy_im_crop
def lowpass_2D(image, r, pixel_size):
    rows = image.shape[0]
    columns = image.shape[1]
    m = np.fft.fftfreq(rows, d=pixel_size)
    n = np.fft.fftfreq(columns, d=pixel_size)
    ky = (2 * math.pi * m)
    kx = (2 * math.pi * n)

    kx2 = kx ** 2
    ky2 = ky ** 2
    kr2 = np.add.outer(ky2, kx2).astype(np.float32)

    lowpass_2d = np.exp(-r * kr2).astype(np.float32)
    return lowpass_2d
def highpass_2D(image, r, pixel_size):
    rows = image.shape[0]
    columns = image.shape[1]
    m = np.fft.fftfreq(rows, d=pixel_size)
    n = np.fft.fftfreq(columns, d=pixel_size)
    ky = (2 * math.pi * m)
    kx = (2 * math.pi * n)

    kx2 = kx ** 2
    ky2 = ky ** 2
    kr2 = np.add.outer(ky2, kx2).astype(np.float32)

    highpass_2d = (1 - np.exp(-r * kr2)).astype(np.float32)
    return highpass_2d
def midpass_2D(image, r, pixel_size):
    rows = image.shape[0]
    columns = image.shape[1]
    m = np.fft.fftfreq(rows, d=pixel_size)
    n = np.fft.fftfreq(columns, d=pixel_size)
    ky = (2 * math.pi * m)
    kx = (2 * math.pi * n)

    kx2 = kx ** 2
    ky2 = ky ** 2
    kr2 = np.add.outer(ky2, kx2)
    kr = np.sqrt(kr2)

    highpass_2d = 1 - np.exp(-r * (kr ** 2))

    ikx = (1j * kx).astype(np.complex64)
    denom = np.add.outer((-1 * ky), ikx)

    midpass_2d = np.divide(
        complex(1., 0.) * highpass_2d, denom,
        out=np.zeros_like(complex(1., 0.) * highpass_2d),
        where=denom != 0,
    ).astype(np.complex64)

    return midpass_2d
def compute_regularisation_parameter(sam_corr, ref_corr, eff_pix_size,signal_region, air_region,show_plot=True):
    """
    Determine the optimal regularisation parameter for the inverse Laplacian
    operator, based on the SNR between a signal region (inside the sample)
    and an air region (background) of the sample speckle image.

    Parameters
    ----------
    sam_corr : np.ndarray
        2D (or stack, indexed as sam_corr[0]) array of the sample speckle image.
    ref_corr : np.ndarray
        2D (or stack, indexed as ref_corr[0]) array of the reference speckle image.
    eff_pix_size : float
        Effective pixel size used to scale the regularisation parameter.
    signal_region : tuple of int
        (row_start, row_end, col_start, col_end) defining the region inside
        the sample used to estimate the signal.
    air_region : tuple of int
        (row_start, row_end, col_start, col_end) defining the region in air
        used to estimate the background noise.
    show_plot : bool, optional
        If True (default), display the ratio image with the two regions
        overlaid for visual verification.

    Returns
    -------
    reg_snr : float
        The determined optimal regularisation parameter.
    """
    signal_ri, signal_rf, signal_ci, signal_cf = signal_region
    air_ri, air_rf, air_ci, air_cf = air_region

    ratio_img = sam_corr / ref_corr

    signal = ratio_img[signal_ri:signal_rf, signal_ci:signal_cf]
    air = ratio_img[air_ri:air_rf, air_ci:air_cf]

    if show_plot:

        fig, ax = plt.subplots(figsize=(8, 6))
        ax.imshow(ratio_img, cmap='gray', vmin=0.6, vmax=1)

        signal_rect = patches.Rectangle(
            (signal_ci, signal_ri), signal_cf - signal_ci, signal_rf - signal_ri,
            linewidth=2, edgecolor='r', facecolor='none', label='Signal region'
        )
        air_rect = patches.Rectangle(
            (air_ci, air_ri), air_cf - air_ci, air_rf - air_ri,
            linewidth=2, edgecolor='b', facecolor='none', label='Air region'
        )
        ax.add_patch(signal_rect)
        ax.add_patch(air_rect)
        ax.title.set_text('Locations of SNR calculation regions: (r) signal, (b) air')
        plt.tight_layout()
        plt.show()
        del ratio_img
        plt.close(fig)

    signal_mean = np.mean(signal)
    air_std = np.std(air)
    SNR = signal_mean / air_std
    reg_snr = 1 / (SNR * eff_pix_size ** 2)

    print('The determined optimal regularisation parameter for the inverse Laplacian operator is ' + str(reg_snr))

    return reg_snr
def find_optimal_epsilon(epsilon_initial, phase_TIE, kr2, ftimage):
    def mse_loss(epsilon):
        regdiv = 1 / (kr2 + epsilon)
        phase_FP_it = np.real(
            -1 * np.fft.ifft2(regdiv * ftimage)
        )
        phase_FP_it_crop = phase_FP_it[:phase_TIE.shape[0], :phase_TIE.shape[1]]
        squared_diff = (phase_TIE - phase_FP_it_crop) ** 2
        MSE = np.mean(squared_diff, dtype=np.float64)
        return MSE

    result = minimize(mse_loss, x0=epsilon_initial, method="L-BFGS-B")

    if not result.success:
        raise RuntimeError("Optimization failed: " + result.message)
    else:
        print(f"Optimization successful: {result.message}")

    best_fine_epsilon = result.x[0]
    best_fine_phase = np.real(
        -1 * np.fft.ifft2(1 / (kr2 + best_fine_epsilon) * ftimage)
    )[:phase_TIE.shape[0], :phase_TIE.shape[1]]

    return best_fine_phase, best_fine_epsilon
def EpsilonOpt_IterativeAlgorithm_MSE(epsilon_initial, phase_TIE, kr2, ftimage):
    # (unchanged -- scalar iterative search, not a memory hotspot)
    ep_value = []
    MSE_value = []

    rows, columns = phase_TIE.shape
    iteration = 0

    previous_MSE = float('inf')
    best_epsilon = epsilon_initial
    best_phase_FP_it = None

    while True:
        print(f"Iteration {iteration}: Epsilon Value = {epsilon_initial}")

        regdiv = 1 / (kr2 + epsilon_initial)
        phase_FP_it = np.real(
            -1 * np.fft.ifft2(regdiv * ftimage)[0:rows, 0:columns])

        squared_diff = (phase_TIE - phase_FP_it) ** 2
        MSE = np.mean(squared_diff, dtype=np.float64)
        print(f"MSE at iteration {iteration}: {MSE}")

        if MSE < previous_MSE:
            previous_MSE = MSE
            best_epsilon = epsilon_initial
            best_phase_FP_it = phase_FP_it
        else:
            print(f"MSE increased at iteration {iteration}. Stopping.")
            break

        epsilon_initial *= 5
        iteration += 1

        ep_value.append(epsilon_initial)
        MSE_value.append(MSE)

    print(f"Starting fine-tuning search around epsilon = {best_epsilon}")

    epsilon_order = np.floor(np.log10(best_epsilon))
    epsilon_step = 10 ** (epsilon_order - 3)

    best_fine_MSE = previous_MSE
    best_fine_epsilon = best_epsilon
    best_fine_phase = best_phase_FP_it

    previous_MSE_fine = float('inf')
    epsilon_fine = 10 ** (epsilon_order - 1)

    while True:
        regdiv = 1 / (kr2 + epsilon_fine)
        phase_FP_it_fine = np.real(
            -1 * np.fft.ifft2(regdiv * ftimage)[0:rows, 0:columns])

        squared_diff_fine = (phase_TIE - phase_FP_it_fine) ** 2
        MSE_fine = np.mean(squared_diff_fine)
        print(f"Fine-tuning MSE for epsilon = {epsilon_fine}: MSE = {MSE_fine}")

        ep_value.append(epsilon_fine)
        MSE_value.append(MSE_fine)

        if MSE_fine > previous_MSE_fine:
            print(f"MSE increased for epsilon = {epsilon_fine}. Stopping fine-tuning.")
            break

        previous_MSE_fine = MSE_fine
        best_fine_MSE = MSE_fine
        best_fine_epsilon = epsilon_fine
        best_fine_phase = phase_FP_it_fine

        epsilon_fine += epsilon_step

    print(f"Best fine-tuned epsilon: {best_fine_epsilon} with MSE: {best_fine_MSE}")

    values = np.array([ep_value, MSE_value])
    with open('Epsilon&MSE.csv', mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(values)

    return best_fine_phase, best_fine_epsilon
# ---------------------------------------------------------------------------------
# Here are all of the solutions for the different inverse problems
# 1) Transport-of-intensity equation single-exposure speckle-based X-ray imaging phase-retrieval algorithm:
def TIE_Speckle(Is, Ir, pixel_size, gamma, prop, wavelength):
    IsIr = (Is / Ir).astype(np.float32)
    IsIr_mirror = mirror_pad(IsIr)
    del IsIr

    ft_IsIr = scipy.fft.fft2(IsIr_mirror).astype(np.complex64)
    del IsIr_mirror
    ky, kx = kspace_kykx(ft_IsIr.shape, pixel_size)
    ky2kx2 = np.add.outer(ky ** 2, kx ** 2).astype(np.float32)
    C = np.float32((prop * gamma * wavelength) / (4 * math.pi))
    ins_ifft = ft_IsIr / (1 + C * ky2kx2)
    del ft_IsIr, ky2kx2
    Iob = np.real(scipy.fft.ifft2(ins_ifft)).astype(np.float32)
    del ins_ifft
    gc.collect()

    Iob_crop = Iob[:Is.shape[0], :Is.shape[1]].copy()
    del Iob

    Phase_crop = (gamma / 2 * np.log(Iob_crop)).astype(np.float32)

    return Iob_crop, Phase_crop

# 2) Single-exposure evolving speckle-based X-ray imaging Fokker--Planck perspective
def Single_Evolving(Is, Ir, pixel_size, gamma, prop, wavelength, savedir, regkr2):
    tranmission, phase = TIE_Speckle(Is, Ir, pixel_size, gamma, prop, wavelength)
    del phase

    Ir_Tran = (Ir * tranmission).astype(np.float32)
    Flux = (Ir_Tran - Is).astype(np.float32)
    ln_trans = np.log(tranmission).astype(np.float32)

    C = np.float32((prop * gamma * wavelength) / (4 * math.pi))

    tmp = xderivative(ln_trans, pixel_size)
    tmp *= Ir_Tran
    Flow = xderivative(tmp, pixel_size)
    Flow *= C
    del tmp
    gc.collect()

    tmp = yderivative(ln_trans, pixel_size)
    tmp *= Ir_Tran
    tmp = yderivative(tmp, pixel_size)
    tmp *= C
    Flow += tmp
    del tmp, ln_trans
    gc.collect()

    FlowMINUSFlux = (Flow - Flux).astype(np.float32)
    del Flow, Flux
    gc.collect()

    invlapFF, reg = invLaplacian(FlowMINUSFlux, regkr2, pixel_size)
    del FlowMINUSFlux
    gc.collect()

    D = invlapFF / (prop ** 2 * Ir_Tran)
    del invlapFF, Ir_Tran
    gc.collect()

    positive_D = np.clip(D, 0, np.inf)
    negative_D = np.clip(D, -np.inf, 0)

    os.chdir(savedir)
    Image.fromarray(tranmission).save(str(prop)+'_TIE_Transmission.tif')
    Image.fromarray(D).save(str(prop)+'XDF_SingEv_{}.tif'.format(f"{reg:.3g}"))
    Image.fromarray(positive_D).save(str(prop)+'Pos_SingEv_{}.tif'.format(f"{reg:.3g}"))
    Image.fromarray(-1 * negative_D).save(
        str(prop)+'Neg_SingEv_{}.tif'.format(f"{reg:.3g}"))

    print('Single-exposure evolving SBXI Fokker-Planck inverse problem has been solved!')
    return D, positive_D, negative_D, tranmission

# 3) Single-exposure devolving speckle-based X-ray imaging Fokker--Planck perspective
def Single_Devolving(Is, Ir, pixel_size, gamma, prop, wavelength, savedir, regkr2):
    tranmission, phase = TIE_Speckle(Is, Ir, pixel_size, gamma, prop, wavelength)
    del phase

    Ir_Tran = (Ir * tranmission).astype(np.float32)
    Flux = (Is - Ir_Tran).astype(np.float32)
    ln_trans = np.log(tranmission).astype(np.float32)
    del Ir_Tran
    gc.collect()

    C = np.float32((prop * gamma * wavelength) / (4 * math.pi))

    tmp = xderivative(ln_trans, pixel_size)
    tmp *= Is
    Flow = xderivative(tmp, pixel_size)
    Flow *= C
    del tmp
    gc.collect()

    tmp = yderivative(ln_trans, pixel_size)
    tmp *= Is
    tmp = yderivative(tmp, pixel_size)
    tmp *= C
    Flow += tmp
    del tmp, ln_trans
    gc.collect()

    FluxaddFlow = (Flux + Flow).astype(np.float32)
    del Flux, Flow
    gc.collect()

    invlapFF, reg = invLaplacian(FluxaddFlow, regkr2, pixel_size)
    del FluxaddFlow
    gc.collect()

    D = invlapFF / (prop ** 2 * Is)
    del invlapFF
    gc.collect()

    positive_D = np.clip(D, 0, np.inf)
    negative_D = np.clip(D, -np.inf, 0)

    os.chdir(savedir)
    Image.fromarray(tranmission).save(str(prop)+'TIE_Transmission.tif')
    Image.fromarray(D).save(str(prop)+'XDF_SingDev_{}.tif'.format(f"{reg:.3g}"))
    Image.fromarray(positive_D).save(str(prop)+'Pos_SingDev_{}.tif'.format(f"{reg:.3g}"))
    Image.fromarray(-1 * negative_D).save(
        str(prop)+'Neg_SingDev_{}.tif'.format(f"{reg:.3g}"))
    print('Single-exposure devolving SBXI Fokker-Planck inverse problem has been solved!')
    return D, positive_D, negative_D, tranmission

# 4) Multiple-exposure evolving speckle-based X-ray imaging Fokker--Planck perspective
def Multiple_Evolving(num_masks, Is, Ir, gamma, wavelength, prop, pixel_size, savedir):
    # rows/columns derived locally from the data instead of relying on
    # module-level globals -- avoids a NameError if this function is ever
    # called before the globals are set, and costs nothing.
    rows, columns = Ir.shape[1], Ir.shape[2]

    # fix #4: write straight into the preallocated arrays instead of
    # building coeff_D / coeff_dx / coeff_dy / lapacaian / RHS lists first.
    coefficient_A = np.empty((num_masks, 4, rows, columns), dtype=np.float32)
    coefficient_b = np.empty((num_masks, 1, rows, columns), dtype=np.float32)

    for i in range(num_masks):
        rhs = ((1 / prop) * (Ir[i, :, :] - Is[i, :, :])).astype(np.float32)
        lap = Ir[i, :, :].astype(np.float32)
        deff = (-1 * np.divide(ndimage.laplace(Ir[i, :, :]), pixel_size ** 2)).astype(np.float32)
        dy, dx = np.gradient(Ir[i, :, :], pixel_size)
        dy_r = (-2 * dy).astype(np.float32)
        dx_r = (-2 * dx).astype(np.float32)
        del dy, dx

        coefficient_A[i, 0, :, :] = lap
        coefficient_A[i, 1, :, :] = deff
        coefficient_A[i, 2, :, :] = dx_r
        coefficient_A[i, 3, :, :] = dy_r
        coefficient_b[i, 0, :, :] = rhs
        del rhs, lap, deff, dy_r, dx_r

    identity = np.identity(4, dtype=np.float32)
    alpha = np.std(coefficient_A) / 10000
    reg = np.multiply(alpha, identity)
    reg_repeat = np.repeat(reg, rows * columns).reshape(4, 4, rows, columns).astype(np.float32)
    zero_repeat = np.zeros((4, 1, rows, columns), dtype=np.float32)

    coefficient_A_reg = np.vstack([coefficient_A, reg_repeat])
    del coefficient_A, reg_repeat
    coefficient_b_reg = np.vstack([coefficient_b, zero_repeat])
    del coefficient_b, zero_repeat
    gc.collect()

    reg_Qr, reg_Rr = np.linalg.qr(coefficient_A_reg.transpose([2, 3, 0, 1]))
    del coefficient_A_reg
    reg_x = np.linalg.solve(reg_Rr, np.matmul(np.matrix.transpose(reg_Qr.transpose([2, 3, 1, 0])),
                                              coefficient_b_reg.transpose([2, 3, 0, 1])))
    del reg_Qr, reg_Rr, coefficient_b_reg
    gc.collect()

    lap_phiDF = reg_x[:, :, 0, 0]
    DFqr = reg_x[:, :, 1, 0] / prop
    dxDF = reg_x[:, :, 2, 0] / prop
    dyDF = reg_x[:, :, 3, 0] / prop
    del reg_x
    gc.collect()

    os.chdir(savedir)
    cutoff = 10

    i_dyDF = (dyDF * 1j).astype(np.complex64)
    insideft = (dxDF + i_dyDF).astype(np.complex64)
    del i_dyDF, dxDF, dyDF
    insideftm = np.concatenate((insideft, np.flipud(insideft)), axis=0)
    del insideft
    ft_dx_idy = scipy.fft.fft2(insideftm).astype(np.complex64)
    del insideftm
    MP = midpass_2D(ft_dx_idy, cutoff, pixel_size)
    MP_deriv = MP * ft_dx_idy
    del MP, ft_dx_idy
    gc.collect()

    DFqrm = np.concatenate((DFqr, np.flipud(DFqr)), axis=0).astype(np.float32)
    ft_DFqr = scipy.fft.fft2(DFqrm).astype(np.complex64)
    del DFqrm
    LP = lowpass_2D(ft_DFqr, cutoff, pixel_size)
    LP_DFqr = LP * ft_DFqr
    del LP, ft_DFqr
    gc.collect()

    combined = LP_DFqr + MP_deriv
    del LP_DFqr, MP_deriv
    # fix #1: .copy() so the full doubled-height `combined` buffer is released
    DF_filtered = np.real(scipy.fft.ifft2(combined)[0:int(rows), :]).astype(np.float32).copy()
    del combined
    gc.collect()

    ref = Ir[0, :, :]
    sam = Is[0, :, :]

    lapphi = ((ref - sam + prop ** 2 * np.divide(ndimage.laplace(DF_filtered * ref), pixel_size ** 2)) * (
                (2 * math.pi) / (wavelength * prop * ref))).astype(np.float32)
    lapphi_m = mirror_pad(lapphi)
    del lapphi
    gc.collect()

    ky, kx = kspace_kykx(lapphi_m.shape, pixel_size)
    kr2 = np.add.outer(ky ** 2, kx ** 2).astype(np.float32)

    ftimage = scipy.fft.fft2(lapphi_m).astype(np.complex64)
    del lapphi_m
    gc.collect()

    epsilon_inital = kr2[kr2 > 0][0] if np.any(kr2 > 0) else None

    I_TIE, phase_TIE = TIE_Speckle(Is[0], Ir[0], pixel_size, gamma, prop, wavelength)
    Image.fromarray(I_TIE).save(str(prop)+'TIE_Tran_{}.tiff'.format(str(gamma)))
    Image.fromarray(phase_TIE).save(str(prop)+'TIE_Phase_{}.tiff'.format(str(gamma)))
    del I_TIE

    # # Jannis' implementation, used by default (matches the original)
    # optimal_phase_FP_MSE, optimal_epsilon_MSE = find_optimal_epsilon(epsilon_inital, phase_TIE, kr2, ftimage)

    # Below is using the originally-published iterative procedure
    optimal_phase_FP_MSE, optimal_epsilon_MSE  = EpsilonOpt_IterativeAlgorithm_MSE(epsilon_inital, phase_TIE, kr2, ftimage)


    del phase_TIE, ftimage, kr2
    gc.collect()

    optimal_phase_FP_MSE = optimal_phase_FP_MSE.astype(np.float32)
    Image.fromarray(optimal_phase_FP_MSE).save(
        str(prop)+'Phase_MultEv_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{optimal_epsilon_MSE:.3g}"))

    Iob = np.exp(2 * optimal_phase_FP_MSE / gamma).astype(np.float32)
    del optimal_phase_FP_MSE
    Image.fromarray(Iob).save(
        str(prop)+'Trans_MultEv_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{optimal_epsilon_MSE:.3g}"))

    beta = 1.8091841*10**(-10)
    mu = (4*math.pi)/wavelength * beta
    thick = (-1 * np.log(Iob) / mu).astype(np.float32)
    Image.fromarray(thick).save(
        'Thick_MultEv_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{optimal_epsilon_MSE:.3g}"))
    del thick
    gc.collect()

    DF_atten = np.real(DF_filtered / Iob).astype(np.float32)
    del DF_filtered
    gc.collect()

    Image.fromarray(np.real(DF_atten)).save(
        str(prop)+'XDF_MultEv_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{optimal_epsilon_MSE:.3g}"))

    positive_D = np.clip(DF_atten, 0, np.inf)
    negative_D = np.clip(DF_atten, -np.inf, 0)
    Image.fromarray(positive_D).save(
        str(prop)+'PosXDF_MultEv_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{optimal_epsilon_MSE:.3g}"))
    Image.fromarray(-1 * negative_D).save(
        str(prop)+'NegXDF_MultEv_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{optimal_epsilon_MSE:.3g}"))

    print('Multiple-exposure evolving SBXI Fokker-Planck inverse problem has been solved!')

    return DF_atten, positive_D, negative_D, Iob, optimal_epsilon_MSE

# 5) Multiple-exposure devolving speckle-based X-ray imaging Fokker--Planck perspective
def Multiple_Devolving(num_masks, Is, Ir, gamma, wavelength, prop, pixel_size, savedir, regkr2):
    rows, columns = Ir.shape[1], Ir.shape[2]

    # fix #4: direct-write, same as Multiple_Evolving
    coefficient_A = np.empty((num_masks, 4, rows, columns), dtype=np.float32)
    coefficient_b = np.empty((num_masks, 1, rows, columns), dtype=np.float32)

    for i in range(num_masks):
        rhs = ((1 / prop) * (Is[i, :, :] - Ir[i, :, :])).astype(np.float32)
        lap = Is[i, :, :].astype(np.float32)
        deff = np.divide(ndimage.laplace(Is[i, :, :]), pixel_size ** 2).astype(np.float32)
        dy, dx = np.gradient(Is[i, :, :], pixel_size)
        dy_r = (2 * dy).astype(np.float32)
        dx_r = (2 * dx).astype(np.float32)
        del dy, dx

        coefficient_A[i, 0, :, :] = lap
        coefficient_A[i, 1, :, :] = deff
        coefficient_A[i, 2, :, :] = dx_r
        coefficient_A[i, 3, :, :] = dy_r
        coefficient_b[i, 0, :, :] = rhs
        del rhs, lap, deff, dy_r, dx_r

    identity = np.identity(4, dtype=np.float32)
    alpha = np.std(coefficient_A) / 10000
    reg = np.multiply(alpha, identity)
    reg_repeat = np.repeat(reg, rows * columns).reshape(4, 4, rows, columns).astype(np.float32)
    zero_repeat = np.zeros((4, 1, rows, columns), dtype=np.float32)

    coefficient_A_reg = np.vstack([coefficient_A, reg_repeat])
    del coefficient_A, reg_repeat
    coefficient_b_reg = np.vstack([coefficient_b, zero_repeat])
    del coefficient_b, zero_repeat
    gc.collect()

    reg_Qr, reg_Rr = np.linalg.qr(coefficient_A_reg.transpose([2, 3, 0, 1]))
    del coefficient_A_reg
    reg_x = np.linalg.solve(reg_Rr, np.matmul(np.matrix.transpose(reg_Qr.transpose([2, 3, 1, 0])),
                                              coefficient_b_reg.transpose([2, 3, 0, 1])))
    del reg_Qr, reg_Rr, coefficient_b_reg
    gc.collect()

    lap_phiDF = reg_x[:, :, 0, 0]
    DFqr = reg_x[:, :, 1, 0] / prop
    dxDF = reg_x[:, :, 2, 0] / prop
    dyDF = reg_x[:, :, 3, 0] / prop
    del reg_x
    gc.collect()

    os.chdir(savedir)
    cutoff = 10

    i_dyDF = (dyDF * 1j).astype(np.complex64)
    insideft = (dxDF + i_dyDF).astype(np.complex64)
    del i_dyDF, dxDF, dyDF
    insideftm = np.concatenate((insideft, np.flipud(insideft)), axis=0)
    del insideft
    ft_dx_idy = scipy.fft.fft2(insideftm).astype(np.complex64)
    del insideftm
    MP = midpass_2D(ft_dx_idy, cutoff, pixel_size)
    MP_deriv = MP * ft_dx_idy
    del MP, ft_dx_idy
    gc.collect()

    DFqrm = np.concatenate((DFqr, np.flipud(DFqr)), axis=0).astype(np.float32)
    ft_DFqr = scipy.fft.fft2(DFqrm).astype(np.complex64)
    del DFqrm
    LP = lowpass_2D(ft_DFqr, cutoff, pixel_size)
    LP_DFqr = LP * ft_DFqr
    del LP, ft_DFqr
    gc.collect()

    combined = LP_DFqr + MP_deriv
    del LP_DFqr, MP_deriv
    DF_filtered = np.real(scipy.fft.ifft2(combined)[0:int(rows), :]).astype(np.float32).copy()
    del combined
    gc.collect()

    ref = Ir[0, :, :]
    sam = Is[0, :, :]
    lapphi = ((ref - sam + prop ** 2 * np.divide(ndimage.laplace(DF_filtered * ref), pixel_size ** 2)) * (
                (2 * math.pi) / (wavelength * prop * ref))).astype(np.float32)

    phi, reg = invLaplacian(lapphi, regkr2, pixel_size)
    del lapphi
    gc.collect()

    Image.fromarray(phi).save(
        str(prop)+'Phase_MultDev_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{regkr2:.3g}"))
    Iob = np.exp(2 * phi / gamma).astype(np.float32)
    del phi
    Image.fromarray(Iob).save(str(prop)+'Trans_MultDev_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{regkr2:.3g}"))

    beta = 1.8091841*10**(-10)
    mu = (4*math.pi)/wavelength * beta
    thick = (-1 * np.log(Iob) / mu).astype(np.float32)
    # NOTE: original referenced the undefined `optimal_epsilon_MSE` here --
    # replaced with `regkr2`, see header note.
    Image.fromarray(thick).save(
        'Thick_MultDev_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{regkr2:.3g}"))
    del thick
    gc.collect()

    DF_atten = np.real(DF_filtered / Iob).astype(np.float32)
    del DF_filtered
    gc.collect()

    Image.fromarray(np.real(DF_atten)).save(
        str(prop)+'XDF_MultDev_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{regkr2:.3g}"))

    positive_D = np.clip(DF_atten, 0, np.inf)
    negative_D = np.clip(DF_atten, -np.inf, 0)
    Image.fromarray(positive_D).save(
        str(prop)+'PosXDF_MultDev_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{regkr2:.3g}"))
    Image.fromarray(-1 * negative_D).save(
        str(prop)+'NegXDF_MultDev_{}.tif'.format('mask' + str(num_masks) + 'gamma' + str(gamma) + 'r' + str(cutoff)+'reg'+f"{regkr2:.3g}"))

    print('Multiple-exposure devolving SBXI Fokker-Planck inverse problem has been solved!')
    return DF_atten, positive_D, negative_D, Iob
# ---------------------------------------------------------------------------------
# Test Data: Four-rod  sample imaged at the MicroCT beamline
data = r'C:\Users\sall0037\Documents\Experimental_Data\5_MaskComparison_MCT 19663\4WoodSample_MCTApril23'
os.chdir(data)
num_masks = 10
gamma = 2335 # That for perspex
wavelength = 4.9594*10**-5 # [microns]
prop = 0.7*10**6 # [microns]
pixel_size = 6.5 # [microns]
savedir = r'C:\Users\sall0037\Documents\DiscoveryProject_FokkerPlanck\Analysis\OptimisingCode\FourRod'

ff = np.double(np.asarray(Image.open('FF_1m.tif')))[870:1300,140:2360]
dc = 0
rows, columns = ff.shape

Ir = np.empty([int(num_masks),int(rows),int(columns)])
Is = np.empty([int(num_masks),int(rows),int(columns)])

for i in range(1, num_masks+1):
    iterable = i #f"{i:03d}"
    # -------------------------------------------------------------------------
    # Reading in data: change string for start of filename as required
    ir = tiff.imread('mask_aligned_{}.tif'.format(str(iterable))) # reads is in straight at a numpy array Marie has already FF- and DC-corrected the image
    isa = np.double(np.asarray(Image.open('Sam{}.tif'.format(str(iterable)))))[870:1300,140:2360]

    isa = (isa-dc)/(ff-dc)

    Is[int(i-1)] = (isa)  # shape =  [num_masks, rows, columns]
    Ir[int(i-1)] = (ir)  # shape =  [num_masks, rows, columns]

    print('Completed Reading Data From Mask = ' + str(i))
    # -------------------------------------------------------------------------



D_Mev ,positive_D_Mev, negative_D_Mev, transmission_Mev, optimal_epsilon_MSE = Multiple_Evolving(num_masks, Is, Ir, gamma, wavelength, prop, pixel_size, savedir)
D_Mdev ,positive_D_Mdev, negative_D_Mdev, transmission_Mdev = Multiple_Devolving(num_masks, Is, Ir, gamma, wavelength, prop, pixel_size, savedir , optimal_epsilon_MSE)
D_Sev, positive_D_Sev, negative_D_Sev, transmission  = Single_Evolving(Is[0], Ir[0], pixel_size,gamma, prop, wavelength,savedir , optimal_epsilon_MSE)
D_Sdev, positive_D_Sdev, negative_D_Sdev, tranmission  = Single_Devolving(Is[0], Ir[0], pixel_size,gamma, prop, wavelength,savedir , optimal_epsilon_MSE)

# To do single-exposure only, then use the below code
# Step 1): Determine the regularisation parameter
sam_0 = Is[0] # select single image if Is and Ir are multi-speckle-position data in numpy arrays
ref_0 = Ir[0]

plt.imshow(sam_0/ref_0) # can use this to deduce the two regions required for computation
plt.show()

reg_snr = compute_regularisation_parameter(sam_0, ref_0, pixel_size,signal_region=(0, sam_0.shape[0], 0, sam_0.shape[1]), air_region=(0, sam_0.shape[0], 1400, 1600))
D_Sev, positive_D_Sev, negative_D_Sev, transmission  = Single_Evolving(sam_0, ref_0, pixel_size,gamma, prop, wavelength,savedir , reg_snr)
D_Sdev, positive_D_Sdev, negative_D_Sdev, tranmission  = Single_Devolving(sam_0, ref_0, pixel_size,gamma, prop, wavelength,savedir , reg_snr)


