"""Shipped helper — save an InferenceData that contains BOTH the parameter posterior
AND the forecast prediction draws.

Forecaster agents MUST call ``save_idata_with_predictions(...)`` instead of a bare
``idata.to_netcdf(...)``. This guarantees the saved ``outputs/idata.nc`` carries a
``predictions`` group (per-draw ``p_event_by_horizon``) alongside ``posterior``.
The post-run validation hook (``validate_predictions.sh``) fails the session if any
forecaster's idata.nc is missing that group.

Copy this file into your instance directory and import it, e.g.::

    from save_predictions import save_idata_with_predictions
    save_idata_with_predictions(idata, p_by_h, horizon_days, "outputs/idata.nc")

``p_by_h`` is the SAME per-draw cumulative probability you already compute for the
credible intervals in ``forecast.json`` — do not invent a new quantity.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import xarray as xr


def save_idata_with_predictions(
    idata,
    p_event_by_horizon,
    horizon_days: Sequence[float],
    path: str = "outputs/idata.nc",
) -> str:
    """Attach per-draw forecast predictions to ``idata`` and write it to ``path``.

    Parameters
    ----------
    idata : arviz.InferenceData
        Must already contain the ``posterior`` group (plus, ideally, ``sample_stats``,
        ``log_likelihood`` and ``log_prior``).
    p_event_by_horizon : array-like
        Per-draw cumulative P(event by horizon). Accepted shapes:
        ``(chain, draw, horizon)`` or ``(chain*draw, horizon)``. These are the SAME
        per-draw probabilities used to build the credible intervals in ``forecast.json``.
    horizon_days : sequence of float
        Day offset of each horizon from the forecast origin (length == n_horizons).
    path : str
        Output netCDF path (default ``outputs/idata.nc``).

    Returns
    -------
    str
        The path written.
    """
    n_chain = int(idata.posterior.sizes["chain"])
    n_draw = int(idata.posterior.sizes["draw"])

    pred = np.asarray(p_event_by_horizon, dtype=float)
    if pred.ndim == 2:  # (chain*draw, H) -> (chain, draw, H)
        pred = pred.reshape(n_chain, n_draw, pred.shape[1])
    if pred.shape[:2] != (n_chain, n_draw):
        raise ValueError(
            "p_event_by_horizon must be (chain, draw, H) or (chain*draw, H); "
            f"got {pred.shape} for chain={n_chain}, draw={n_draw}"
        )
    n_h = pred.shape[2]
    hor = [float(x) for x in list(horizon_days)[:n_h]]

    da = xr.DataArray(
        pred,
        dims=["chain", "draw", "horizon"],
        coords={"horizon": list(range(n_h)), "horizon_days": ("horizon", hor)},
        name="p_event_by_horizon",
    )
    predictions = xr.Dataset({"p_event_by_horizon": da})

    # Write the parameter posterior (and other existing groups) first, then append the
    # predictions group. Appending avoids arviz/DataTree add_groups API differences and
    # the "file already open read-only" conflict from lazy loading.
    idata.to_netcdf(path)
    try:
        xr.backends.file_manager.FILE_CACHE.clear()
    except Exception:  # pragma: no cover
        pass
    predictions.to_netcdf(path, group="predictions", mode="a", engine="h5netcdf")
    return path
