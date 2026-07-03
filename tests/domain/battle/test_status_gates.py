from pokeop.domain.battle.flow.action_gate import (
    ActionDecision,
    default_action_gate_pipeline,
)
from pokeop.domain.battle.rulesets.profiles import BattleRulesetProfile
from pokeop.domain.battle.status.gates import (
    ConfusionGate,
    FreezeGate,
    InfatuationGate,
    ParalysisGate,
    SleepGate,
)
from pokeop.domain.battle.status.state import SleepStatus
from tests.domain.battle.helpers import (
    CombatantStatusFactory,
    FixedBattleRandom,
    MoveProfileFactory,
)


def _gen9_ruleset():
    return BattleRulesetProfile.GEN9.build()


def test_sleep_gate_blocks_when_combatant_does_not_wake_up():
    """
    验证睡眠状态在本回合没有醒来时会阻止行动。本用例通过固定随机数让睡眠策略返回未醒结果，然后检查
    SleepGate 是否返回 BLOCK、原因是否为 sleep，并确认睡眠回合计数被推进。这个测试保护出招前状态阻断链的
    第一层语义：睡眠未解除时原招式不能继续执行，但状态对象必须以不可变方式返回更新后的新快照。
    """
    status = CombatantStatusFactory.sleeping()
    rng = FixedBattleRandom([False])

    result = SleepGate().check_before_action(
        status=status,
        move=MoveProfileFactory.physical(),
        ruleset=_gen9_ruleset(),
        rng=rng,
    )

    assert result.decision is ActionDecision.BLOCK
    assert result.reason == "sleep"
    assert isinstance(result.updated_status.non_volatile, SleepStatus)
    assert result.updated_status.non_volatile.turns_asleep == 1


def test_sleep_gate_clears_sleep_and_allows_action_when_combatant_wakes_up():
    """
    验证睡眠状态在出招前判定醒来时会立即清除，并允许同一回合继续行动。本用例让固定随机数触发醒来分支，
    然后断言结果为 ALLOW、原因标记为 sleep_woke_up，且返回状态中不再存在 non-volatile sleep。这个边界很重要，
    因为后续回合流程应继续执行麻痹、着迷、混乱等后续 gate，而不是因为曾经睡眠就提前阻断行动。
    """
    status = CombatantStatusFactory.sleeping(turns_asleep=1)
    rng = FixedBattleRandom([True])

    result = SleepGate().check_before_action(
        status=status,
        move=MoveProfileFactory.physical(),
        ruleset=_gen9_ruleset(),
        rng=rng,
    )

    assert result.decision is ActionDecision.ALLOW
    assert result.reason == "sleep_woke_up"
    assert result.updated_status.non_volatile is None


def test_freeze_gate_blocks_normal_move_when_combatant_does_not_thaw():
    """
    验证冰冻状态下使用普通招式且没有通过概率解冻时会阻止行动。本用例让固定随机数返回未解冻，使用不带解冻
    标记的普通物理招式，断言 FreezeGate 返回 BLOCK 并保留原始冻结状态。这个测试保证冰冻 gate 只依据规则集
    的解冻概率和招式 flag 决策，不会因为招式名称、默认行为或其他状态误判而让被冻结的宝可梦错误行动。
    """
    status = CombatantStatusFactory.frozen()
    rng = FixedBattleRandom([False])

    result = FreezeGate().check_before_action(
        status=status,
        move=MoveProfileFactory.physical(),
        ruleset=_gen9_ruleset(),
        rng=rng,
    )

    assert result.decision is ActionDecision.BLOCK
    assert result.reason == "freeze"
    assert result.updated_status == status


def test_freeze_gate_thaw_move_flag_always_clears_freeze_and_allows_action():
    """
    验证带有 THAWS_USER_WHEN_FROZEN 标记的招式可以跳过概率判定，直接解除使用者冰冻并允许行动。本用例传入
    一个数据化 flag 招式，并检查固定随机数没有被消费，说明解冻行为没有依赖随机概率或硬编码招式名。这个测试
    锁住后续接入招式数据时的扩展点，确保新增解冻招式只需要配置 MoveFlag，而不需要修改 FreezeGate 逻辑。
    """
    status = CombatantStatusFactory.frozen()
    rng = FixedBattleRandom([])

    result = FreezeGate().check_before_action(
        status=status,
        move=MoveProfileFactory.thawing_physical(),
        ruleset=_gen9_ruleset(),
        rng=rng,
    )

    assert result.decision is ActionDecision.ALLOW
    assert result.reason == "freeze_thawed_by_move"
    assert result.updated_status.non_volatile is None
    assert rng.probabilities == []


