"""
Refresh the bundled model catalog (dlab/data/models.json) from models.dev.

Run before each release so the bundled baseline stays close to opencode's
live catalog (see issue #91 for the runtime TTL-cache layer on top):

    python scripts/refresh_models_json.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dlab.create_dpack import fetch_models_from_api  # noqa: E402


def main() -> None:
    bundle_path: Path = REPO_ROOT / "dlab" / "data" / "models.json"
    old: dict = json.loads(bundle_path.read_text())
    new: dict = fetch_models_from_api()

    if not new.get("models") or not new.get("provider_envs"):
        raise SystemExit("models.dev fetch returned no data — bundle left unchanged")

    with open(bundle_path, "w") as f:
        json.dump(new, f, indent=2)
        f.write("\n")

    added: int = len(set(new["models"]) - set(old["models"]))
    removed: int = len(set(old["models"]) - set(new["models"]))
    print(
        f"models.json refreshed: {len(old['models'])} -> {len(new['models'])} "
        f"models (+{added}/-{removed}), "
        f"{len(new['provider_envs'])} providers"
    )


if __name__ == "__main__":
    main()
