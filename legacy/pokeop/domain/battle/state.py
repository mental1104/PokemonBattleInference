from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import TYPE_CHECKING

from pokeop.domain.battle.context import (
    BattlePokemon,
    DamageContext,
    DamageContextBuilder,
)
from pokeop.domain.battle.environment import BattleEnvironment
from pokeop.domain.battle.inference_outcome import BattleSide
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.items import DamageItem
from pokeop.domain.battle.move_slots import MoveSlotState
from pokeop.domain.battle.side_conditions import SideConditions
from pokeop.domain.battle.specs import (
    InvalidBattleState,
    PokemonSpec,
    PokemonSpecKey,
)
from pokeop.domain.battle.status.state import CombatantStatus
from pokeop.domain.battle.terrain import Terrain
from pokeop.domain.battle.weather import Weather

if TYPE_CHECKING:
    from pokeop.domain.battle.rulesets.models import BattleRuleset


class BattlePhase(str, Enum):
    """表示首版状态节点所处的回合阶段。"""

    ACTION_SELECTION = "action-selection"
    ACTION_RESOLUTION = "action-resolution"
    END_OF_TURN = "end-of-turn"
    TERMINAL = "terminal"


class StatStageField(str, Enum):
    """表示可在战斗中升降的七类能力等级字段。"""

    ATTACK = "attack"
    DEFENSE = "defense"
    SPECIAL_ATTACK = "special_attack"
    SPECIAL_DEFENSE = "special_defense"
    SPEED = "speed"
    ACCURACY = "accuracy"
    EVASION = "evasion"


@dataclass(frozen=True, slots=True)
class StatStages:
    """表示一只出场宝可梦当前的能力等级快照。

    该对象只记录 -6 到 +6 的等级，不在本 Issue 中决定不同世代的倍率公式。
    """

    attack: int = 0
    defense: int = 0
    special_attack: int = 0
    special_defense: int = 0
    speed: int = 0
    accuracy: int = 0
    evasion: int = 0

    def __post_init__(self) -> None:
        """校验全部能力等级均位于游戏允许的闭区间。"""
        for field_name, value in (
            ("attack", self.attack),
            ("defense", self.defense),
            ("special_attack", self.special_attack),
            ("special_defense", self.special_defense),
            ("speed", self.speed),
            ("accuracy", self.accuracy),
            ("evasion", self.evasion),
        ):
            if isinstance(value, bool) or not -6 <= value <= 6:
                raise InvalidBattleState(
                    f"{field_name} stage must be between -6 and 6"
                )

    def value_for(self, field_name: StatStageField) -> int:
        """读取指定能力等级字段。"""
        if not isinstance(field_name, StatStageField):
            raise InvalidBattleState("field_name must be a StatStageField")
        return getattr(self, field_name.value)

    def with_stage(self, field_name: StatStageField, value: int) -> "StatStages":
        """返回只替换一个能力等级的新快照。"""
        if not isinstance(field_name, StatStageField):
            raise InvalidBattleState("field_name must be a StatStageField")
        return replace(self, **{field_name.value: value})


@dataclass(frozen=True, slots=True)
class BattleFieldState:
    """表示按 #20 稳定双方视角保存的天气、场地和边侧状态。

    现有 ``BattleEnvironment`` 使用本次攻击的相对双方语义；当稳定防守方行动时，
    ``damage_environment_for`` 会交换两侧状态后再构造伤害快照。
    """

    weather: Weather | None = None
    terrain: Terrain | None = None
    attacker_side_conditions: SideConditions = field(default_factory=SideConditions)
    defender_side_conditions: SideConditions = field(default_factory=SideConditions)

    def __post_init__(self) -> None:
        """校验场地字段均为显式领域类型。"""
        if self.weather is not None and not isinstance(self.weather, Weather):
            raise InvalidBattleState("weather must be a Weather or None")
        if self.terrain is not None and not isinstance(self.terrain, Terrain):
            raise InvalidBattleState("terrain must be a Terrain or None")
        if not isinstance(self.attacker_side_conditions, SideConditions):
            raise InvalidBattleState(
                "attacker_side_conditions must be SideConditions"
            )
        if not isinstance(self.defender_side_conditions, SideConditions):
            raise InvalidBattleState(
                "defender_side_conditions must be SideConditions"
            )

    def damage_environment_for(self, acting_side: BattleSide) -> BattleEnvironment:
        """按本次行动方向构造现有伤害入口使用的相对环境。"""
        if acting_side is BattleSide.ATTACKER:
            attacker_conditions = self.attacker_side_conditions
            defender_conditions = self.defender_side_conditions
        elif acting_side is BattleSide.DEFENDER:
            attacker_conditions = self.defender_side_conditions
            defender_conditions = self.attacker_side_conditions
        else:
            raise InvalidBattleState("acting_side must be a BattleSide")
        return BattleEnvironment(
            weather=self.weather,
            terrain=self.terrain,
            attacker_side=attacker_conditions,
            defender_side=defender_conditions,
        )


