"""Model configuration serialization utilities.

Functions for saving and loading MMM configuration to/from YAML,
including Prior object serialization and adstock/saturation transformations.
"""

import yaml
from typing import Any, Optional

import numpy as np
from pymc_extras.prior import Prior
from pymc_marketing.mmm.components.adstock import AdstockTransformation
from pymc_marketing.mmm.components.saturation import SaturationTransformation
from pymc_marketing.mmm import GeometricAdstock, LogisticSaturation


def _to_python_native(value: Any) -> Any:
    """Convert numpy types to Python native types for YAML serialization."""
    if isinstance(value, np.ndarray):
        return value.tolist()
    elif isinstance(value, np.integer):
        return int(value)
    elif isinstance(value, np.floating):
        return float(value)
    elif isinstance(value, np.bool_):
        return bool(value)
    elif isinstance(value, dict):
        return {k: _to_python_native(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [_to_python_native(v) for v in value]
    else:
        return value


def prior_to_dict(prior: Prior) -> dict[str, Any]:
    """Convert Prior to serializable dict.

    Parameters
    ----------
    prior : Prior
        PyMC-Marketing Prior object.

    Returns
    -------
    dict[str, Any]
        Dictionary with 'dist' and 'kwargs' keys.
    """
    # Use Prior's built-in to_dict() method which returns {'dist': ..., 'kwargs': ...}
    return prior.to_dict()


def dict_to_prior(d: dict[str, Any]) -> Prior:
    """Reconstruct Prior from dict, including nested priors (hyperpriors).

    Parameters
    ----------
    d : dict[str, Any]
        Dictionary with 'dist' and 'kwargs' keys.

    Returns
    -------
    Prior
        Reconstructed Prior object.
    """
    dist = d["dist"]
    kwargs = d.get("kwargs", {})

    # Recursively convert any nested priors in kwargs
    reconstructed_kwargs = {}
    for key, value in kwargs.items():
        if isinstance(value, dict) and "dist" in value:
            # This is a nested prior (hyperprior)
            reconstructed_kwargs[key] = dict_to_prior(value)
        else:
            reconstructed_kwargs[key] = value

    return Prior(dist, **reconstructed_kwargs)


def _is_prior_dict(d: dict) -> bool:
    """Check if a dict represents a serialized Prior."""
    return isinstance(d, dict) and "dist" in d and ("kwargs" in d or any(
        k not in ("dist", "dims", "_type") for k in d.keys()
    ))


def _reconstruct_priors_in_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Recursively reconstruct Prior objects from dicts in a nested structure."""
    result = {}
    for key, value in d.items():
        if key == "_type":
            continue
        if isinstance(value, dict):
            if _is_prior_dict(value):
                # This looks like a Prior dict
                result[key] = dict_to_prior(value)
            else:
                # Recurse into the dict
                result[key] = _reconstruct_priors_in_dict(value)
        elif isinstance(value, list):
            result[key] = [
                dict_to_prior(v) if isinstance(v, dict) and _is_prior_dict(v)
                else _reconstruct_priors_in_dict(v) if isinstance(v, dict)
                else v
                for v in value
            ]
        else:
            result[key] = value
    return result


def _serialize_config_value(value: Any) -> Any:
    """Recursively serialize config values, converting Priors to dicts.

    Also converts numpy types to Python native types for YAML compatibility.
    """
    if isinstance(value, Prior):
        prior_dict = prior_to_dict(value)
        prior_dict = _to_python_native(prior_dict)
        return {"_type": "Prior", **prior_dict}
    elif isinstance(value, AdstockTransformation):
        return {"_type": "Adstock", **_to_python_native(value.to_dict())}
    elif isinstance(value, SaturationTransformation):
        return {"_type": "Saturation", **_to_python_native(value.to_dict())}
    elif isinstance(value, dict):
        return {k: _serialize_config_value(v) for k, v in value.items()}
    elif isinstance(value, (list, tuple)):
        return [_serialize_config_value(v) for v in value]
    elif isinstance(value, (np.ndarray, np.integer, np.floating, np.bool_)):
        return _to_python_native(value)
    else:
        return value


def _deserialize_adstock(d: dict[str, Any]) -> AdstockTransformation:
    """Reconstruct Adstock from dict, handling nested priors."""
    adstock_type = d.get("type", "GeometricAdstock")
    l_max = d.get("l_max", 8)
    priors = d.get("priors", {})

    # Reconstruct all priors (including nested hyperpriors)
    reconstructed_priors = _reconstruct_priors_in_dict(priors)

    if adstock_type == "GeometricAdstock":
        return GeometricAdstock(l_max=l_max, priors=reconstructed_priors)
    else:
        raise ValueError(f"Unknown adstock type: {adstock_type}")


def _deserialize_saturation(d: dict[str, Any]) -> SaturationTransformation:
    """Reconstruct Saturation from dict, handling nested priors."""
    sat_type = d.get("type", "LogisticSaturation")
    priors = d.get("priors", {})

    # Reconstruct all priors (including nested hyperpriors)
    reconstructed_priors = _reconstruct_priors_in_dict(priors)

    if sat_type == "LogisticSaturation":
        return LogisticSaturation(priors=reconstructed_priors)
    else:
        raise ValueError(f"Unknown saturation type: {sat_type}")


def _deserialize_config_value(value: Any) -> Any:
    """Recursively deserialize config values, reconstructing Priors/Adstock/Saturation."""
    if isinstance(value, dict):
        type_marker = value.get("_type")
        if type_marker == "Prior":
            return dict_to_prior({"dist": value["dist"], "kwargs": value.get("kwargs", {})})
        elif type_marker == "Adstock":
            return _deserialize_adstock(value)
        elif type_marker == "Saturation":
            return _deserialize_saturation(value)
        else:
            return {k: _deserialize_config_value(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_deserialize_config_value(v) for v in value]
    else:
        return value


def save_model_config(
    model_config: dict[str, Any],
    sampler_config: dict[str, Any],
    data_config: dict[str, Any],
    filepath: str,
    adstock: Optional[AdstockTransformation] = None,
    saturation: Optional[SaturationTransformation] = None,
    model_type: str = "MMM",
) -> str:
    """Save model configuration to YAML.

    Parameters
    ----------
    model_config : dict
        MMM model_config with Prior objects.
    sampler_config : dict
        Sampler settings (draws, tune, chains, target_accept).
    data_config : dict
        Data column specifications (date_column, channel_columns, etc.).
        For MMM with dims, should include 'dim_column' and 'dims'.
    filepath : str
        Output YAML path.
    adstock : AdstockTransformation, optional
        Configured adstock transformation with priors.
    saturation : SaturationTransformation, optional
        Configured saturation transformation with priors.
    model_type : str
        "MMM" for single time series, "MMM" with dims for panel data.

    Returns
    -------
    str
        Path to saved file.
    """
    bundle = {
        "model_type": model_type,
        "model_config": _serialize_config_value(model_config),
        "sampler_config": sampler_config,
        "data_config": data_config,
        "version": "1.1",
    }

    if adstock is not None:
        bundle["adstock"] = _serialize_config_value(adstock)
    if saturation is not None:
        bundle["saturation"] = _serialize_config_value(saturation)

    with open(filepath, "w") as f:
        yaml.dump(bundle, f, default_flow_style=False, sort_keys=False)

    return filepath


def load_model_config(filepath: str) -> dict[str, Any]:
    """Load model configuration from YAML.

    Parameters
    ----------
    filepath : str
        Path to YAML config file.

    Returns
    -------
    dict[str, Any]
        Dictionary with keys:
        - model_config: dict with Prior objects
        - sampler_config: dict
        - data_config: dict
        - model_type: str ("MMM")
        - adstock: AdstockTransformation (if present)
        - saturation: SaturationTransformation (if present)
    """
    with open(filepath, "r") as f:
        bundle = yaml.safe_load(f)

    result = {
        "model_config": _deserialize_config_value(bundle.get("model_config", {})),
        "sampler_config": bundle.get("sampler_config", {}),
        "data_config": bundle.get("data_config", {}),
        "model_type": bundle.get("model_type", "MMM"),
    }

    if "adstock" in bundle:
        result["adstock"] = _deserialize_config_value(bundle["adstock"])
    if "saturation" in bundle:
        result["saturation"] = _deserialize_config_value(bundle["saturation"])

    return result
