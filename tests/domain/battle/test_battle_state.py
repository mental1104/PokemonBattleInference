from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction

import pytest

from pokeop.domain.battle.context import BattleMove, MoveCategory
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.specs import InvalidBattleState, MoveSpec, PokemonSpec
from pokeop.domain.battle.state import (
    BattleFieldState,
    BattlePhase,
    BattleState,
    BattlerState,
    StatStages,
)
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from pokeop.domain.battle.status.state import (
    CombatantStatus,
    ConfusionStatus,
    FlinchStatus,
)
from pokeop.domain.battle.transitions import WeightedTransition
from pokeop.domain.models.types import Type


def _move_spec(
    move_id: int,
    *,
    name: str,
    move_type: Type,
    category: MoveCategory,
    power: int,
    max_pp: int,
) -> MoveSpec:
    """构造测试使用的显式招式配置。

    Args:
        move_id: 测试规则集中的稳定招式 ID。
        name: 只用于 DamageContext 展示的招式名称。
        move_type: 招式属性。
        category: 招式伤害分类。
        power: 招式威力；变化招式可为 0。
        max_pp: 当前配置的最大 PP。

    Returns:
        已通过生产代码构造期校验的 MoveSpec。
    """
    return MoveSpec(
        move_id=move_id,
        move=BattleMove(
            name=name,
            type=move_type,
            category=category,
            power=power,
        ),
        max_pp=max_pp,
    )


def _scizor_spec(
    *,
    name: str = "scizor",
    item: DamageItem = DamageItem.CHOICE_BAND,
) -> PokemonSpec:
    """构造具备四个合理招式槽的巨钳螳螂配置。

    Args:
        name: 展示名称，可在不改变战斗语义的情况下替换。
        item: 当前测试需要的携带道具，默认讲究头带以覆盖锁招状态。

    Returns:
        等级、属性、最终能力值、特性、道具和四招均完整的 PokemonSpec。
    """
    return PokemonSpec(
        pokemon_id=212,
        name=name,
        level=50,
        types=(Type.BUG, Type.STEEL),
        stats=StatValues(
            hp=177,
            attack=200,
            defense=120,
            special_attack=67,
            special_defense=100,
            speed=85,
        ),
        item=item,
        moves=(
            _move_spec(
                1,
                name="bullet-punch",
                move_type=Type.STEEL,
                category=MoveCategory.PHYSICAL,
                power=40,
                max_pp=30,
            ),
            _move_spec(
                2,
                name="x-scissor",
                move_type=Type.BUG,
                category=MoveCategory.PHYSICAL,
                power=80,
                max_pp=15,
            ),
            _move_spec(
                3,
                name="close-combat",
                move_type=Type.FIGHTING,
                category=MoveCategory.PHYSICAL,
                power=120,
                max_pp=5,
            ),
            _move_spec(
                4,
                name="swords-dance",
                move_type=Type.NORMAL,
                category=MoveCategory.STATUS,
                power=0,
                max_pp=20,
            ),
        ),
    )


def _sylveon_spec(*, name: str = "sylveon") -> PokemonSpec:
    """构造防守方仙子伊布配置，提供四个可区分的招式槽。

    Args:
        name: DamageContext 使用的展示名称，不参与规范化状态键。

    Returns:
        等级 50、单妖精属性和四个合理招式的 PokemonSpec。
    """
    return PokemonSpec(
        pokemon_id=700,
        name=name,
        level=50,
        types=(Type.FAIRY,),
        stats=StatValues(
            hp=202,
            attack=76,
            defense=117,
            special_attack=130,
            special_defense=150,
            speed=80,
        ),
        item=DamageItem.LIFE_ORB,
        moves=(
            _move_spec(
                101,
                name="moonblast",
                move_type=Type.FAIRY,
                category=MoveCategory.SPECIAL,
                power=95,
                max_pp=15,
            ),
            _move_spec(
                102,
                name="hyper-voice",
                move_type=Type.NORMAL,
                category=MoveCategory.SPECIAL,
                power=90,
                max_pp=10,
            ),
            _move_spec(
                103,
                name="quick-attack",
                move_type=Type.NORMAL,
                category=MoveCategory.PHYSICAL,
                power=40,
                max_pp=30,
            ),
            _move_spec(
                104,
                name="calm-mind",
                move_type=Type.PSYCHIC,
                category=MoveCategory.STATUS,
                power=0,
                max_pp=20,
            ),
        ),
    )


