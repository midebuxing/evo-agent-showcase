"""Worldgen generator — 违建（UBW）子域 surrogate helper（spec 06 §6）.

从 generator.py 拆出（纯代码重组，零改行为）。3 个 UBW index 公式派生：
改建分值 / 分契单元标识 / 结构影响。

依赖底座（generator_base）：_sigmoid。
"""

from __future__ import annotations

from typing import Optional

from workflow_engine.worldgen.models import ComponentNode, DriverState, LocationNode
from workflow_engine.worldgen.generator_base import _sigmoid


def _compute_ubw_alteration_score(driver: DriverState) -> float:
    """spec 06 §6 alteration_score = sigmoid(1.2*alteration + 0.5*workmanship + 0.4*maintenance - 0.8)."""
    raw = (
        1.2 * driver.alteration_propensity
        + 0.5 * driver.workmanship_deficit_index
        + 0.4 * driver.maintenance_deficit_index
        - 0.8
    )
    return _sigmoid(raw)


def _compute_ubw_subdivided_unit_sign_present(
    location: Optional[LocationNode],
    alteration_type: str,
    alteration_score: float,
) -> bool:
    """spec 06 §6 subdivided_unit_sign_present =
    (location has private_premises) AND (alteration_type == subdivision) AND (alteration_score > 0.45).
    """
    if location is None:
        return False
    has_private = "private_premises" in (location.spatial_tags or [])
    is_subdivision = alteration_type == "subdivision"
    return has_private and is_subdivision and alteration_score > 0.45


def _compute_ubw_structural_impact_index(
    alteration_score: float,
    component: ComponentNode,
) -> float:
    """spec 06 §6 structural_impact_index = clip(0.6*alteration + 0.3*(load_bearing), 0, 1).

    component.structural_role ∈ {primary_load_bearing, secondary_load_bearing} → 视为 load-bearing.
    """
    is_load_bearing = component.structural_role in (
        "primary_load_bearing", "secondary_load_bearing",
    )
    raw = 0.6 * alteration_score + 0.3 * (1.0 if is_load_bearing else 0.0)
    return max(0.0, min(1.0, raw))
