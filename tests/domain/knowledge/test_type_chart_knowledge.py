import pytest

from pokeop.domain.knowledge import (
    InMemoryBattleKnowledgeProvider,
    UnknownTypeError,
    UnsupportedKnowledgeError,
)


@pytest.mark.parametrize(
    ("attacking_type", "defending_type", "expected"),
    [
        ("fire", "grass", 2.0),
        ("water", "fire", 2.0),
        ("electric", "water", 2.0),
        ("grass", "water", 2.0),
        ("ice", "dragon", 2.0),
        ("fighting", "normal", 2.0),
        ("ground", "electric", 2.0),
        ("psychic", "fighting", 2.0),
        ("bug", "psychic", 2.0),
        ("rock", "flying", 2.0),
        ("ghost", "ghost", 2.0),
        ("dragon", "dragon", 2.0),
        ("dark", "psychic", 2.0),
        ("steel", "fairy", 2.0),
        ("fairy", "dragon", 2.0),
    ],
)
def test_type_chart_returns_modern_super_effective_single_type_multiplier(
    attacking_type,
    defending_type,
    expected,
):
    """
    验证现代十八属性表中每一种代表性克制关系都能由 Knowledge 层直接回答。
    场景固定使用 xy 规则集，只传入攻击属性和单个防守属性，期望 provider 返回精确两倍倍率。
    这个测试保护完整属性表的业务契约，避免未来伤害计算器、推理器或解释器再各自维护零散样例。
    """
    provider = InMemoryBattleKnowledgeProvider()

    multiplier = provider.type_multiplier(attacking_type, (defending_type,), "xy")

    assert multiplier == expected


@pytest.mark.parametrize(
    ("attacking_type", "defending_type", "expected"),
    [
        ("fire", "water", 0.5),
        ("water", "grass", 0.5),
        ("electric", "grass", 0.5),
        ("grass", "fire", 0.5),
        ("ice", "fire", 0.5),
        ("fighting", "poison", 0.5),
        ("poison", "ground", 0.5),
        ("ground", "grass", 0.5),
        ("flying", "electric", 0.5),
        ("psychic", "steel", 0.5),
        ("bug", "fighting", 0.5),
        ("rock", "fighting", 0.5),
        ("ghost", "dark", 0.5),
        ("dragon", "steel", 0.5),
        ("dark", "fighting", 0.5),
        ("steel", "fire", 0.5),
        ("fairy", "fire", 0.5),
    ],
)
def test_type_chart_returns_modern_resisted_single_type_multiplier(
    attacking_type,
    defending_type,
    expected,
):
    """
    验证现代十八属性表中典型抵抗关系会返回半倍倍率，而不是被缺省成一倍。
    场景覆盖火水草电冰格斗毒地飞超虫岩幽灵龙恶钢妖精等攻击属性的抵抗样本。
    这个测试让 Knowledge 层承担完整相性知识，保护上层计算逻辑只消费倍率结果而不复制规则表。
    """
    provider = InMemoryBattleKnowledgeProvider()

    multiplier = provider.type_multiplier(attacking_type, (defending_type,), "xy")

    assert multiplier == expected


@pytest.mark.parametrize(
    ("attacking_type", "defending_type", "expected"),
    [
        ("normal", "ghost", 0.0),
        ("fighting", "ghost", 0.0),
        ("poison", "steel", 0.0),
        ("ground", "flying", 0.0),
        ("ghost", "normal", 0.0),
        ("electric", "ground", 0.0),
        ("psychic", "dark", 0.0),
        ("dragon", "fairy", 0.0),
    ],
)
def test_type_chart_returns_modern_immune_single_type_multiplier(
    attacking_type,
    defending_type,
    expected,
):
    """
    验证现代属性免疫关系会返回零倍率，并且免疫优先于普通一倍或其他缺省处理。
    场景覆盖普通打幽灵、格斗打幽灵、毒打钢、地面打飞行、幽灵打普通、电打地面、
    超能打恶和龙打妖精。这个测试保护未来双属性相乘时零倍率能够自然传播成最终无效。
    """
    provider = InMemoryBattleKnowledgeProvider()

    multiplier = provider.type_multiplier(attacking_type, (defending_type,), "xy")

    assert multiplier == expected


@pytest.mark.parametrize(
    ("attacking_type", "defending_types", "expected"),
    [
        ("fire", ("bug", "steel"), 4.0),
        ("water", ("dragon", "ground"), 1.0),
        ("electric", ("water", "flying"), 4.0),
        ("ground", ("flying", "steel"), 0.0),
        ("ice", ("dragon", "ground"), 4.0),
        ("fighting", ("ghost", "dark"), 0.0),
        ("fairy", ("dragon", "dark"), 4.0),
    ],
)
def test_type_chart_multiplies_single_matchups_for_dual_type_defenders(
    attacking_type,
    defending_types,
    expected,
):
    """
    验证防守方为双属性时，Knowledge 层会逐个查询单属性相性并把倍率相乘得到总倍率。
    场景覆盖四倍、普通一倍、免疫归零等常见组合，包括火打虫钢、电打水飞、地面打飞钢、
    冰打龙地、格斗打幽恶和妖精打龙恶。这个契约让未来伤害计算只依赖一个确定的总倍率。
    """
    provider = InMemoryBattleKnowledgeProvider()

    multiplier = provider.type_multiplier(attacking_type, defending_types, "xy")

    assert multiplier == expected