def _move_slots(spec: PokemonSpec) -> tuple[MoveSlotState, ...]:
    """把不变招式配置转换为满 PP 的动态槽位。

    Args:
        spec: 提供一到四个 MoveSpec 的宝可梦配置。

    Returns:
        顺序与 spec.moves 一致、当前 PP 等于最大 PP 的槽位元组。
    """
    return tuple(
        MoveSlotState(
            move_id=move.move_id,
            current_pp=move.max_pp,
            max_pp=move.max_pp,
        )
        for move in spec.moves
    )


def _battler(
    spec: PokemonSpec,
    *,
    current_hp: int | None = None,
    flinched: bool = False,
    item_consumed: bool = False,
) -> BattlerState:
    """构造测试所需的一方动态状态。

    Args:
        spec: 跨回合不变的宝可梦配置。
        current_hp: 当前 HP；None 表示使用配置中的最大 HP。
        flinched: 是否在临时状态集合中加入畏缩。
        item_consumed: 是否把携带道具标记为已经消耗。

    Returns:
        招式槽、状态集合和首次出场标记均完整的 BattlerState。
    """
    status = CombatantStatus(
        volatile=frozenset((FlinchStatus(),)) if flinched else frozenset()
    )
    return BattlerState(
        spec=spec,
        current_hp=spec.stats.hp if current_hp is None else current_hp,
        move_slots=_move_slots(spec),
        status=status,
        item_consumed=item_consumed,
    )


def _battle_state(
    *,
    attacker_spec: PokemonSpec | None = None,
    defender_spec: PokemonSpec | None = None,
    attacker_flinched: bool = False,
    defender_item_consumed: bool = False,
    field: BattleFieldState | None = None,
) -> BattleState:
    """构造一个遵循 Issue #20 首版合同的 1v1 节点。

    Args:
        attacker_spec: 稳定攻击方配置；None 时使用默认巨钳螳螂。
        defender_spec: 稳定防守方配置；None 时使用默认仙子伊布。
        attacker_flinched: 是否让稳定攻击方处于畏缩状态。
        defender_item_consumed: 是否让稳定防守方携带道具失效。
        field: 可选固定双方场地；None 时使用空场地。

    Returns:
        回合号为 1、处于行动选择阶段且双方等级与规则一致的 BattleState。
    """
    return BattleState(
        attacker=_battler(attacker_spec or _scizor_spec(), flinched=attacker_flinched),
        defender=_battler(
            defender_spec or _sylveon_spec(),
            item_consumed=defender_item_consumed,
        ),
        rules=BattleInferenceRules(level=50),
        field=field or BattleFieldState(),
    )


def test_equivalent_battle_states_share_one_hashable_state_key() -> None:
    """验证语义等价节点可以稳定用于状态图去重。两个节点使用相同 Pokémon ID、能力值、
    四个招式槽、PP、回合、阶段、首次出场与畏缩状态，只把双方展示名称替换成另一种文案；
    预期 BattleState、StateKey 和哈希完全相同，并能作为 dict/set 键互相命中。该场景保护
    “名称、trace 或展示文本不得污染状态键”的边界，同时直接证明当前模型能够表达双方 HP、
    四招 PP、畏缩和首次出场标记，而不会因为旧 Type 枚举不可哈希导致图节点失效。
    """
    original = _battle_state(attacker_flinched=True)
    renamed = _battle_state(
        attacker_spec=_scizor_spec(name="巨钳螳螂"),
        defender_spec=_sylveon_spec(name="仙子伊布"),
        attacker_flinched=True,
    )

    assert original == renamed
    assert original.state_key == renamed.state_key
    assert hash(original) == hash(renamed)
    assert {original: "reachable"}[renamed] == "reachable"
    assert len({original, renamed}) == 1
    transition = WeightedTransition(probability=Fraction(1, 1), state=original)
    assert transition.state.state_key == original.state_key
    assert len(original.attacker.move_slots) == 4
    assert original.attacker.is_first_turn is True
    assert original.attacker.status.has_volatile(VolatileStatusKind.FLINCH)


