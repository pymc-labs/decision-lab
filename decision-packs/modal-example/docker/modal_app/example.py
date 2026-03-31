"""
Example Modal app for serverless cloud execution.

Deploy with: modal deploy example.py

Cache Busting
-------------
Modal caches images by their definition. If you change only the Python code
(not the package list), Modal won't rebuild the image. The self-hash trick
below forces a rebuild whenever this file changes.

Package Versions
----------------
If you use cloudpickle to send objects between the Docker container and Modal,
package versions here MUST match the Dockerfile. Otherwise unpickling will fail.
"""

import hashlib
from pathlib import Path

import modal

# Hash this file to force image rebuild when code changes.
# Without this, Modal uses a cached image even when the code is different.
_modal_app_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]

# Conda packages — use micromamba for properly linked BLAS, MKL, etc.
CONDA_PACKAGES = [
    "python=3.11",
    # Add your conda packages here
    # "numpy",
    # "pandas",
]

# Packages that need pip (not on conda-forge or need specific versions)
PIP_PACKAGES = [
    # "some-pip-only-package",
]

image = (
    modal.Image.micromamba(python_version="3.11")
    .run_commands(f"echo 'modal_app hash: {_modal_app_hash}'")  # Cache buster
    .micromamba_install(*CONDA_PACKAGES, channels=["conda-forge"])
    .pip_install(*PIP_PACKAGES)
)

app = modal.App("modal-example-compute")


@app.function(image=image, timeout=3600)
def run_compute(data: dict) -> dict:
    """Example compute function. Replace with your own logic."""
    return {"status": "done", "input_keys": list(data.keys())}
