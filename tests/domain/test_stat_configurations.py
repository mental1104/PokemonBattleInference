"""配置预设领域规则测试。"""

from __future__ import annotations

import pytest

from pokeop.domain.battle.stats import StatValues, calculate_actual_stats
from pokeop.domain.configuration_presets import (
    PokemonBindingKind,
    StatConfiguration,
    StatConfigurationRole,
    StatConfigurationSource,
    StatSpread,
    stat_profile_from_snapshot,
)


def test_ev_and_iv_boundaries_are_enforced() -> None:
    """
    配置预设的 EV/IV 是伤害计算和固定推演共同依赖的领域输入，不能只依赖前端表单。
    本测试覆盖 EV 单项 0 与 252、总和 510 的合法边界，以及单项 253、总和 511、
    IV 32 等非法输入，保护 application 和 API 即使收到伪造请求也不会生成非法
    StatProfile。
    """
    StatSpread.evs(hp=252, attack=252, speed=6)
    StatSpread.ivs(hp=0, attack=31, defense=31, special_attack=31, special_defense=31, speed=31)

    with pytest.raises(ValueError, match="between 0 and 252"):
        StatSpread.evs(attack=253)
    with pytest.raises(ValueError, match="total EVs"):
        StatSpread.evs(hp=252, attack=252, defense=7)
    with pytest.raises(ValueError, match="between 0 and 31"):
        StatSpread.ivs(hp=32)


def test_configuration_matching_and_snapshot_affect_stats() -> None:
    """
    Pokémon 专属配置只能匹配绑定的 pokemon_id，且 attacker/defender/both 角色过滤必须
    在领域层可复用。测试还把配置编码成计算快照再解析为 StatProfile，断言 nature、EV
    和 IV 会实际改变最终能力值，而不是只成为 UI 或 CRUD 字段。
    """
    config = StatConfiguration(
        key="scizor-fast",
        source=StatConfigurationSource.CUSTOM,
        name="Scizor Fast",
        nature_id="jolly",
        evs=StatSpread.evs(attack=252, speed=252, hp=4),
        ivs=StatSpread.perfect_ivs(),
        role=StatConfigurationRole.BOTH,
        binding_kind=PokemonBindingKind.POKEMON,
        pokemon_id=212,
    )

    assert config.applies_to(pokemon_id=212, role=StatConfigurationRole.ATTACKER)
    assert config.applies_to(pokemon_id=212, role=StatConfigurationRole.DEFENDER)
    assert not config.applies_to(pokemon_id=700, role=StatConfigurationRole.ATTACKER)

    profile = stat_profile_from_snapshot(
        config.snapshot_profile_id(),
        StatValues(hp=70, attack=130, defense=100, special_attack=55, special_defense=80, speed=65),
    )
    assert profile is not None
    stats = calculate_actual_stats(profile, level=50)
    assert stats.attack == 182
    assert stats.speed == 128
