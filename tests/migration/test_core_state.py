"""通过真实 C ABI 对照原不可变状态、完整键语义及精确状态修正，不模拟 Core。"""
from __future__ import annotations

import os
import random
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from pokeop.domain.battle.abilities import DamageAbility
from pokeop.domain.battle.actions import PassAction
from pokeop.domain.battle.context import BattleMove, DamageContext, MoveCategory
from pokeop.domain.battle.grounding import GroundingState
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleFormat, BattleInferenceRules, CycleResolution, RepetitionResolution, SwitchingPolicy
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_execution import EffectiveSpeedActionOrderPolicy
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.rulesets.damage_policy import DamagePolicy
from pokeop.domain.battle.rulesets.resolver import resolve_ruleset_by_generation
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.specs import MoveSpec, PokemonSpec
from pokeop.domain.battle.state import BattleFieldState, BattlePhase, BattleState, BattlerState, StatStages
from pokeop.domain.battle.stats import StatValues
from pokeop.domain.battle.status.cleanup import clear_status_on_switch_out
from pokeop.domain.battle.status.modifiers import apply_burn_physical_damage_modifier, apply_paralysis_speed_modifier, burn_physical_damage_multiplier
from pokeop.domain.battle.status.state import BadPoisonStatus, BurnStatus, CombatantStatus, ConfusionStatus, FlinchStatus, FreezeStatus, InfatuationStatus, ParalysisStatus, PoisonStatus, SleepStatus
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.weather import Weather
from pokeop.domain.battle.moves.models import MoveProfile
from pokeop.domain.models.types import Type, TypeHelper
from tests.migration.test_core_damage import DamageResponse, ExactFraction, MoveSnapshot, PokemonSnapshot, TypeEfficacySnapshot


