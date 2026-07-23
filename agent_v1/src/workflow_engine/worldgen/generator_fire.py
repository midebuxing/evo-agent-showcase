"""Worldgen generator — 消防子域 surrogate helper（spec 06 §7）.

从 generator.py 拆出（纯代码重组，零改行为）。消防缺陷分值 / 缺陷在否 / 严重度派生。

依赖底座（generator_base）：_sigmoid。
fire_component_class 查表 `_lookup_fire_component_class_from_component_type` 留在底座层。
"""

from __future__ import annotations

from typing import Dict

from workflow_engine.worldgen.models import DriverState
from workflow_engine.worldgen.generator_base import _sigmoid


def _compute_fire_deficiency_score(driver: DriverState) -> float:
    """spec 06 §7 deficiency_score = sigmoid(1.0*fire_safety_deficit + 0.7*maintenance - 0.7)."""
    raw = (
        1.0 * driver.fire_safety_deficit_index
        + 0.7 * driver.maintenance_deficit_index
        - 0.7
    )
    return _sigmoid(raw)


def _is_fire_deficiency_present(deficiency_score: float) -> bool:
    """spec 06 §7 deficiency_present = (deficiency_score > 0.45)."""
    return deficiency_score > 0.45


_FIRE_COMPONENT_IMPORTANCE_WEIGHTS: Dict[str, float] = {
    "escape_route": 1.0,
    "fire_door": 0.9,
    "fire_resisting_wall": 0.9,
    "smoke_vent": 0.85,
    "fire_service_installation": 0.85,
    "unknown_fire_component": 0.7,
}


def _compute_fire_severity_index(
    deficiency_score: float, fire_component_class: str
) -> float:
    """spec 06 §7 severity_index = deficiency_score * component_importance_weight."""
    weight = _FIRE_COMPONENT_IMPORTANCE_WEIGHTS.get(fire_component_class, 0.7)
    return max(0.0, min(1.0, deficiency_score * weight))