def test_paralysis_gate_blocks_when_full_paralysis_occurs():
    """
    验证麻痹状态触发 full paralysis 时会阻止本回合行动。本用例使用固定随机数命中规则集中的麻痹不能动概率，
    然后断言 ParalysisGate 返回 BLOCK 且原因是 paralysis。这个测试覆盖行动阻断链中麻痹 gate 的核心分支，
    确保速度下降和不能动两个效果被拆开处理，后续修改速度修正器时不会意外影响出招前的麻痹阻断判定。
    """
    status = CombatantStatusFactory.paralyzed()
    rng = FixedBattleRandom([True])

    result = ParalysisGate().check_before_action(
        status=status,
        move=MoveProfileFactory.physical(),
        ruleset=_gen9_ruleset(),
        rng=rng,
    )

    assert result.decision is ActionDecision.BLOCK
    assert result.reason == "paralysis"


def test_infatuation_gate_blocks_when_infatuation_immobilizes_combatant():
    """
    验证着迷状态在本回合触发无法行动时会阻止原招式执行。本用例构造只带着迷 volatile status 的状态快照，
    通过固定随机数命中规则集中的 immobilize 概率，并断言结果为 BLOCK。这个测试保证着迷作为离场后消失的
    临时状态参与出招前 gate，而不是被误建模成主要异常状态或伤害修正，便于后续接入性别、特性和目标来源规则。
    """
    status = CombatantStatusFactory.infatuated()
    rng = FixedBattleRandom([True])

    result = InfatuationGate().check_before_action(
        status=status,
        move=MoveProfileFactory.physical(),
        ruleset=_gen9_ruleset(),
        rng=rng,
    )

    assert result.decision is ActionDecision.BLOCK
    assert result.reason == "infatuation"


def test_confusion_gate_replaces_move_with_self_hit_when_confusion_triggers():
    """
    验证混乱状态触发自伤时不会简单阻止行动，而是把原招式替换为混乱自伤流程。本用例构造只带混乱的状态快照，
    通过固定随机数命中 self-hit 概率，断言结果为 REPLACE_WITH_SELF_HIT 且原因是 confusion。这个测试区分混乱
    与睡眠、冰冻、麻痹、着迷的行为差异，保证后续回合执行器可以根据 decision 分派到自伤伤害计算。
    """
    status = CombatantStatusFactory.confused()
    rng = FixedBattleRandom([True])

    result = ConfusionGate().check_before_action(
        status=status,
        move=MoveProfileFactory.physical(),
        ruleset=_gen9_ruleset(),
        rng=rng,
    )

    assert result.decision is ActionDecision.REPLACE_WITH_SELF_HIT
    assert result.reason == "confusion"


def test_action_gate_pipeline_stops_after_first_blocking_gate():
    """
    验证出招前状态阻断链在某个 gate 返回阻断结果后会停止后续 gate。本用例让宝可梦同时处于麻痹和混乱状态，
    并通过固定随机数让麻痹先触发不能动；断言 pipeline 返回 paralysis 阻断，同时随机数队列被精确消费一次。
    这个测试保护 gate 顺序和短路语义，避免后续新增状态时继续执行混乱自伤等后续判断，造成一个回合出现多个互斥结果。
    """
    status = CombatantStatusFactory.paralyzed_and_confused()
    rng = FixedBattleRandom([True])

    result = default_action_gate_pipeline().check_before_action(
        status=status,
        move=MoveProfileFactory.physical(),
        ruleset=_gen9_ruleset(),
        rng=rng,
    )

    assert result.decision is ActionDecision.BLOCK
    assert result.reason == "paralysis"
    assert rng.results == []
