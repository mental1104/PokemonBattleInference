"""生成和解析 1v1 后台任务使用的 canonical 配置身份。"""

from __future__ import annotations

import json
from hashlib import sha256

from pokeop.application.configuration_space.one_on_one import (
    FixedPokemonConfiguration,
    NormalizedOneOnOneConfiguration,
)
from pokeop.application.repositories.battle_inference_jobs import (
    BattleInferenceCaseDefinition,
)


def decode_one_on_one_configuration_id(
    configuration_id: str,
) -> NormalizedOneOnOneConfiguration:
    """把 v1 canonical 配置 ID 还原为 worker 可准备的固定输入。"""
    prefix = "one-on-one-configuration:"
    if not isinstance(configuration_id, str) or not configuration_id.startswith(prefix):
        raise ValueError("configuration_id must use the v1 canonical prefix")
    try:
        payload = json.loads(configuration_id[len(prefix) :])
        if not isinstance(payload, list) or len(payload) != 6:
            raise ValueError("configuration payload must contain six fields")
        contract_version, ruleset_id, version_group_id, revision, attacker, defender = payload
        return NormalizedOneOnOneConfiguration(
            contract_version=_require_text(contract_version, "contract_version"),
            ruleset_id=_require_text(ruleset_id, "ruleset_id"),
            version_group_id=_require_int(version_group_id, "version_group_id"),
            calculation_revision=_require_text(revision, "calculation_revision"),
            attacker=_decode_fixed_configuration(attacker, "attacker"),
            attacker_move_ids=_decode_move_ids(attacker, "attacker"),
            defender=_decode_fixed_configuration(defender, "defender"),
            defender_move_ids=_decode_move_ids(defender, "defender"),
        )
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise ValueError(f"invalid one-on-one configuration id: {error}") from error


def case_definition(
    configuration: NormalizedOneOnOneConfiguration,
) -> BattleInferenceCaseDefinition:
    """把规范化配置转换为 #85 轻量 case 元数据。"""
    return BattleInferenceCaseDefinition(
        configuration_pair_id=configuration.configuration_id,
        attacker_configuration_id=_side_configuration_id(
            "attacker", configuration.attacker, configuration.attacker_move_ids
        ),
        defender_configuration_id=_side_configuration_id(
            "defender", configuration.defender, configuration.defender_move_ids
        ),
        attacker_move_ids=configuration.attacker_move_ids,
        defender_move_ids=configuration.defender_move_ids,
    )


def fixed_identity(fixed: FixedPokemonConfiguration) -> list[object]:
    """返回幂等指纹使用的一侧固定配置数组。"""
    return [
        fixed.pokemon_id,
        fixed.form_id,
        fixed.level,
        fixed.stat_profile_id,
        fixed.ability_identifier,
        fixed.item_identifier,
    ]


def _side_configuration_id(
    side: str,
    fixed: FixedPokemonConfiguration,
    move_ids: tuple[int, ...],
) -> str:
    """为一侧固定配置生成紧凑稳定 SHA-256 标识。"""
    payload = json.dumps(
        [
            side,
            fixed.pokemon_id,
            fixed.form_id,
            fixed.level,
            fixed.stat_profile_id,
            fixed.ability_identifier,
            fixed.item_identifier,
            list(move_ids),
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"one-on-one-side-{sha256(payload.encode('utf-8')).hexdigest()}"


def _decode_fixed_configuration(value: object, side: str) -> FixedPokemonConfiguration:
    """从 canonical 数组还原一侧固定配置。"""
    fields = _require_side_payload(value, side)
    form_id = fields[1]
    if form_id is not None:
        form_id = _require_int(form_id, f"{side}.form_id")
    item_identifier = fields[5]
    if item_identifier is not None:
        item_identifier = _require_text(item_identifier, f"{side}.item_identifier")
    return FixedPokemonConfiguration(
        pokemon_id=_require_int(fields[0], f"{side}.pokemon_id"),
        form_id=form_id,
        level=_require_int(fields[2], f"{side}.level"),
        stat_profile_id=_require_text(fields[3], f"{side}.stat_profile_id"),
        ability_identifier=_require_text(fields[4], f"{side}.ability_identifier"),
        item_identifier=item_identifier,
    )


def _decode_move_ids(value: object, side: str) -> tuple[int, ...]:
    """从 canonical 数组还原一侧规范化技能组。"""
    fields = _require_side_payload(value, side)
    raw = fields[6]
    if not isinstance(raw, list):
        raise ValueError(f"{side}.move_ids must be an array")
    return tuple(_require_int(move_id, f"{side}.move_id") for move_id in raw)


def _require_side_payload(value: object, side: str) -> list[object]:
    """校验一侧 canonical 数组固定包含七个位置字段。"""
    if not isinstance(value, list) or len(value) != 7:
        raise ValueError(f"{side} configuration payload must contain seven fields")
    return value


def _require_text(value: object, field_name: str) -> str:
    """返回规范化非空文本，否则抛出稳定错误。"""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be non-empty and normalized")
    return value


def _require_int(value: object, field_name: str) -> int:
    """返回排除 bool 的整数，否则抛出稳定错误。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value
