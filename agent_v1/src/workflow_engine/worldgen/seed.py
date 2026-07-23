from __future__ import annotations

from workflow_engine.worldgen.constants import GENERATOR_VERSION, _hash_payload


def _derive_world_seed(batch_seed: int, instance_index: int, profile_id: str, projection_registry_id: str) -> int:
    seed_hash = _hash_payload(
        {
            "batch_seed": batch_seed,
            "instance_index": instance_index,
            "profile_id": profile_id,
            "projection_registry_id": projection_registry_id,
            "generator_version": GENERATOR_VERSION,
        }
    )
    return int(seed_hash[:16], 16) % (2**31)


def _derive_slot_seed(world_seed: int, slot_id: str, measurement_id: str) -> int:
    seed_hash = _hash_payload(
        {
            "world_seed": world_seed,
            "stage": "measurement",
            "slot_id": slot_id,
            "measurement_id": measurement_id,
            "generator_version": GENERATOR_VERSION,
        }
    )
    return int(seed_hash[:16], 16) % (2**31)