@dataclass(frozen=True, slots=True)
class BattlerStateKey:
    """表示一方所有会影响未来状态转移的规范化键。"""

    spec: PokemonSpecKey
    current_hp: int
    move_slots: tuple[MoveSlotState, ...]
    stat_stages: StatStages
    status: CombatantStatus
    last_move_id: int | None
    choice_lock_move_id: int | None
    item_consumed: bool
    is_first_turn: bool


@dataclass(frozen=True, slots=True, eq=False)
class BattlerState:
    """表示一只出场宝可梦在当前图节点中的完整动态状态。"""

    spec: PokemonSpec
    current_hp: int
    move_slots: tuple[MoveSlotState, ...]
    stat_stages: StatStages = field(default_factory=StatStages)
    status: CombatantStatus = field(default_factory=CombatantStatus)
    last_move_id: int | None = None
    choice_lock_move_id: int | None = None
    item_consumed: bool = False
    is_first_turn: bool = True

    def __post_init__(self) -> None:
        """规范化招式槽并校验 HP、槽位映射与讲究锁招不变量。"""
        if not isinstance(self.spec, PokemonSpec):
            raise InvalidBattleState("spec must be a PokemonSpec")
        if (
            isinstance(self.current_hp, bool)
            or not 0 <= self.current_hp <= self.spec.stats.hp
        ):
            raise InvalidBattleState("current_hp must be between 0 and maximum hp")
        if not isinstance(self.stat_stages, StatStages):
            raise InvalidBattleState("stat_stages must be StatStages")
        if not isinstance(self.status, CombatantStatus):
            raise InvalidBattleState("status must be CombatantStatus")
        if not isinstance(self.item_consumed, bool):
            raise InvalidBattleState("item_consumed must be a bool")
        if not isinstance(self.is_first_turn, bool):
            raise InvalidBattleState("is_first_turn must be a bool")

        normalized_slots = tuple(self.move_slots)
        if any(not isinstance(slot, MoveSlotState) for slot in normalized_slots):
            raise InvalidBattleState("move_slots must contain MoveSlotState values")
        configured_ids = tuple(move.move_id for move in self.spec.moves)
        slot_ids = tuple(slot.move_id for slot in normalized_slots)
        if len(slot_ids) != len(set(slot_ids)):
            raise InvalidBattleState("move slot ids must be unique")
        if len(slot_ids) != len(configured_ids) or set(slot_ids) != set(configured_ids):
            raise InvalidBattleState("move slots must match configured moves exactly")
        for slot in normalized_slots:
            if slot.max_pp != self.spec.move_spec(slot.move_id).max_pp:
                raise InvalidBattleState(
                    "move slot max_pp must match configured move"
                )

        if self.last_move_id is not None and (
            isinstance(self.last_move_id, bool) or self.last_move_id <= 0
        ):
            raise InvalidBattleState("last_move_id must be a positive move id")
        self._validate_choice_lock(normalized_slots, slot_ids)
        object.__setattr__(self, "move_slots", normalized_slots)

    def _validate_choice_lock(
        self,
        slots: tuple[MoveSlotState, ...],
        slot_ids: tuple[int, ...],
    ) -> None:
        """校验讲究锁招 ID、道具和槽位标记保持一致。"""
        locked_slots = tuple(slot for slot in slots if slot.is_locked)
        if self.choice_lock_move_id is None:
            if locked_slots:
                raise InvalidBattleState(
                    "locked move slot requires choice_lock_move_id"
                )
            return
        if self.choice_lock_move_id not in slot_ids:
            raise InvalidBattleState(
                "choice_lock_move_id must reference a configured move"
            )
        if self.spec.item not in (DamageItem.CHOICE_BAND, DamageItem.CHOICE_SPECS):
            raise InvalidBattleState("choice lock requires a supported choice item")
        if self.item_consumed:
            raise InvalidBattleState("consumed item cannot maintain a choice lock")
        if (
            len(locked_slots) != 1
            or locked_slots[0].move_id != self.choice_lock_move_id
        ):
            raise InvalidBattleState(
                "exactly the choice-locked move slot must be locked"
            )

    def move_slot(self, move_id: int) -> MoveSlotState:
        """按招式 ID 读取一个动态招式槽。"""
        for slot in self.move_slots:
            if slot.move_id == move_id:
                return slot
        raise InvalidBattleState(f"move_id {move_id} is not present in move slots")

    def with_current_hp(self, current_hp: int) -> "BattlerState":
        """返回只替换当前 HP 的新状态。"""
        return replace(self, current_hp=current_hp)

    def with_move_slot(self, move_slot: MoveSlotState) -> "BattlerState":
        """按 move_id 替换一个招式槽并返回新状态。"""
        self.spec.move_spec(move_slot.move_id)
        return replace(
            self,
            move_slots=tuple(
                move_slot if old.move_id == move_slot.move_id else old
                for old in self.move_slots
            ),
        )

    def with_status(self, status: CombatantStatus) -> "BattlerState":
        """返回替换主状态与临时状态集合后的新状态。"""
        return replace(self, status=status)

    def with_stat_stages(self, stat_stages: StatStages) -> "BattlerState":
        """返回替换全部能力等级后的新状态。"""
        return replace(self, stat_stages=stat_stages)

    def with_last_move(self, move_id: int | None) -> "BattlerState":
        """返回更新上一招记录后的新状态。"""
        return replace(self, last_move_id=move_id)

    def with_choice_lock(self, move_id: int | None) -> "BattlerState":
        """同步更新讲究锁招 ID 与槽位标记并返回新状态。"""
        updated_slots = tuple(
            replace(slot, is_locked=move_id is not None and slot.move_id == move_id)
            for slot in self.move_slots
        )
        return replace(
            self,
            move_slots=updated_slots,
            choice_lock_move_id=move_id,
        )

    def with_item_consumed(self, consumed: bool = True) -> "BattlerState":
        """返回更新道具消耗状态的新节点。"""
        return replace(self, item_consumed=consumed)

    def mark_first_turn_complete(self) -> "BattlerState":
        """返回首次出场回合标记已清除的新状态。"""
        return replace(self, is_first_turn=False)

    @property
    def state_key(self) -> BattlerStateKey:
        """返回排除展示字段后的规范化战斗方状态键。"""
        return BattlerStateKey(
            spec=self.spec.state_key,
            current_hp=self.current_hp,
            move_slots=self.move_slots,
            stat_stages=self.stat_stages,
            status=self.status,
            last_move_id=self.last_move_id,
            choice_lock_move_id=self.choice_lock_move_id,
            item_consumed=self.item_consumed,
            is_first_turn=self.is_first_turn,
        )

    def __hash__(self) -> int:
        """按规范化状态键计算哈希值。"""
        return hash(self.state_key)

    def __eq__(self, other: object) -> bool:
        """按影响未来结果的字段比较两个战斗方状态。"""
        return isinstance(other, BattlerState) and self.state_key == other.state_key


