# SPDX-FileCopyrightText: 2026 Justin Stanley
# SPDX-License-Identifier: MIT
import json
from pathlib import Path

from impsolver.cli import SCHEMAS

ROOT = Path(__file__).resolve().parents[1] / "schemas"


def test_committed_schemas_match_models() -> None:
    for name, cls in SCHEMAS.items():
        committed = json.loads((ROOT / f"{name}.schema.json").read_text())
        assert committed == cls.model_json_schema(), (
            f"schemas/{name}.schema.json is stale; run `impsolver schema --out schemas`"
        )