def test_state_key_changes_for_each_future_relevant_dynamic_field() -> None:
    """验证状态键不会把会改变后续转移的节点错误合并。以同一初始节点为基准，分别改变当前
    HP、非锁定招式 PP、禁用标记、讲究锁招、能力等级、上一招、道具消耗、畏缩状态、首次
    出场标记和回合阶段；每个变体都应产生不同 StateKey。测试特意保持 Pokémon 名称、规则和
    其他配置一致，确保差异确实来自动态字段本身。该场景防止求解器未来因为键遗漏而把可选行动、
    伤害承受能力或回合语义不同的节点视为同一状态，也验证 MoveSlotState 的禁用/锁定语义已进入
    规范化图节点表示。绝对回合号只用于运行保护，因此推进到下一回合但局面完全相同时仍应命中
    同一个语义键，允许形成回边。
    """
    base = _battle_state()
    lower_hp = base.with_battler(
        BattleSide.ATTACKER,
        base.attacker.with_current_hp(base.attacker.current_hp - 1),
    )
    lower_pp_slot = base.attacker.move_slot(2).with_current_pp(14)
    lower_pp = base.with_battler(
        BattleSide.ATTACKER,
        base.attacker.with_move_slot(lower_pp_slot),
    )
    disabled = base.with_battler(
        BattleSide.ATTACKER,
        base.attacker.with_move_slot(base.attacker.move_slot(2).with_disabled()),
    )
    choice_locked = base.with_battler(
        BattleSide.ATTACKER,
        base.attacker.with_choice_lock(1),
    )
    boosted = base.with_battler(
        BattleSide.ATTACKER,
        base.attacker.with_stat_stages(StatStages(attack=1)),
    )
    recorded_move = base.with_battler(
        BattleSide.ATTACKER,
        base.attacker.with_last_move(165),
    )
    consumed_item = base.with_battler(
        BattleSide.ATTACKER,
        base.attacker.with_item_consumed(),
    )
    flinched = base.with_battler(
        BattleSide.ATTACKER,
        base.attacker.with_status(base.attacker.status.add_volatile(FlinchStatus())),
    )
    after_first_turn = base.with_battler(
        BattleSide.ATTACKER,
        base.attacker.mark_first_turn_complete(),
    )
    next_turn = base.next_turn()
    resolving = base.with_phase(BattlePhase.ACTION_RESOLUTION)

    variants = {
        base.state_key,
        lower_hp.state_key,
        lower_pp.state_key,
        disabled.state_key,
        choice_locked.state_key,
        boosted.state_key,
        recorded_move.state_key,
        consumed_item.state_key,
        flinched.state_key,
        after_first_turn.state_key,
        resolving.state_key,
    }
    assert len(variants) == 11
    assert next_turn.turn_number == 2
    assert next_turn.state_key == base.state_key
    assert choice_locked.attacker.choice_lock_move_id == 1
    assert choice_locked.attacker.move_slot(1).is_locked is True


def test_immutable_updates_create_new_nodes_without_mutating_ancestors() -> None:
    """验证状态图扩展采用持久化数据结构语义，而不是原地改写父节点。先从初始节点扣除第一方
    HP，再减少一个招式槽的 PP，并推进到下一回合；每一步都必须返回新对象，初始节点的 HP、PP、
    回合号和阶段保持原值。随后直接尝试给 frozen 字段赋值，应抛出 FrozenInstanceError。该测试
    保护分支枚举时最关键的祖先节点隔离：同一父状态产生多个概率分支后，任一孩子的更新都不能
    污染兄弟分支或已经放入 dict/set 的键，否则状态图概率累计会得到不可复现的错误结果。
    """
    original = _battle_state()
    damaged_first = original.attacker.with_current_hp(original.attacker.current_hp - 30)
    damaged = original.with_battler(BattleSide.ATTACKER, damaged_first)
    spent_slot = damaged.attacker.move_slot(1).with_current_pp(29)
    spent = damaged.with_battler(
        BattleSide.ATTACKER,
        damaged.attacker.with_move_slot(spent_slot),
    )
    advanced = spent.next_turn()

    assert original.attacker.current_hp == original.attacker.spec.stats.hp
    assert original.attacker.move_slot(1).current_pp == 30
    assert original.turn_number == 1
    assert damaged.attacker.current_hp == original.attacker.current_hp - 30
    assert spent.attacker.move_slot(1).current_pp == 29
    assert advanced.turn_number == 2
    assert advanced.phase is BattlePhase.ACTION_SELECTION
    with pytest.raises(FrozenInstanceError):
        setattr(original, "turn_number", 99)


