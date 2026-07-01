from pokeop.domain.knowledge import InMemoryBattleKnowledgeProvider


def test_move_lookup_normalizes_case_space_and_underscore_variants():
    """
    验证招式查询对大小写、空格、下划线和连字符保持统一归一化行为。
    场景分别用 Bullet Punch、bullet_punch、bullet-punch 查询同一个招式，
    期望得到相同的规范 identifier、钢属性、物理分类、威力、命中和先制度。
    这个契约让上层用例可以接受用户输入或外部数据中的常见写法差异，而不用知道内存表如何组织。
    """
    provider = InMemoryBattleKnowledgeProvider()

    by_space = provider.get_move("Bullet Punch", "xy")
    by_underscore = provider.get_move("bullet_punch", "xy")
    by_hyphen = provider.get_move("bullet-punch", "xy")

    assert by_space == by_underscore == by_hyphen
    assert by_space.identifier == "bullet-punch"
    assert by_space.type == "steel"
    assert by_space.damage_class == "physical"
    assert by_space.power == 40
    assert by_space.accuracy == 100
    assert by_space.priority == 1


def test_status_move_keeps_missing_power_and_accuracy_as_none():
    """
    验证变化类招式不会被迫填充不存在的威力或命中数值。
    场景查询剑舞这个代表性 status 招式，期望 damage_class 为 status，
    power 与 accuracy 都保持 None，priority 为普通先制度。这个测试保护 Knowledge
    模型对缺失战斗字段的表达能力，避免未来接入真实数据时把空值错误转换成零或其他哨兵值。
    """
    provider = InMemoryBattleKnowledgeProvider()

    swords_dance = provider.get_move("Swords Dance", "xy")

    assert swords_dance.identifier == "swords-dance"
    assert swords_dance.type == "normal"
    assert swords_dance.damage_class == "status"
    assert swords_dance.power is None
    assert swords_dance.accuracy is None
    assert swords_dance.priority == 0
