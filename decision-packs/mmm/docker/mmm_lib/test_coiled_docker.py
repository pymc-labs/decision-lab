#!/usr/bin/env python
"""Test Coiled from inside Docker container.

Copy this to the container and run to diagnose package sync issues.
"""

import os

# Must have DASK_COILED__TOKEN set
token = os.environ.get("DASK_COILED__TOKEN")
if not token:
    print("ERROR: DASK_COILED__TOKEN not set")
    exit(1)

print(f"Token: {token[:8]}...{token[-4:]}")

import coiled


def test_pyarrow():
    """Test pyarrow sync from Docker."""
    print("\nTest: pyarrow availability on remote")
    print("-" * 40)

    @coiled.function(
        vm_type="c6i.xlarge",
        region="us-east-1",
        keepalive="5 minutes",
    )
    def remote_check():
        import sys
        result = [f"Python: {sys.version}"]

        try:
            import pyarrow
            result.append(f"pyarrow: {pyarrow.__version__}")
        except ImportError as e:
            result.append(f"pyarrow: FAILED - {e}")

        try:
            import pandas
            result.append(f"pandas: {pandas.__version__}")
        except ImportError as e:
            result.append(f"pandas: FAILED - {e}")

        try:
            import cloudpickle
            result.append(f"cloudpickle: {cloudpickle.__version__}")
        except ImportError as e:
            result.append(f"cloudpickle: FAILED - {e}")

        try:
            import pymc_marketing
            result.append(f"pymc-marketing: {pymc_marketing.__version__}")
        except ImportError as e:
            result.append(f"pymc-marketing: FAILED - {e}")

        return "\n".join(result)

    result = remote_check()
    print(result)


if __name__ == "__main__":
    test_pyarrow()
