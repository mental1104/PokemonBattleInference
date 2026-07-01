import pytest

from pokeop.domain.knowledge import InMemoryBattleKnowledgeProvider


@pytest.mark.parametrize(
    ("pokemon", "move", "ruleset"),
    [
        ("Scizor", "Bullet Punch", "xy"),
        ("scizor", "swords_dance", "xy"),
        ("Sylveon", "Moonblast", "xy"),
        ("Garchomp", "Earthquake", "sv"),
        ("Gengar", "Shadow Ball", "xy"),
    ],
)
def test_known_learnset_pairs_return_true_with_normalized_identifiers(
    pokemon,
    move,
    ruleset,
):
    """
    验证学习面查询能回答未来构队、招式合法性和对战推理都会依赖的基础问题。
    场景覆盖巨钳螳螂学习子弹拳与剑舞、仙子伊布学习月亮之力、烈咬陆鲨在 sv 学地震、
    耿鬼在 xy 学暗影球，并刻意混用大小写、空格和下划线。测试只断言公开布尔结果，
    不把内存样本的组织方式暴露给测试用例或上层业务。
    """
    provider = InMemoryBattleKnowledgeProvider()

    assert provider.can_learn_move(pokemon, move, ruleset) is True


def test_unlisted_learnset_pair_returns_false_after_valid_lookup():
    """
    验证当宝可梦、招式和规则集本身都有效，但学习面关系不存在时，provider 返回 False
    而不是抛出未知错误。场景使用巨钳螳螂和月亮之力，两者都能在 xy 规则集中被识别，
    但样本契约明确巨钳螳螂不可学习该招式。这个边界对未来合法性检查很重要，
    因为不存在的学习关系和不存在的数据标识需要被上层区别处理。
    """
    provider = InMemoryBattleKnowledgeProvider()

    assert provider.can_learn_move("scizor", "moonblast", "xy") is False