class _Contract(BaseModel):
    """只负责固定测试协议边界，冻结并拒绝未知字段。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class SleepSnapshot(_Contract):
    """睡眠种类与专属计数，不允许夹带其他状态字段。"""
    kind: Literal["sleep"] = "sleep"
    turns_asleep: int


class PoisonSnapshot(_Contract):
    """剧毒种类与专属计数。"""
    kind: Literal["bad_poison"] = "bad_poison"
    toxic_counter: int


class SimpleMajor(_Contract):
    """四种无附加字段的主状态。"""
    kind: Literal["paralysis", "burn", "freeze", "poison"]


class ConfusionSnapshot(_Contract):
    """混乱剩余回合，可明确为空。"""
    kind: Literal["confusion"] = "confusion"
    turns_remaining: int | None


class InfatuationSnapshot(_Contract):
    """迷恋来源，空字符串与 null 不等价。"""
    kind: Literal["infatuation"] = "infatuation"
    source_id: str | None


class FlinchSnapshot(_Contract):
    """畏缩标记，没有计数或来源字段。"""
    kind: Literal["flinch"] = "flinch"


MajorSnapshot = Annotated[SleepSnapshot | PoisonSnapshot | SimpleMajor, Field(discriminator="kind")]
VolatileSnapshot = Annotated[ConfusionSnapshot | InfatuationSnapshot | FlinchSnapshot, Field(discriminator="kind")]
Stages = tuple[int, int, int, int, int, int, int]


class StatusSnapshot(_Contract):
    """规范主/临时状态集合，临时项按 Core 的种类顺序输出。"""
    major: MajorSnapshot | None
    volatile: tuple[VolatileSnapshot, ...]


class MoveSpecSnapshot(_Contract):
    """完整不变招式合同，名称与机制标识的责任分开。"""
    move_id: int
    name: str
    move: MoveSnapshot
    max_pp: int
    priority: int
    accuracy: int | None
    effect_identifier: str | None


class SpecSnapshot(_Contract):
    """完整宝可梦不变配置，复用伤害快照合同。"""
    pokemon_id: int
    name: str
    pokemon: PokemonSnapshot
    moves: tuple[MoveSpecSnapshot, ...]


class SlotSnapshot(_Contract):
    """完整动态槽，含稳定运行时身份。"""
    move_id: int
    current_pp: int
    max_pp: int
    disabled: bool
    locked: bool
    slot_id: int


class BattlerSnapshot(_Contract):
    """一方节点的全部未来相关字段，测试不只核对 HP。"""
    spec: SpecSnapshot
    current_hp: int
    move_slots: tuple[SlotSnapshot, ...]
    stages: Stages
    status: StatusSnapshot
    last_move_id: int | None
    choice_lock_move_id: int | None
    item_consumed: bool
    is_first_turn: bool


class ExecutionSnapshot(_Contract):
    """执行 policy 的完整值，精确挣扎反伤分数不经浮点数。"""
    accuracy_denominator: int
    consume_pp_on_miss: bool
    consume_pp_when_action_blocked: bool
    consume_pp_when_before_move_stops: bool
    struggle_power: int
    struggle_recoil_fraction: ExactFraction


class RulesSnapshot(_Contract):
    """进入键的完整规则快照。"""
    ruleset_id: str
    version_group_id: int
    level: int
    battle_format: BattleFormat
    switching_policy: SwitchingPolicy
    allow_terastallization: bool
    allow_mega_evolution: bool
    allow_dynamax: bool
    max_turns: int | None
    repetition_resolution: RepetitionResolution
    cycle_resolution: CycleResolution
    damage_policy: DamagePolicy
    move_execution_policy: ExecutionSnapshot


class FieldSnapshot(_Contract):
    """固定双方的完整场地，与单次攻击相对双方不同。"""
    weather: Weather | Literal["none"]
    terrain: Terrain | Literal["none"]
    attacker_side: SideConditions
    defender_side: SideConditions


class BattleSnapshot(_Contract):
    """完整可重放状态；比较结果仍使用原 Python StateKey。"""
    attacker: BattlerSnapshot
    defender: BattlerSnapshot
    rules: RulesSnapshot
    turn_number: int
    field: FieldSnapshot
    phase: BattlePhase


class HpChange(_Contract):
    """更新指定侧 HP。"""
    kind: Literal["hp"] = "hp"
    side: BattleSide
    value: int


class PpChange(_Contract):
    """更新指定招式 PP。"""
    kind: Literal["pp"] = "pp"
    side: BattleSide
    move_id: int
    value: int


class DisabledChange(_Contract):
    """更新指定招式禁用标记。"""
    kind: Literal["disabled"] = "disabled"
    side: BattleSide
    move_id: int
    value: bool


class MoveIdChange(_Contract):
    """替换锁招或上一招，null 语义明确。"""
    kind: Literal["choice_lock", "last_move"]
    side: BattleSide
    move_id: int | None


class StagesChange(_Contract):
    """替换完整七等级。"""
    kind: Literal["stages"] = "stages"
    side: BattleSide
    value: Stages


class StatusChange(_Contract):
    """替换完整状态集合。"""
    kind: Literal["status"] = "status"
    side: BattleSide
    value: StatusSnapshot


class ItemChange(_Contract):
    """替换道具消耗标记。"""
    kind: Literal["item_consumed"] = "item_consumed"
    side: BattleSide
    value: bool


class FirstTurnChange(_Contract):
    """清除首次回合标记。"""
    kind: Literal["first_turn_complete"] = "first_turn_complete"
    side: BattleSide


class NextTurnChange(_Contract):
    """进入下一绝对回合。"""
    kind: Literal["next_turn"] = "next_turn"


class PhaseChange(_Contract):
    """替换回合阶段。"""
    kind: Literal["phase"] = "phase"
    value: BattlePhase


class FieldChange(_Contract):
    """替换固定双方场地。"""
    kind: Literal["field"] = "field"
    value: FieldSnapshot


class RulesChange(_Contract):
    """显式替换完整规则。"""
    kind: Literal["rules"] = "rules"
    value: RulesSnapshot


class SlotChange(_Contract):
    """按 ID 替换完整槽位。"""
    kind: Literal["slot"] = "slot"
    side: BattleSide
    value: SlotSnapshot


Update = Annotated[HpChange | PpChange | DisabledChange | MoveIdChange | StagesChange | StatusChange | ItemChange | FirstTurnChange | NextTurnChange | PhaseChange | FieldChange | RulesChange | SlotChange, Field(discriminator="kind")]


class DamageQuery(_Contract):
    """更新后从实际状态构造伤害输入，验证 PP/锁招与道具转换接线。"""
    side: BattleSide
    move_id: int
    generation_id: int
    type_chart: tuple[TypeEfficacySnapshot, ...]
    policy: DamagePolicy | None = None


class StateOperation(_Contract):
    """原子状态更新请求；所有可选值均明确可空。"""
    kind: Literal["battle_state"] = "battle_state"
    state: BattleSnapshot
    updates: tuple[Update, ...]
    compare_to: BattleSnapshot | None = None
    damage_query: DamageQuery | None = None


class StatusOperation(_Contract):
    """独立状态修正请求，完整有理数输入直接跨 ABI。"""
    kind: Literal["status_modifiers"] = "status_modifiers"
    status: StatusSnapshot
    speed: int
    generation_id: int
    category: MoveCategory
    base_multiplier: ExactFraction
    burn_multiplier: ExactFraction
    paralysis_multiplier: ExactFraction | None = None


class StateResponse(_Contract):
    """完整状态、两个规范键等价判断、行动速度和可选实际伤害。"""
    kind: Literal["battle_state"]
    state: BattleSnapshot
    same_key_as_input: bool
    same_key_as_reference: bool | None
    attacker_speed: int
    defender_speed: int
    damage: DamageResponse | None


class StatusResponse(_Contract):
    """独立状态 helper 的全部输出。"""
    kind: Literal["status_modifiers"]
    status: StatusSnapshot
    speed: int
    burn_multiplier: ExactFraction
    adjusted_multiplier: ExactFraction
    after_switch_out: StatusSnapshot


class Batch(_Contract):
    """正式 ABI 请求封装，不单独启动测试专用规则实现。"""
    schema_version: Literal[1] = 1
    operations: tuple[Annotated[StateOperation | StatusOperation, Field(discriminator="kind")], ...]


class Envelope(_Contract):
    """成功结果的完整固定合同，错误对象不能被当作成功。"""
    schema_version: Literal[1]
    engine_version: Literal["0.11.0"]
    rules_version: Literal["calculation-rules.v11"]
    results: tuple[Annotated[StateResponse | StatusResponse, Field(discriminator="kind")], ...]


@dataclass(frozen=True)
class StateCase:
    """由 Python 公开状态方法产生的输入/预期，避免在测试中重写状态更新算法。"""
    before: BattleState
    updates: tuple[Update, ...]
    after: BattleState
    reference: BattleState | None = None
    query: DamageQuery | None = None
    damage_context: DamageContext | None = None


class _StateOracle:
    """集中负责旧领域模型到固定合同的适配；语义判断来自 Python 原实现。"""

    @staticmethod
    def fraction(value: Fraction) -> ExactFraction:
        """value 为任意精确分数；返回规范十进制分子/分母，不经 float。"""
        return ExactFraction(numerator=str(value.numerator), denominator=str(value.denominator))

    @staticmethod
    def status(value: CombatantStatus) -> StatusSnapshot:
        """value 为只读旧状态；返回按固定种类顺序编码的完整快照。"""
        major: MajorSnapshot | None = None
        status = value.non_volatile
        if isinstance(status, SleepStatus): major = SleepSnapshot(turns_asleep=status.turns_asleep)
        elif isinstance(status, BadPoisonStatus): major = PoisonSnapshot(toxic_counter=status.toxic_counter)
        elif isinstance(status, ParalysisStatus): major = SimpleMajor(kind="paralysis")
        elif isinstance(status, BurnStatus): major = SimpleMajor(kind="burn")
        elif isinstance(status, FreezeStatus): major = SimpleMajor(kind="freeze")
        elif isinstance(status, PoisonStatus): major = SimpleMajor(kind="poison")
        elif status is not None: raise AssertionError("unsupported major status in the reference oracle")
        temporary: list[VolatileSnapshot] = []
        for item in value.volatile:
            if isinstance(item, ConfusionStatus): temporary.append(ConfusionSnapshot(turns_remaining=item.turns_remaining))
            elif isinstance(item, InfatuationStatus): temporary.append(InfatuationSnapshot(source_id=item.source_id))
            elif isinstance(item, FlinchStatus): temporary.append(FlinchSnapshot())
            else: raise AssertionError("unsupported volatile status in the reference oracle")
        order = ("confusion", "infatuation", "flinch")
        return StatusSnapshot(major=major, volatile=tuple(sorted(temporary, key=lambda item: order.index(item.kind))))

    @classmethod
    def battler(cls, value: BattlerState) -> BattlerSnapshot:
        """value 为只读旧一方节点；返回包含全部静态/动态字段的快照。"""
        spec = value.spec
        return BattlerSnapshot(
            spec=SpecSnapshot(pokemon_id=spec.pokemon_id, name=spec.name,
                pokemon=PokemonSnapshot(level=spec.level, types=spec.types, stats=spec.stats,
                    ability="none" if spec.ability is DamageAbility.UNKNOWN else spec.ability,
                    item="none" if spec.item is DamageItem.UNKNOWN else spec.item,
                    can_evolve=spec.can_evolve, grounding=spec.grounding_state),
                moves=tuple(MoveSpecSnapshot(move_id=move.move_id, name=move.move.name,
                    move=MoveSnapshot(type=move.move.type, category=move.move.category, power=move.move.power),
                    max_pp=move.max_pp, priority=move.priority, accuracy=move.accuracy, effect_identifier=move.effect_identifier) for move in spec.moves)),
            current_hp=value.current_hp, move_slots=tuple(cls.slot(slot) for slot in value.move_slots),
            stages=cls.stages(value.stat_stages),
            status=cls.status(value.status), last_move_id=value.last_move_id, choice_lock_move_id=value.choice_lock_move_id,
            item_consumed=value.item_consumed, is_first_turn=value.is_first_turn,
        )

    @staticmethod
    def stages(value: StatStages) -> Stages:
        """value 为已验证七等级；返回具有完整静态长度关系的协议元组。"""
        return (value.attack, value.defense, value.special_attack, value.special_defense, value.speed, value.accuracy, value.evasion)

    @staticmethod
    def slot(value: MoveSlotState) -> SlotSnapshot:
        """value 为只读旧槽；返回全部运行时槽位字段。"""
        return SlotSnapshot(move_id=value.move_id, current_pp=value.current_pp, max_pp=value.max_pp,
                            disabled=value.is_disabled, locked=value.is_locked, slot_id=value.slot_id)

    @classmethod
    def rules(cls, value: BattleInferenceRules) -> RulesSnapshot:
        """value 为只读完整规则；返回原策略语义，不推定 version_group 就等于 damage profile。"""
        policy = value.move_execution_policy
        return RulesSnapshot(ruleset_id=value.ruleset_id, version_group_id=value.version_group_id, level=value.level,
            battle_format=value.battle_format, switching_policy=value.switching_policy,
            allow_terastallization=value.allow_terastallization, allow_mega_evolution=value.allow_mega_evolution, allow_dynamax=value.allow_dynamax,
            max_turns=value.max_turns, repetition_resolution=value.repetition_resolution, cycle_resolution=value.cycle_resolution,
            damage_policy=value.damage_policy,
            move_execution_policy=ExecutionSnapshot(accuracy_denominator=policy.accuracy_denominator, consume_pp_on_miss=policy.consume_pp_on_miss,
                consume_pp_when_action_blocked=policy.consume_pp_when_action_blocked, consume_pp_when_before_move_stops=policy.consume_pp_when_before_move_stops,
                struggle_power=policy.struggle_power, struggle_recoil_fraction=cls.fraction(policy.struggle_recoil_fraction)))

    @staticmethod
    def field(value: BattleFieldState) -> FieldSnapshot:
        """value 为固定双方场地；返回相同视角，不提前交换攻击方向。"""
        return FieldSnapshot(weather=value.weather or "none", terrain=value.terrain or "none",
                             attacker_side=value.attacker_side_conditions, defender_side=value.defender_side_conditions)

    @classmethod
    def snapshot(cls, value: BattleState) -> BattleSnapshot:
        """value 为只读完整旧节点；返回重放及完整比较所需的全部字段。"""
        return BattleSnapshot(attacker=cls.battler(value.attacker), defender=cls.battler(value.defender), rules=cls.rules(value.rules),
                              turn_number=value.turn_number, field=cls.field(value.field), phase=value.phase)

    @staticmethod
    def execute(runner: Path, operations: Sequence[StateOperation | StatusOperation]) -> tuple[StateResponse | StatusResponse, ...]:
        """runner 为实际 ABI 程序，operations 为完整固定模型；返回解析后的所有结果。

        每批最多 32 项并限制进程 60 秒，显式检查批次/槽位数量，不吞掉错误响应。
        """
        batches = tuple(Batch(operations=tuple(operations[index:index + 32])) for index in range(0, len(operations), 32))
        result = subprocess.run([str(runner)], input="\n".join(batch.model_dump_json() for batch in batches) + "\n",
                                text=True, capture_output=True, check=True, timeout=60)
        lines = result.stdout.splitlines()
        assert len(lines) == len(batches)
        values = tuple(value for line in lines for value in Envelope.model_validate_json(line).results)
        assert len(values) == len(operations)
        return values

    @classmethod
    def run(cls, runner: Path, cases: Sequence[StateCase]) -> None:
        """runner 为实际 ABI 程序，cases 使用原模型给出预期；完整验证快照、键与原行动排序。"""
        operations = tuple(StateOperation(state=cls.snapshot(case.before), updates=case.updates,
            compare_to=cls.snapshot(case.reference) if case.reference is not None else None, damage_query=case.query) for case in cases)
        results = cls.execute(runner, operations)
        ordering = EffectiveSpeedActionOrderPolicy()
        for case, actual in zip(cases, results, strict=True):
            assert isinstance(actual, StateResponse)
            assert actual.state == cls.snapshot(case.after)
            assert actual.same_key_as_input == (case.after.state_key == case.before.state_key)
            assert actual.same_key_as_reference == (case.after.state_key == case.reference.state_key if case.reference is not None else None)
            assert actual.attacker_speed == ordering.base_order(case.after, PassAction(BattleSide.ATTACKER)).speed
            assert actual.defender_speed == ordering.base_order(case.after, PassAction(BattleSide.DEFENDER)).speed
            if case.damage_context is None:
                assert actual.damage is None
            else:
                # 复用已经完整比较伤害/trace/精确 KO 的 oracle，不在状态测试复制规则。
                from tests.migration.test_core_damage import _DamageOracle
                assert actual.damage is not None
                _DamageOracle.check(case.damage_context, actual.damage)


@pytest.fixture(scope="module")
def state_runner() -> Path:
    """返回已构建的真实 ABI 程序；无配置且未构建才 SKIP，错误显式配置必须 FAIL。"""
    configured = os.environ.get("PBI_CORE_VECTOR_RUNNER")
    directory = Path(configured).parent if configured else Path(__file__).resolve().parents[2] / "build/core"
    path = directory / "pbi_abi_vectors"
    if not path.is_file() or not os.access(path, os.X_OK):
        if configured: pytest.fail("configured core build must contain pbi_abi_vectors")
        pytest.skip("run make test-core to enable state differential tests")
    return path


def _reference() -> BattleState:
    """无参数；返回四个招式、不同双方属性/能力和运行时槽位的旧领域节点。"""
    first_moves = (
        MoveSpec(1, BattleMove("bullet-punch", Type.STEEL, MoveCategory.PHYSICAL, 40), 30, priority=1),
        MoveSpec(2, BattleMove("brick-break", Type.FIGHTING, MoveCategory.PHYSICAL, 75), 15, effect_identifier="Brick-Break"),
        MoveSpec(3, BattleMove("special", Type.BUG, MoveCategory.SPECIAL, 80), 10, accuracy=None),
        MoveSpec(4, BattleMove("swords-dance", Type.NORMAL, MoveCategory.STATUS, 0), 20),
    )
    second_moves = tuple(replace(move, move_id=move.move_id + 100) for move in first_moves)
    first = PokemonSpec(212, "scizor", 50, (Type.BUG, Type.STEEL), StatValues(177, 182, 120, 67, 100, 85), item=DamageItem.CHOICE_BAND, moves=first_moves)
    second = PokemonSpec(700, "sylveon", 50, (Type.FAIRY,), StatValues(202, 76, 85, 130, 150, 80), item=DamageItem.LIFE_ORB, moves=second_moves)
    return BattleState(
        BattlerState(first, first.stats.hp, tuple(MoveSlotState(move.move_id, move.max_pp, move.max_pp, slot_id=1000 + move.move_id) for move in first.moves)),
        BattlerState(second, second.stats.hp, tuple(MoveSlotState(move.move_id, move.max_pp, move.max_pp, slot_id=2000 + move.move_id) for move in second.moves)),
        BattleInferenceRules(),
    )


class TestCoreState:
    """状态、键、方向转换与精确状态 helper 的真实跨 ABI 差分。"""

    def test_immutable_update_chain_and_damage(self, state_runner: Path) -> None:
        """state_runner 为真实 ABI；验证 PP/锁招/消耗道具/阶段更新及方向正确的实际伤害。"""
        before = _reference()
        attacker = before.attacker.with_current_hp(140).with_move_slot(before.attacker.move_slot(1).with_current_pp(29)).with_choice_lock(1)
        attacker = attacker.with_stat_stages(StatStages(speed=-1)).with_status(CombatantStatus(ParalysisStatus(), frozenset((FlinchStatus(),)))).mark_first_turn_complete()
        after = before.with_battler(BattleSide.ATTACKER, attacker).with_battler(BattleSide.DEFENDER, before.defender.with_item_consumed())
        after = after.with_field(BattleFieldState(weather=Weather.RAIN, attacker_side_conditions=SideConditions(reflect=True))).next_turn()
        updates: tuple[Update, ...] = (
            HpChange(side=BattleSide.ATTACKER, value=140), PpChange(side=BattleSide.ATTACKER, move_id=1, value=29),
            MoveIdChange(kind="choice_lock", side=BattleSide.ATTACKER, move_id=1),
            StagesChange(side=BattleSide.ATTACKER, value=(0, 0, 0, 0, -1, 0, 0)), StatusChange(side=BattleSide.ATTACKER, value=_StateOracle.status(attacker.status)),
            FirstTurnChange(side=BattleSide.ATTACKER), ItemChange(side=BattleSide.DEFENDER, value=True), FieldChange(value=_StateOracle.field(after.field)), NextTurnChange(),
        )
        rules = resolve_ruleset_by_generation(9)
        context = after.damage_context_for(acting_side=BattleSide.DEFENDER, move_id=101, damage_ruleset=rules)
        query = DamageQuery(side=BattleSide.DEFENDER, move_id=101, generation_id=9,
            type_chart=tuple(TypeEfficacySnapshot(attacking=context.move.type, defending=kind, percent=TypeHelper.get_type_efficacy(context.move.type, kind)) for kind in context.defender.types))
        _StateOracle.run(state_runner, (StateCase(before, updates, after, reference=before, query=query, damage_context=context),))
        assert before.attacker.current_hp == 177 and before.attacker.move_slot(1).current_pp == 30
        assert before.attacker.choice_lock_move_id is None and before.turn_number == 1

    def test_state_key_field_sensitivity(self, state_runner: Path) -> None:
        """state_runner 为真实 ABI；以原 StateKey 核对字段敏感性，不复制 C++ 键编码或哈希算法。"""
        before = _reference()
        first = before.attacker
        variants = [before.next_turn(), replace(before, turn_number=999),
            replace(before, attacker=replace(first, spec=replace(first.spec, name="巨钳螳螂"))),
            before.with_phase(BattlePhase.ACTION_RESOLUTION), before.with_phase(BattlePhase.END_OF_TURN), before.with_phase(BattlePhase.TERMINAL)]
        for changed in (first.with_current_hp(176), first.with_move_slot(first.move_slot(2).with_current_pp(14)),
            first.with_move_slot(first.move_slot(2).with_disabled()), first.with_choice_lock(1), first.with_last_move(165),
            first.with_item_consumed(), first.mark_first_turn_complete(),
            replace(first, move_slots=first.move_slots[::-1]),
            first.with_move_slot(replace(first.move_slot(2), slot_id=99999))):
            variants.append(before.with_battler(BattleSide.ATTACKER, changed))
        for field in ("attack", "defense", "special_attack", "special_defense", "speed", "accuracy", "evasion"):
            variants.append(before.with_battler(BattleSide.ATTACKER, first.with_stat_stages(replace(StatStages(), **{field: 1}))))
        specs = [replace(first.spec, pokemon_id=213), replace(first.spec, types=(Type.STEEL, Type.BUG)),
            replace(first.spec, types=(Type.NORMAL,)), replace(first.spec, item=DamageItem.LIFE_ORB),
            replace(first.spec, can_evolve=True), replace(first.spec, grounding_state=GroundingState.GROUNDED),
            replace(first.spec, grounding_state=GroundingState.AIRBORNE), replace(first.spec, moves=first.spec.moves[::-1])]
        for field in ("hp", "attack", "defense", "special_attack", "special_defense", "speed"):
            specs.append(replace(first.spec, stats=replace(first.spec.stats, **{field: getattr(first.spec.stats, field) + 1})))
        for ability in tuple(DamageAbility)[1:]: specs.append(replace(first.spec, ability=ability))
        move = first.spec.moves[0]
        for configured in (replace(move, move=replace(move.move, name="中文展示")), replace(move, move=replace(move.move, name="")),
                replace(move, move=replace(move.move, type=Type.FIRE)), replace(move, move=replace(move.move, category=MoveCategory.SPECIAL)),
                replace(move, move=replace(move.move, power=41)), replace(move, priority=2), replace(move, accuracy=99),
                replace(move, accuracy=None), replace(move, effect_identifier="fake_out")):
            specs.append(replace(first.spec, moves=(configured, *first.spec.moves[1:])))
        variants.extend(before.with_battler(BattleSide.ATTACKER, replace(first, spec=spec)) for spec in specs)
        expanded_move = replace(move, max_pp=31)
        expanded_spec = replace(first.spec, moves=(expanded_move, *first.spec.moves[1:]))
        expanded_slots = (replace(first.move_slots[0], max_pp=31), *first.move_slots[1:])
        variants.append(before.with_battler(BattleSide.ATTACKER, replace(first, spec=expanded_spec, move_slots=expanded_slots)))
        renamed_move = replace(move, move_id=9001)
        renamed_spec = replace(first.spec, moves=(renamed_move, *first.spec.moves[1:]))
        renamed_slots = (replace(first.move_slots[0], move_id=9001), *first.move_slots[1:])
        variants.append(before.with_battler(BattleSide.ATTACKER, replace(first, spec=renamed_spec, move_slots=renamed_slots)))
        variants.append(replace(before, attacker=replace(first, spec=replace(first.spec, level=51)),
            defender=replace(before.defender, spec=replace(before.defender.spec, level=51)), rules=replace(before.rules, level=51)))
        for status in (CombatantStatus(SleepStatus(2)), CombatantStatus(ParalysisStatus()), CombatantStatus(BurnStatus()), CombatantStatus(FreezeStatus()),
                       CombatantStatus(PoisonStatus()), CombatantStatus(BadPoisonStatus(3)),
                       CombatantStatus(volatile=frozenset((ConfusionStatus(None),))), CombatantStatus(volatile=frozenset((ConfusionStatus(0),))),
                       CombatantStatus(volatile=frozenset((InfatuationStatus(None),))), CombatantStatus(volatile=frozenset((InfatuationStatus(""),))),
                       CombatantStatus(volatile=frozenset((FlinchStatus(),)))):
            variants.append(before.with_battler(BattleSide.ATTACKER, first.with_status(status)))
        for weather in Weather: variants.append(before.with_field(BattleFieldState(weather=weather)))
        for terrain in Terrain: variants.append(before.with_field(BattleFieldState(terrain=terrain)))
        for field in ("attacker_side_conditions", "defender_side_conditions"):
            for screen in ("reflect", "light_screen", "aurora_veil"):
                variants.append(before.with_field(replace(BattleFieldState(), **{field: SideConditions(**{screen: True})})))
        for field in DamagePolicy.__dataclass_fields__:
            old = getattr(before.rules.damage_policy, field)
            changed = (0.8, 1.0) if field == "random_damage_multipliers" else 61 if field == "technician_base_power_threshold" else 1.125
            assert old != changed
            variants.append(replace(before, rules=replace(before.rules, damage_policy=replace(before.rules.damage_policy, **{field: changed}))))
        for rules in (replace(before.rules, ruleset_id="another"), replace(before.rules, version_group_id=31), replace(before.rules, max_turns=None),
                      replace(before.rules, max_turns=101), replace(before.rules, repetition_resolution=RepetitionResolution.CONTINUE),
                      replace(before.rules, cycle_resolution=CycleResolution.SOLVE_ABSORPTION_PROBABILITY),
                      replace(before.rules, move_execution_policy=replace(before.rules.move_execution_policy, struggle_power=51)),
                      replace(before.rules, move_execution_policy=replace(before.rules.move_execution_policy, struggle_recoil_fraction=Fraction(1, 3)))):
            variants.append(replace(before, rules=rules))
        _StateOracle.run(state_runner, tuple(StateCase(value, (), value, reference=before) for value in variants))

    def test_generated_state_updates(self, state_runner: Path) -> None:
        """state_runner 为真实 ABI；1024 组合法不可变更新同时比较完整快照、原键和行动速度。"""
        randomizer = random.Random(27)
        before = _reference()
        cases: list[StateCase] = []
        for index in range(1024):
            side = BattleSide.ATTACKER if index % 2 else BattleSide.DEFENDER
            battler = before.battler(side)
            move = battler.move_slots[index % 4]
            hp, pp = randomizer.randint(0, battler.spec.stats.hp), randomizer.randint(0, move.max_pp)
            stages = StatStages(*(randomizer.randint(-6, 6) for _ in range(7)))
            values = _StateOracle.stages(stages)
            status = CombatantStatus((SleepStatus(index % 5), ParalysisStatus(), BurnStatus(), FreezeStatus(), PoisonStatus(), BadPoisonStatus(index % 15 + 1), None)[index % 7],
                frozenset((ConfusionStatus(index % 4), InfatuationStatus("对手" if index % 2 else None), FlinchStatus())) if index % 3 else frozenset())
            changed = battler.with_current_hp(hp).with_move_slot(move.with_current_pp(pp).with_disabled(bool(index % 2))).with_stat_stages(stages).with_status(status).with_last_move(165)
            after = before.with_battler(side, changed).with_phase(tuple(BattlePhase)[index % 4])
            changes: tuple[Update, ...] = (HpChange(side=side, value=hp), PpChange(side=side, move_id=move.move_id, value=pp),
                DisabledChange(side=side, move_id=move.move_id, value=bool(index % 2)), StagesChange(side=side, value=values),
                StatusChange(side=side, value=_StateOracle.status(status)), MoveIdChange(kind="last_move", side=side, move_id=165), PhaseChange(value=after.phase))
            cases.append(StateCase(before, changes, after, reference=before))
        _StateOracle.run(state_runner, cases)

    def test_exact_status_modifiers(self, state_runner: Path) -> None:
        """state_runner 为真实 ABI；全部代际、六种主状态与非二进制精确倍率对照原 helper。"""
        operations: list[StatusOperation] = []
        expected: list[StatusResponse] = []
        base = Fraction(2, 7)
        for generation in range(1, 10):
            for major in (None, SleepStatus(2), ParalysisStatus(), BurnStatus(), FreezeStatus(), PoisonStatus(), BadPoisonStatus(3)):
                for category in MoveCategory:
                    status = CombatantStatus(major, frozenset((ConfusionStatus(2), InfatuationStatus("source"), FlinchStatus())))
                    for speed in (0, 1, 3, 100, 101, 2147483647):
                        rules = resolve_ruleset_by_generation(generation)
                        rules = replace(rules, damage_policy=replace(rules.damage_policy, burn_physical_attack_multiplier=0.3))
                        move = MoveProfile("probe", category)
                        operations.append(StatusOperation(status=_StateOracle.status(status), speed=speed, generation_id=generation, category=category,
                            base_multiplier=_StateOracle.fraction(base), burn_multiplier=_StateOracle.fraction(Fraction("0.3"))))
                        expected.append(StatusResponse(kind="status_modifiers", status=_StateOracle.status(status),
                            speed=apply_paralysis_speed_modifier(speed, status, rules), burn_multiplier=_StateOracle.fraction(burn_physical_damage_multiplier(status, rules, move)),
                            adjusted_multiplier=_StateOracle.fraction(apply_burn_physical_damage_modifier(base, status, rules, move)), after_switch_out=_StateOracle.status(clear_status_on_switch_out(status))))
        # 自定义精确倍率不局限于代际默认值；200 位分母经过同一 C ABI，不能降为 double。
        for multiplier in (Fraction(1, 3), Fraction(2), Fraction(1, (1 << 200) + 1)):
            for speed in (0, 1, 101, 2147483647):
                status = CombatantStatus(ParalysisStatus())
                rules = resolve_ruleset_by_generation(9)
                rules = replace(rules, status_rules=replace(rules.status_rules,
                    paralysis_policy=replace(rules.status_rules.paralysis_policy, speed_multiplier=multiplier)))
                operations.append(StatusOperation(status=_StateOracle.status(status), speed=speed, generation_id=9, category=MoveCategory.PHYSICAL,
                    base_multiplier=_StateOracle.fraction(base), burn_multiplier=_StateOracle.fraction(Fraction(1, 2)), paralysis_multiplier=_StateOracle.fraction(multiplier)))
                expected.append(StatusResponse(kind="status_modifiers", status=_StateOracle.status(status),
                    speed=apply_paralysis_speed_modifier(speed, status, rules), burn_multiplier=_StateOracle.fraction(Fraction(1)),
                    adjusted_multiplier=_StateOracle.fraction(base), after_switch_out=_StateOracle.status(status)))
        assert _StateOracle.execute(state_runner, operations) == tuple(expected)