def test_constructor_rejects_invalid_hp_pp_stat_stage_and_slot_mapping() -> None:
    """验证所有基础数值边界在对象进入状态图前就被拒绝。测试分别构造负 HP、超过最大 HP、
    当前 PP 大于最大 PP、能力等级超过正六级，以及缺少一个已配置招式槽的状态；这些输入都应
    抛出统一 InvalidBattleState，而不是等到求解器遍历时才暴露。场景覆盖 Issue #21 对 HP、PP、
    能力等级和完整四槽映射的直接验收要求，并保证非法节点无法被哈希、缓存或传入伤害计算，避免
    后续代码被迫在每次状态转移中重复防御同一批结构性错误。最后再用两个不同计数的混乱状态
    构造同类临时状态组合，确认 CombatantStatus 仍会拒绝一个种类同时出现多份的非法快照。
    """
    spec = _scizor_spec()

    with pytest.raises(InvalidBattleState, match="current_hp"):
        _battler(spec, current_hp=-1)
    with pytest.raises(InvalidBattleState, match="current_hp"):
        _battler(spec, current_hp=spec.stats.hp + 1)
    with pytest.raises(InvalidBattleState, match="current_pp"):
        MoveSlotState(move_id=1, current_pp=31, max_pp=30)
    with pytest.raises(InvalidBattleState, match="attack stage"):
        StatStages(attack=7)
    with pytest.raises(InvalidBattleState, match="match configured moves"):
        BattlerState(
            spec=spec,
            current_hp=spec.stats.hp,
            move_slots=_move_slots(spec)[:-1],
        )
    with pytest.raises(ValueError, match="unique kinds"):
        CombatantStatus(
            volatile=frozenset(
                (
                    ConfusionStatus(turns_remaining=1),
                    ConfusionStatus(turns_remaining=2),
                )
            )
        )


def test_constructor_rejects_illegal_choice_lock_combinations() -> None:
    """验证讲究锁招必须同时满足道具、槽位和可行动性不变量。测试覆盖没有讲究道具却声明锁招、
    choice_lock_move_id 与 is_locked 槽位不一致、锁定 ID 不属于配置，以及道具已消耗后仍保留锁招
    四种非法组合；每种情况都应在 BattlerState 构造期明确失败。该场景防止状态键出现表面不同但
    语义无法执行的节点，也确保后续合法行动生成器无需猜测应该相信字段级锁定标记还是战斗方级
    choice lock，从而把“唯一锁定招式”维持为一个可审查、可测试的领域不变量。测试同时保留
    一个合法边界：锁定招式耗尽 PP 后锁定状态仍可存在，后续合法行动层可以据此选择 Struggle。
    """
    non_choice_spec = _scizor_spec(item=DamageItem.LIFE_ORB)
    choice_spec = _scizor_spec()
    locked_first = tuple(
        replace(slot, is_locked=slot.move_id == 1)
        for slot in _move_slots(choice_spec)
    )

    with pytest.raises(InvalidBattleState, match="choice item"):
        BattlerState(
            spec=non_choice_spec,
            current_hp=non_choice_spec.stats.hp,
            move_slots=tuple(
                replace(slot, is_locked=slot.move_id == 1)
                for slot in _move_slots(non_choice_spec)
            ),
            choice_lock_move_id=1,
        )
    with pytest.raises(InvalidBattleState, match="exactly"):
        BattlerState(
            spec=choice_spec,
            current_hp=choice_spec.stats.hp,
            move_slots=locked_first,
            choice_lock_move_id=2,
        )
    with pytest.raises(InvalidBattleState, match="configured move"):
        BattlerState(
            spec=choice_spec,
            current_hp=choice_spec.stats.hp,
            move_slots=locked_first,
            choice_lock_move_id=999,
        )
    with pytest.raises(InvalidBattleState, match="consumed item"):
        BattlerState(
            spec=choice_spec,
            current_hp=choice_spec.stats.hp,
            move_slots=locked_first,
            choice_lock_move_id=1,
            item_consumed=True,
        )

    depleted_locked = BattlerState(
        spec=choice_spec,
        current_hp=choice_spec.stats.hp,
        move_slots=tuple(
            replace(slot, current_pp=0) if slot.move_id == 1 else slot
            for slot in locked_first
        ),
        choice_lock_move_id=1,
    )
    assert depleted_locked.move_slot(1).current_pp == 0
    assert depleted_locked.choice_lock_move_id == 1


