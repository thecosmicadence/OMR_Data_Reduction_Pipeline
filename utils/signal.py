import numpy as np
from scipy.fft import fft, ifft


def measure_shift_integer(ref_flux, tar_flux):
    """
    Return pure integer pixel shift using FFT cross-correlation.
    Perfect for zero-interpolation array slicing.

    Parameters
    ----------
    ref_flux : array-like
        Reference spectrum flux array.
    tar_flux : array-like
        Target spectrum flux array (same length as ref_flux).

    Returns
    -------
    int
        Integer shift in pixels (positive = target is shifted right of reference).
    """
    # 1. Flatten arrays to ensure 1D inputs
    ref_flux = ref_flux.flatten()
    tar_flux = tar_flux.flatten()

    # 2. Apply Hanning Window to reduce edge ringing
    window = np.hanning(len(ref_flux))
    ref_flux_w = (ref_flux - np.mean(ref_flux)) * window
    tar_flux_w = (tar_flux - np.mean(tar_flux)) * window

    n = len(ref_flux_w)
    f_ref = fft(ref_flux_w)
    f_tar = fft(tar_flux_w)

    # 3. Cross-correlation
    corr = ifft(f_tar * np.conj(f_ref))
    corr = np.abs(corr)

    # 4. Find Peak (Discrete Integer)
    peak = np.argmax(corr)
    if peak > n // 2:
        peak -= n

    # Return the exact integer bucket
    return int(peak)