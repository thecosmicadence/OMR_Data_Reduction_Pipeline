import numpy as np
from scipy.fft import fft, ifft


def measure_shift_subpixel(ref_flux, tar_flux):
    """
    Return sub-pixel shift using FFT cross-correlation with Hanning windowing.
    Optimized for non-periodic spectral data.

    Parameters
    ----------
    ref_flux : array-like
        Reference spectrum flux array.
    tar_flux : array-like
        Target spectrum flux array (same length as ref_flux).

    Returns
    -------
    float
        Sub-pixel shift in pixels (positive = target is shifted right of reference).
    """
    # 1. Flatten arrays to ensure 1D inputs
    ref_flux = np.asarray(ref_flux).flatten()
    tar_flux = np.asarray(tar_flux).flatten()

    # 2. Apply Hanning window to reduce edge ringing
    window = np.hanning(len(ref_flux))
    ref_flux_w = (ref_flux - np.mean(ref_flux)) * window
    tar_flux_w = (tar_flux - np.mean(tar_flux)) * window

    n = len(ref_flux_w)
    f_ref = fft(ref_flux_w)
    f_tar = fft(tar_flux_w)

    # 3. Cross-correlation in frequency domain
    corr = ifft(f_tar * np.conj(f_ref))
    corr = np.abs(corr)

    # 4. Find integer peak, wrap negatives to represent left shifts
    peak = int(np.argmax(corr))
    if peak > n // 2:
        peak -= n

    # 5. Sub-pixel refinement via quadratic fit around the peak
    if 1 <= abs(peak) < n // 2 - 1:
        idx = peak if peak >= 0 else n + peak
        y0, y1, y2 = corr[idx - 1], corr[idx], corr[(idx + 1) % n]

        denom = y0 - 2 * y1 + y2
        offset = 0.5 * (y0 - y2) / denom if denom != 0 else 0.0
    else:
        offset = 0.0

    return float(peak + offset)