def test_damage_context_conversion_preserves_relative_sides_and_consumed_item() -> None:
    """验证 BattleState 到旧 DamageContext 的兼容边界不会改变固定双方语义。让稳定防守方仙子伊布
    使用月亮之力，同时给稳定攻击方设置反射壁、稳定防守方设置光墙，并把防守方道具标记为已消耗；转换后
    attacker/defender 应按防守方行动重新排列，环境中的 attacker_side 应对应稳定防守方光墙，
    defender_side 应对应稳定攻击方反射壁，招式和双方名称应正常进入旧快照，而攻击方 item 必须变为
    UNKNOWN。该场景确保状态图模型可以复用现有伤害责任链，又不会让相对边侧、消耗道具或原节点
    在转换过程中发生丢失和原地修改。
    """
    first_side = SideConditions(reflect=True)
    second_side = SideConditions(light_screen=True)
    battle = _battle_state(
        defender_item_consumed=True,
        field=BattleFieldState(
            attacker_side_conditions=first_side,
            defender_side_conditions=second_side,
        ),
    )

    context = battle.damage_context_for(
        acting_side=BattleSide.DEFENDER,
        move_id=101,
        is_critical=True,
    )

    assert context.attacker.name == "sylveon"
    assert context.defender.name == "scizor"
    assert context.move.name == "moonblast"
    assert context.attacker.item is DamageItem.UNKNOWN
    assert context.defender.item is DamageItem.CHOICE_BAND
    assert context.environment.attacker_side == second_side
    assert context.environment.defender_side == first_side
    assert context.is_critical is True
    assert battle.defender.item_consumed is True


def test_damage_context_conversion_rejects_unusable_or_unlocked_moves() -> None:
    """验证兼容转换只接受当前节点中的合法伤害行动。测试先把子弹拳 PP 归零，再把它标记禁用，
    最后建立锁定子弹拳的讲究状态却尝试使用十字剪；三种情况分别应因无 PP、禁用和违反锁招而
    抛出 InvalidBattleState。该场景明确转换函数只是从已验证节点生成只读伤害快照，不会偷偷
    修复状态、自动解除锁招或绕过合法行动约束，也避免后续状态图执行器把不可选择的招式送入现有
    DamageContext 责任链，从而产生不存在于真实战斗中的概率分支。
    """
    battle = _battle_state()
    empty_slot = battle.attacker.move_slot(1).with_current_pp(0)
    no_pp = battle.with_battler(
        BattleSide.ATTACKER,
        battle.attacker.with_move_slot(empty_slot),
    )
    disabled_slot = battle.attacker.move_slot(1).with_disabled()
    disabled = battle.with_battler(
        BattleSide.ATTACKER,
        battle.attacker.with_move_slot(disabled_slot),
    )
    locked = battle.with_battler(
        BattleSide.ATTACKER,
        battle.attacker.with_choice_lock(1),
    )

    with pytest.raises(InvalidBattleState, match="remaining pp"):
        no_pp.damage_context_for(acting_side=BattleSide.ATTACKER, move_id=1)
    with pytest.raises(InvalidBattleState, match="disabled move"):
        disabled.damage_context_for(acting_side=BattleSide.ATTACKER, move_id=1)
    with pytest.raises(InvalidBattleState, match="choice lock"):
        locked.damage_context_for(acting_side=BattleSide.ATTACKER, move_id=2)
