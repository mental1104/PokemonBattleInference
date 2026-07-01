from pokeop.domain.knowledge import (
    BaseStats,
    InMemoryBattleKnowledgeProvider,
)


def test_ruleset_lookup_returns_generation_metadata_with_normalized_identifier():
    """
    验证 Knowledge 层能够按规则集标识返回未来查询服务需要的世代上下文。
    场景只读取内存样本，不依赖数据库、CSV、PokeAPI 或 repository；输入使用大小写不同的
    bw 标识，期望输出仍归一到稳定 identifier，并暴露 generation 与 version_group，
    从而保护后续宝可梦、招式、属性表和学习面查询都能共享同一个规则集契约。
    """
    provider = InMemoryBattleKnowledgeProvider()

    ruleset = provider.get_ruleset("BW")

    assert ruleset.identifier == "bw"
    assert ruleset.generation == 5
    assert ruleset.version_group == "black-white"


def test_pokemon_lookup_returns_typing_and_base_stats_without_persistence():
    """
    验证 Knowledge 层能返回对战计算最基础的宝可梦资料快照，包括规范化 identifier、
    展示名、单属性或双属性，以及六项种族值。测试使用巨钳螳螂这个双属性样本，
    只关心公开返回模型的业务含义，不检查内存实现里的存储结构，确保本层先形成稳定契约，
    以后替换成数据库或外部数据源时仍需满足同样的查询行为。
    """
    provider = InMemoryBattleKnowledgeProvider()

    scizor = provider.get_pokemon("SCIZOR", "xy")

    assert scizor.identifier == "scizor"
    assert scizor.display_name == "Scizor"
    assert scizor.types == ("bug", "steel")
    assert scizor.base_stats == BaseStats(
        hp=70,
        attack=130,
        defense=100,
        special_attack=55,
        special_defense=80,
        speed=65,
    )


def test_fairy_pokemon_is_available_after_generation_six_rulesets():
    """
    验证第六世代之后引入的妖精属性宝可梦可以在对应规则集中被正常查询。
    场景使用仙子伊布和 sv 规则集，期望 provider 返回 fairy 单属性和完整种族值；
    这个测试描述的是规则集感知能力，而不是物种来源，因此不允许通过读取 CSV 或数据库来完成，
    后续真实数据实现也必须保持同样的 domain 层输入输出边界。
    """
    provider = InMemoryBattleKnowledgeProvider()

    sylveon = provider.get_pokemon("Sylveon", "sv")

    assert sylveon.identifier == "sylveon"
    assert sylveon.types == ("fairy",)
    assert sylveon.base_stats.special_attack == 110
    assert sylveon.base_stats.special_defense == 130
