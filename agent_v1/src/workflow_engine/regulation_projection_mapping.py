from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

RUNTIME_MAPPING_FILENAME = "projection_runtime_mapping_v1.json"


def runtime_mapping_path(bundle_dir: Path) -> Path:
    return Path(bundle_dir) / RUNTIME_MAPPING_FILENAME


def load_runtime_mapping(bundle_dir: Path) -> Dict[str, Any]:
    path = runtime_mapping_path(bundle_dir)
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    payload["mapping_path"] = str(path)
    return payload