@pytest.mark.parametrize("attacking_type", ["Fire", "fire", "FIRE"])
def test_type_chart_canonicalizes_type_identifiers_before_lookup(attacking_type):
    """
    验证属性倍率查询会先规范化输入标识，再进入已知属性和规则集可用性校验。
    场景分别使用 Fire、fire 和 FIRE 作为攻击属性，并用大小写混合的 Grass 作为防守属性，
    期望都得到火克草的两倍倍率。这个测试保护用户输入、外部文件名和未来接口参数的大小写差异。
    """
    provider = InMemoryBattleKnowledgeProvider()

    multiplier = provider.type_multiplier(attacking_type, ("Grass",), "xy")

    assert multiplier == 2.0


@pytest.mark.parametrize(
    ("attacking_type", "defending_type", "ruleset", "expected"),
    [
        ("ghost", "steel", "bw", 0.5),
        ("dark", "steel", "bw", 0.5),
        ("ghost", "steel", "xy", 1.0),
        ("dark", "steel", "xy", 1.0),
    ],
)
def test_type_chart_applies_generation_specific_steel_resistance_changes(
    attacking_type,
    defending_type,
    ruleset,
    expected,
):
    """
    验证第五世代和第六世代之后围绕钢属性抵抗关系的差异会被规则集显式选择。
    场景比较 bw 与 xy 中幽灵打钢、恶打钢的结果，bw 保持半倍抵抗，xy 返回现代一倍中性。
    这个测试保护规则集上下文不被伤害公式硬编码，也避免以后新增 sv 等规则集时回退到旧世代。
    """
    provider = InMemoryBattleKnowledgeProvider()

    multiplier = provider.type_multiplier(attacking_type, (defending_type,), ruleset)

    assert multiplier == expected


@pytest.mark.parametrize(
    ("ruleset", "attacking_type", "defending_type", "expected"),
    [
        ("xy", "fairy", "dragon", 2.0),
        ("sv", "fairy", "dragon", 2.0),
        ("xy", "dragon", "fairy", 0.0),
        ("sv", "dragon", "fairy", 0.0),
        ("sv", "dark", "steel", 1.0),
    ],
)
def test_type_chart_uses_modern_matchups_for_xy_and_sv_rulesets(
    ruleset,
    attacking_type,
    defending_type,
    expected,
):
    """
    验证第六世代之后的多个规则集会共享现代属性表，而不是只在 xy 样例中偶然生效。
    场景比较 xy 与 sv 中妖精克龙、龙打妖精无效，并额外确认 sv 中恶打钢是一倍中性。
    这个测试保护未来新增规则集时的分支语义：第五世代以前走旧钢抵抗，六代以后走现代十八属性。
    """
    provider = InMemoryBattleKnowledgeProvider()

    multiplier = provider.type_multiplier(attacking_type, (defending_type,), ruleset)

    assert multiplier == expected


@pytest.mark.parametrize(
    ("attacking_type", "defending_types"),
    [
        ("fairy", ("dragon",)),
        ("dragon", ("fairy",)),
    ],
)
def test_type_chart_rejects_fairy_matchups_in_bw_ruleset(
    attacking_type,
    defending_types,
):
    """
    验证妖精属性在全局词汇中属于已知属性，但在 bw 规则集中仍然不可用于属性表查询。
    场景分别覆盖妖精攻击龙和龙攻击妖精，二者在现代规则中都有明确倍率，但第五世代没有妖精属性。
    这个测试保护 UnknownTypeError 与 UnsupportedKnowledgeError 的边界，让跨世代调用方能区分问题。
    """
    provider = InMemoryBattleKnowledgeProvider()

    with pytest.raises(UnsupportedKnowledgeError):
        provider.type_multiplier(attacking_type, defending_types, "bw")


def test_type_chart_rejects_unknown_attacking_and_defending_types():
    """
    验证属性表遇到完全未知的攻击或防守属性时会抛出 UnknownTypeError，而不是返回中性倍率。
    场景使用 sound 作为攻击属性、crystal 作为防守属性，并且都放在有效 xy 规则集中触发校验。
    这个测试保护拼写错误和未纳入领域词汇的新概念不会被静默接受，保持 Knowledge 契约可诊断。
    """
    provider = InMemoryBattleKnowledgeProvider()

    with pytest.raises(UnknownTypeError):
        provider.type_multiplier("sound", ("steel",), "xy")
    with pytest.raises(UnknownTypeError):
        provider.type_multiplier("steel", ("crystal",), "xy")


@pytest.mark.parametrize(
    "defending_types",
    [
        (),
        ("fire", "water", "grass"),
    ],
)
def test_type_chart_rejects_invalid_defending_type_counts(defending_types):
    """
    验证属性倍率接口只接受真实对战中存在的一到两个防守属性，空集合或三属性组合都不可计算。
    场景分别传入空 tuple 和三个合法属性，期望得到 UnsupportedKnowledgeError 而不是未知属性错误。
    这个测试保护调用方必须先构造完整且符合宝可梦规则的类型快照，再请求 Knowledge 层回答倍率。
    """
    provider = InMemoryBattleKnowledgeProvider()

    with pytest.raises(UnsupportedKnowledgeError):
        provider.type_multiplier("steel", defending_types, "xy")
