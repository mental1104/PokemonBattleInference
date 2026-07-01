import pytest

from pokeop.domain.knowledge import (
    InMemoryBattleKnowledgeProvider,
    UnknownMoveError,
    UnknownPokemonError,
    UnknownRulesetError,
    UnknownTypeError,
    UnsupportedKnowledgeError,
)


def test_unknown_ruleset_raises_specific_ruleset_error():
    """
    验证规则集标识无法识别时会抛出 UnknownRulesetError，而不是返回空对象或落到默认世代。
    场景查询当前内存样本没有覆盖的 oras，期望调用方立即得到明确失败原因。
    这个契约能保护未来 application 层在编排查询前先确认规则上下文，避免把错误规则集继续传入
    宝可梦、招式、属性表或学习面逻辑后产生更难定位的派生错误。
    """
    provider = InMemoryBattleKnowledgeProvider()

    with pytest.raises(UnknownRulesetError):
        provider.get_ruleset("oras")


def test_unknown_pokemon_and_move_raise_specific_lookup_errors():
    """
    验证宝可梦和招式标识不存在时分别使用对应的自定义异常。
    场景在有效 xy 规则集中查询不存在的宝可梦 missingno 和不存在的招式 light-that-burns，
    期望 UnknownPokemonError 与 UnknownMoveError 能被调用方区分捕获。
    这个测试保护 Knowledge 查询接口的错误语义，不让上层只能依赖字符串消息判断问题类型。
    """
    provider = InMemoryBattleKnowledgeProvider()

    with pytest.raises(UnknownPokemonError):
        provider.get_pokemon("missingno", "xy")
    with pytest.raises(UnknownMoveError):
        provider.get_move("light-that-burns", "xy")


def test_unknown_type_raises_specific_type_error():
    """
    验证属性表查询遇到完全未知的属性标识时会抛出 UnknownTypeError。
    场景使用 sound 作为攻击属性、steel 作为防守属性并指定有效 xy 规则集，
    因为 sound 不属于当前 Knowledge 契约支持的宝可梦属性集合，所以不能被当作中性一倍处理。
    该测试保护属性标识校验边界，避免未来输入拼写错误时被静默吞掉。
    """
    provider = InMemoryBattleKnowledgeProvider()

    with pytest.raises(UnknownTypeError):
        provider.type_multiplier("sound", ("steel",), "xy")


def test_fairy_type_is_unsupported_in_bw_for_chart_pokemon_and_moves():
    """
    验证妖精属性虽然是全局已知属性，但在第五世代 bw 规则集中不可用。
    场景分别从属性表、宝可梦资料和招式资料三个入口触发 fairy：钢打妖精、
    查询仙子伊布、查询月亮之力，期望都抛出 UnsupportedKnowledgeError。
    这个测试把“已知但规则集不支持”和“完全未知”区分开，为未来跨世代真实数据实现保留清晰契约。
    """
    provider = InMemoryBattleKnowledgeProvider()

    with pytest.raises(UnsupportedKnowledgeError):
        provider.type_multiplier("steel", ("fairy",), "bw")
    with pytest.raises(UnsupportedKnowledgeError):
        provider.get_pokemon("sylveon", "bw")
    with pytest.raises(UnsupportedKnowledgeError):
        provider.get_move("moonblast", "bw")


def test_invalid_defending_type_count_raises_unsupported_knowledge_error():
    """
    验证属性倍率接口只接受单属性或双属性防守方，遇到空属性列表时给出明确的能力不支持错误。
    当前 Knowledge 契约服务的是宝可梦对战中真实存在的一到两个防守属性，
    因此空 tuple 不应该被解释为一倍，也不应该冒充未知属性。这个边界让调用方在组装查询参数时
    能尽早发现缺失数据，并保持 domain 层行为独立于数据库或外部数据源。
    """
    provider = InMemoryBattleKnowledgeProvider()

    with pytest.raises(UnsupportedKnowledgeError):
        provider.type_multiplier("steel", (), "xy")