@dataclass(frozen=True, slots=True)
class StateKey:
    """表示一个 1v1 ``BattleState`` 的稳定图节点键。

    绝对回合号只用于运行保护和展示，不进入语义键；否则同一局面随回合递增后
    无法形成状态图回边。trace、日志、名称和外部资源引用同样不会进入键。
    """

    attacker: BattlerStateKey
    defender: BattlerStateKey
    field: BattleFieldState
    phase: BattlePhase
    rules: BattleInferenceRules


@dataclass(frozen=True, slots=True, eq=False)
class BattleState:
    """表示 1v1 多回合状态图中的一个不可变语义节点。"""

    attacker: BattlerState
    defender: BattlerState
    rules: BattleInferenceRules
    turn_number: int = 1
    field: BattleFieldState = field(default_factory=BattleFieldState)
    phase: BattlePhase = BattlePhase.ACTION_SELECTION

    def __post_init__(self) -> None:
        """校验节点类型、回合号以及双方等级与规则合同一致。"""
        if not isinstance(self.attacker, BattlerState):
            raise InvalidBattleState("attacker must be a BattlerState")
        if not isinstance(self.defender, BattlerState):
            raise InvalidBattleState("defender must be a BattlerState")
        if not isinstance(self.rules, BattleInferenceRules):
            raise InvalidBattleState("rules must be BattleInferenceRules")
        if not isinstance(self.field, BattleFieldState):
            raise InvalidBattleState("field must be BattleFieldState")
        if not isinstance(self.phase, BattlePhase):
            raise InvalidBattleState("phase must be a BattlePhase")
        if isinstance(self.turn_number, bool) or self.turn_number <= 0:
            raise InvalidBattleState("turn_number must be greater than 0")
        if self.attacker.spec.level != self.rules.level:
            raise InvalidBattleState("attacker level must match inference rules")
        if self.defender.spec.level != self.rules.level:
            raise InvalidBattleState("defender level must match inference rules")

    def battler(self, side: BattleSide) -> BattlerState:
        """读取 #20 稳定双方枚举对应的战斗方状态。"""
        if side is BattleSide.ATTACKER:
            return self.attacker
        if side is BattleSide.DEFENDER:
            return self.defender
        raise InvalidBattleState("side must be a BattleSide")

    def opponent(self, side: BattleSide) -> BattlerState:
        """读取指定稳定战斗侧的对手状态。"""
        if side is BattleSide.ATTACKER:
            return self.defender
        if side is BattleSide.DEFENDER:
            return self.attacker
        raise InvalidBattleState("side must be a BattleSide")

    def with_battler(self, side: BattleSide, battler: BattlerState) -> "BattleState":
        """替换稳定双方中的一方并返回新节点。"""
        if not isinstance(battler, BattlerState):
            raise InvalidBattleState("battler must be a BattlerState")
        if side is BattleSide.ATTACKER:
            return replace(self, attacker=battler)
        if side is BattleSide.DEFENDER:
            return replace(self, defender=battler)
        raise InvalidBattleState("side must be a BattleSide")

    def with_phase(self, phase: BattlePhase) -> "BattleState":
        """返回切换到指定回合阶段的新节点。"""
        return replace(self, phase=phase)

    def with_field(self, battle_field: BattleFieldState) -> "BattleState":
        """返回替换天气、场地和边侧状态后的新节点。"""
        return replace(self, field=battle_field)

    def next_turn(self) -> "BattleState":
        """返回进入下一回合行动选择阶段的新节点。"""
        return replace(
            self,
            turn_number=self.turn_number + 1,
            phase=BattlePhase.ACTION_SELECTION,
        )

    def damage_context_for(
        self,
        *,
        acting_side: BattleSide,
        move_id: int,
        damage_ruleset: BattleRuleset | None = None,
        is_critical: bool = False,
        is_spread_move: bool = False,
        is_protect_reduced: bool = False,
        is_multi_target_battle: bool = False,
    ) -> DamageContext:
        """从当前节点构造现有单次伤害入口使用的只读快照。

        当前旧 ``DamageContext`` 尚未直接承载能力等级与 ``CombatantStatus``；这些
        字段继续保留在 ``BattlerState``，本转换不会改写或丢弃原状态对象。
        """
        attacker = self.battler(acting_side)
        defender = self.opponent(acting_side)
        move_slot = attacker.move_slot(move_id)
        if move_slot.current_pp <= 0:
            raise InvalidBattleState("damage move must have remaining pp")
        if move_slot.is_disabled:
            raise InvalidBattleState("disabled move cannot build a damage context")
        if (
            attacker.choice_lock_move_id is not None
            and attacker.choice_lock_move_id != move_id
        ):
            raise InvalidBattleState("move_id violates the current choice lock")

        configured_move = attacker.spec.move_spec(move_id)
        builder = DamageContextBuilder.for_move(
            attacker=self._battle_pokemon_snapshot(attacker),
            defender=self._battle_pokemon_snapshot(defender),
            move=configured_move.move,
        ).with_environment(self.field.damage_environment_for(acting_side))
        if damage_ruleset is not None:
            builder = builder.with_ruleset(damage_ruleset)
        if is_critical:
            builder = builder.with_critical_hit()
        if is_spread_move:
            builder = builder.as_spread_move()
        if is_protect_reduced:
            builder = builder.with_protect_reduction()
        if is_multi_target_battle:
            builder = builder.in_multi_target_battle()
        return builder.build()

    @staticmethod
    def _battle_pokemon_snapshot(battler: BattlerState) -> BattlePokemon:
        """把一方状态转换为旧伤害入口消费的 ``BattlePokemon``。"""
        return BattlePokemon(
            name=battler.spec.name,
            level=battler.spec.level,
            types=battler.spec.types,
            stats=battler.spec.stats,
            ability=battler.spec.ability,
            item=DamageItem.UNKNOWN if battler.item_consumed else battler.spec.item,
            can_evolve=battler.spec.can_evolve,
            grounding_state=battler.spec.grounding_state,
        )

    @property
    def state_key(self) -> StateKey:
        """生成用于状态图去重的规范化键。"""
        return StateKey(
            attacker=self.attacker.state_key,
            defender=self.defender.state_key,
            field=self.field,
            phase=self.phase,
            rules=self.rules,
        )

    def __hash__(self) -> int:
        """按 ``StateKey`` 计算哈希值。"""
        return hash(self.state_key)

    def __eq__(self, other: object) -> bool:
        """按语义键比较节点，忽略绝对回合号和展示字段。"""
        return isinstance(other, BattleState) and self.state_key == other.state_key


__all__ = [
    "BattleFieldState",
    "BattlePhase",
    "BattleState",
    "BattlerState",
    "BattlerStateKey",
    "StateKey",
    "StatStageField",
    "StatStages",
]
