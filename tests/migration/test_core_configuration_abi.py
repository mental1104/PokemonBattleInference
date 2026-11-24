"""通过正式 C ABI 对照旧 provider 的完整配置空间，不在测试中复制枚举或权重规则。"""
from __future__ import annotations

import random
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from pokeop.application.battle_inference_effect_factory import TransparentPokemonChampionEffectFactory
from pokeop.application.configuration_space.commands import (
    AbilitySpaceCommand, ItemSpaceCommand, MoveSpaceCommand, PokemonSpaceCommand, StatSpaceCommand,
)
from pokeop.application.configuration_space.model_base import ConfigurationWeightAssumption, StatEnumerationMode
from pokeop.application.configuration_space.generator import PokemonConfigurationGenerator
from pokeop.application.configuration_space.projections import AbilityConfigurationCandidate
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.factories import PokemonChampionEffectFactory
from pokeop.domain.battle.effects.protocols import EffectCoverage, EffectCoverageStatus
from pokeop.domain.battle.stats import NatureModifier, StatValues
from pokeop.domain.models.pokemon_fields import StatField
from pokeop.domain.models.types import Type
from tests.application.configuration_space.helpers import _dragonite_profile, _move
from tests.migration.test_core_configuration_moves import (
    Candidate, Coverage, Move, MoveInput, _Case as _MoveCase, _Oracle as _MoveOracle,
)
from tests.migration.test_core_configuration_space import (
    Ability, ConfigurationClass, PairClass, SideCoverage, SideReply, SpaceReply,
    _Case as _SpaceCase, _Oracle as _SpaceOracle, _Side,
)
from tests.migration.test_core_configuration_stats import (
    Nature, StatInput, _Case as _StatCase, _Oracle as _StatOracle,
)
from tests.migration.test_core_damage import ExactFraction, MoveSnapshot, damage_runner
from tests.migration.test_core_state import MoveSpecSnapshot


class _Contract(BaseModel):
    """冻结全部正式传输字段，拒绝额外字段，JSON不进入内部oracle算法。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class Profile(_Contract):
    """原始完整投入与五轴性格，尚未计算实际能力。"""
    ivs: StatValues
    evs: StatValues
    nature: Nature


class Preset(_Contract):
    """第一代表标签独立于归并行为。"""
    profile: Profile
    label: str


class PresetEnumeration(_Contract):
    """已经由原应用解析完成的完整preset列表。"""
    mode: Literal["preset"] = "preset"
    presets: tuple[Preset, ...]


class ControlledEnumeration(_Contract):
    """完整受控命令，未在适配器执行product或过滤。"""
    mode: Literal["controlled"] = "controlled"
    fields: tuple[StatField, ...]
    ev_values: tuple[int, ...]
    natures: tuple[Nature, ...]


class StatsInput(_Contract):
    """正式能力请求的完整内部input。"""
    base: StatValues
    level: int
    enumeration: Annotated[PresetEnumeration | ControlledEnumeration, Field(discriminator="mode")]
    max_raw_profiles: int


class MoveCandidate(_Contract):
    """完整repository合法候选；执行招式与provider效果保持独立。"""
    move_id: int
    identifier: str
    move: MoveSpecSnapshot | None
    effect_identifier: str | None
    support: Literal["supported", "partial", "unsupported"]
    reason: str


class MovesInput(_Contract):
    """真实招式组合命令，不传入预先生成的组合。"""
    candidates: tuple[MoveCandidate, ...]
    requested_ids: tuple[int, ...]
    slot_counts: tuple[int, ...]
    max_raw_combinations: int


class SideInput(_Contract):
    """正式单侧四维知识快照及完整过滤命令。"""
    ruleset_id: str
    version_group_id: int
    pokemon_id: int
    name: str
    types: tuple[int, ...]
    can_evolve: bool
    moves: MovesInput
    stats: StatsInput
    abilities: tuple[Ability, ...]
    requested_abilities: tuple[str, ...]
    items: tuple[str | None, ...]
    max_raw_configurations: int


class SpaceInput(_Contract):
    """双方完整候选输入和归并前原始pair预算。"""
    attacker: SideInput
    defender: SideInput
    weight_assumption: ConfigurationWeightAssumption
    max_raw_pairs: int


class StatsOperation(_Contract):
    """正式能力枚举操作。"""
    kind: Literal["configuration_stats"] = "configuration_stats"
    input: StatsInput


class MovesOperation(_Contract):
    """正式招式枚举操作。"""
    kind: Literal["configuration_moves"] = "configuration_moves"
    input: MovesInput


class SpaceOperation(_Contract):
    """正式通用配置空间操作，不冒充job-v1具体case。"""
    kind: Literal["configuration_space"] = "configuration_space"
    input: SpaceInput


class DescriptionInput(_Contract):
    """独立标准/透明factory查询，显式区分三类来源。"""
    mode: Literal["describe"] = "describe"
    factory: Literal["standard", "transparent_inference"]
    moves: tuple[str | None, ...]
    abilities: tuple[str | None, ...]
    items: tuple[str | None, ...]


class CoverageOperation(_Contract):
    """描述操作，未知/缺失效果仍返回完整coverage。"""
    kind: Literal["configuration_coverage"] = "configuration_coverage"
    input: DescriptionInput


class Batch(_Contract):
    """有界正式ABI批次，原输入顺序不可改变。"""
    schema_version: Literal[1] = 1
    operations: tuple[Annotated[StatsOperation | MovesOperation | SpaceOperation | CoverageOperation, Field(discriminator="kind")], ...]


class Effect(_Contract):
    """完整factory事实，包括overall supported遮不住的子能力缺口。"""
    identifier: str
    status: EffectCoverageStatus
    reason: str
    missing_capabilities: tuple[str, ...]


class Repository(_Contract):
    """repository原始支持事实，不能用factory reason覆盖掉。"""
    support: Literal["supported", "partial", "unsupported"]
    reason: str


class MoveDescription(_Contract):
    """原合法招式身份、repository和factory的完整分离快照。"""
    source: Literal["move"]
    identifier: str
    move_id: int
    repository: Repository
    factory: Effect


class AbilityDescription(_Contract):
    """完整合法特性repository事实及独立factory描述。"""
    source: Literal["ability"]
    identifier: str
    repository: Repository
    factory: Effect


class ItemDescription(_Contract):
    """显式受控道具的完整factory描述。"""
    source: Literal["item"]
    factory: Effect


class StatClass(_Contract):
    """第一代表、实际能力与原始成员数全部保留。"""
    representative: Profile
    actual: StatValues
    label: str
    member_count: str


class ConfiguredMove(_Contract):
    """完整实际招式字段和独立效果身份。"""
    spec: MoveSpecSnapshot
    effect_identifier: str | None
    key: str


class MoveClass(_Contract):
    """无序招式组合及原始成员数，不只比较组合数量。"""
    moves: tuple[ConfiguredMove, ...]
    member_count: str


class StatsResult(_Contract):
    """完整正式能力结果。"""
    kind: Literal["configuration_stats"]
    classes: tuple[StatClass, ...]
    raw_profile_count: str


class MovesResult(_Contract):
    """全部组合、所有纳入/排除事实、原repository和factory原因。"""
    kind: Literal["configuration_moves"]
    classes: tuple[MoveClass, ...]
    coverage: tuple[Coverage, ...]
    candidate_descriptions: tuple[MoveDescription, ...]
    raw_combination_count: str


class Pokemon(_Contract):
    """空间所属原知识身份与完整属性，不从类排序键反解析。"""
    ruleset_id: str
    version_group_id: int
    pokemon_id: int
    name: str
    types: tuple[int, ...]
    level: int
    can_evolve: bool


class PokemonClass(_Contract):
    """完整四维第一代表，保留具体招式ID和实际能力。"""
    key: str
    member_count: str
    moves: MoveClass
    stats: StatClass
    ability: str
    item: str


class DimensionCoverage(Coverage):
    """正式协议来源与原provider维度名分别投影。"""
    dimension: Literal["move", "ability", "item"]


class SideResult(_Contract):
    """完整单侧空间，不允许吞掉新增字段。"""
    pokemon: Pokemon
    classes: tuple[PokemonClass, ...]
    coverage: tuple[DimensionCoverage, ...]
    candidate_descriptions: tuple[Annotated[MoveDescription | AbilityDescription | ItemDescription, Field(discriminator="source")], ...]
    raw_configuration_count: str


class Pair(_Contract):
    """下标明确引用同结果的双方拥有类，权重不经过float。"""
    attacker_class: int
    defender_class: int
    member_count: str
    weight: ExactFraction


class SpaceResult(_Contract):
    """完整配置对分区。"""
    kind: Literal["configuration_space"]
    attacker: SideResult
    defender: SideResult
    pairs: tuple[Pair, ...]
    raw_pair_count: str
    weight_assumption: ConfigurationWeightAssumption


class QueriedEffect(Effect):
    """正式描述查询额外保留来源及明确factory选择。"""
    source: Literal["move", "ability", "item"]
    factory: Literal["standard", "transparent_inference"]


class CoverageResult(_Contract):
    """原始顺序的全部机制描述。"""
    kind: Literal["configuration_coverage"]
    mode: Literal["describe"]
    effects: tuple[QueriedEffect, ...]


class Envelope(_Contract):
    """当前正式版本和严格成功结果；不能将错误伪装为空结果。"""
    schema_version: Literal[1]
    engine_version: Literal["0.10.0"]
    rules_version: Literal["calculation-rules.v10"]
    results: tuple[Annotated[StatsResult | MovesResult | SpaceResult | CoverageResult, Field(discriminator="kind")], ...]


class _ABI:
    """仅转换wire形状，所有算法预期取自旧provider和旧真实factory。"""
    @staticmethod
    def stats(value: StatInput) -> StatsInput:
        """value为旧oracle读取的快照；返回未计算的正式typed能力命令。"""
        enumeration = PresetEnumeration(presets=tuple(Preset(profile=Profile(ivs=StatValues(*item.ivs),
            evs=StatValues(*item.evs), nature=item.nature), label=item.label) for item in value.presets)) if value.mode == "preset" else ControlledEnumeration(
                fields=tuple(tuple(StatField)[index] for index in value.fields), ev_values=value.ev_values, natures=value.natures)
        return StatsInput(base=StatValues(*value.base), level=value.level, enumeration=enumeration, max_raw_profiles=value.max_raw_profiles)

    @staticmethod
    def move(value: Move) -> MoveSpecSnapshot:
        """value为原招式快照；只变换嵌套字段，不推断任何机制。"""
        return MoveSpecSnapshot(move_id=value.move_id, name=value.name, move=MoveSnapshot(type=value.type,
            category=tuple(MoveCategory)[value.category], power=value.power), max_pp=value.max_pp,
            priority=value.priority, accuracy=value.accuracy, effect_identifier=value.effect_identifier)

    @classmethod
    def moves(cls, value: MoveInput) -> MovesInput:
        """完整合法候选逐个投影，保留所有unsupported和重复projection。"""
        return MovesInput(candidates=tuple(MoveCandidate(move_id=item.move_id, identifier=item.identifier,
            move=None if item.move is None else cls.move(item.move), effect_identifier=item.effect_identifier,
            support=item.support.value, reason=item.reason) for item in value.candidates), requested_ids=value.requested_ids,
            slot_counts=value.slot_counts, max_raw_combinations=value.max_raw_combinations)

    @classmethod
    def side(cls, value: _Side) -> SideInput:
        """value为原知识/命令组合；只从原oracle的读取结果转换DTO。"""
        source = _SpaceOracle.side_request(value)
        return SideInput(ruleset_id=source.ruleset_id, version_group_id=source.version_group_id,
            pokemon_id=source.pokemon_id, name=source.name, types=source.types, can_evolve=source.can_evolve,
            moves=cls.moves(source.moves), stats=cls.stats(source.stats), abilities=source.abilities,
            requested_abilities=source.requested_abilities, items=source.items, max_raw_configurations=source.max_raw_configurations)

    @staticmethod
    def run(runner: Path, operations: tuple[StatsOperation | MovesOperation | SpaceOperation | CoverageOperation, ...]) -> tuple[StatsResult | MovesResult | SpaceResult | CoverageResult, ...]:
        """runner为实际ABI可执行程序；每条独立批次全量解码并保持原顺序。"""
        process = subprocess.run([str(runner.parent / "pbi_abi_vectors")],
            input="".join(Batch(operations=(operation,)).model_dump_json() + "\n" for operation in operations),
            text=True, capture_output=True, check=True, timeout=120)
        lines = process.stdout.splitlines(); assert len(lines) == len(operations)
        envelopes = tuple(Envelope.model_validate_json(line) for line in lines)
        assert all(len(item.results) == 1 for item in envelopes)
        return tuple(item.results[0] for item in envelopes)

    @staticmethod
    def effect(value: EffectCoverage) -> Effect:
        """原factory元数据直接投影全部缺失子能力，不重写支持规则。"""
        return Effect(identifier=value.identifier, status=value.status, reason=value.reason,
            missing_capabilities=tuple(dict.fromkeys(value.unsupported_aspects + tuple(item.identifier for item in value.unsupported_capabilities))))

    @classmethod
    def check_descriptions(cls, descriptions: tuple[MoveDescription, ...], candidates: tuple[Candidate, ...]) -> None:
        """逐个比较原repository理由和原factory产品，包括被命令排除的合法候选。"""
        assert len(descriptions) == len(candidates)
        factory = PokemonChampionEffectFactory()
        for actual, candidate in zip(descriptions, candidates, strict=True):
            effect = candidate.effect_identifier or (candidate.move.effect_identifier if candidate.move is not None else None)
            assert actual.move_id == candidate.move_id and actual.identifier == candidate.identifier
            assert actual.repository == Repository(support=candidate.support.value, reason=candidate.reason)
            assert actual.factory == cls.effect(factory.create_move_effect(effect).coverage)

    @staticmethod
    def project_side(value: SideResult) -> SideReply:
        """正式丰富结果投影为原oracle字段；不改变排序、成员数或代表。"""
        return SideReply(classes=tuple(ConfigurationClass(key=item.key, member_count=item.member_count,
            ivs=_StatOracle.values(item.stats.representative.ivs), evs=_StatOracle.values(item.stats.representative.evs),
            nature=item.stats.representative.nature, stat_label=item.stats.label,
            move_names=tuple(move.spec.name for move in item.moves.moves)) for item in value.classes),
            coverage=tuple(SideCoverage(dimension="moves" if item.dimension == "move" else item.dimension,
                identifier=item.identifier, support=item.support, included=item.included, reason=item.reason,
                factory_status=item.factory_status) for item in value.coverage), raw_configuration_count=value.raw_configuration_count)

    @classmethod
    def check_rich_side(cls, actual: SideResult, source: _Side, side: Literal["attacker", "defender"]) -> None:
        """逐字段核对丰富代表、嵌套维度计数和全部原描述，不只检查repr排序键。"""
        original = PokemonConfigurationGenerator(PokemonChampionEffectFactory()).generate(source.profile, source.command, side=side)
        stats = _StatOracle.reference(_StatCase(_StatOracle.values(source.profile.base_stats), source.command.level, source.command.stats))
        moves = _MoveOracle.reference(_MoveCase(source.profile.moves, source.command.moves))
        assert len(actual.classes) == len(original.equivalence_classes)
        for value, old in zip(actual.classes, original.equivalence_classes, strict=True):
            configuration = old.representative
            assert value.stats.actual == configuration.stats
            assert value.stats.representative == Profile(ivs=configuration.stat_profile.ivs, evs=configuration.stat_profile.evs,
                nature=_StatOracle.nature(configuration.stat_profile.nature_modifier))
            expected_stat = next(item for item in stats.classes if StatValues(*item.actual) == configuration.stats)
            assert (value.stats.member_count, value.stats.label) == (expected_stat.member_count, expected_stat.label)
            assert (value.ability, value.item) == (configuration.ability_identifier, configuration.item_identifier)
            expected_moves = next(item for item in moves.classes if tuple(move.key for move in item.moves) == tuple(repr(move.behavior_signature) for move in configuration.moves))
            assert value.moves.member_count == expected_moves.member_count
            assert len(value.moves.moves) == len(configuration.moves)
            for move, old_move in zip(value.moves.moves, configuration.moves, strict=True):
                spec = old_move.move_spec
                expected = MoveSpecSnapshot(move_id=spec.move_id, name=spec.move.name,
                    move=MoveSnapshot(type=spec.move.type, category=spec.move.category, power=spec.move.power),
                    max_pp=spec.max_pp, priority=spec.priority, accuracy=spec.accuracy, effect_identifier=spec.effect_identifier)
                assert move.spec == expected and move.effect_identifier == old_move.effect_identifier
        assert actual.pokemon == Pokemon(ruleset_id=source.profile.ruleset_id, version_group_id=source.profile.version_group_id,
            pokemon_id=source.profile.pokemon_id, name=source.profile.name, types=tuple(value.value for value in source.profile.types),
            level=source.command.level, can_evolve=source.profile.can_evolve)
        expected_abilities = source.profile.abilities
        descriptions = tuple(item for item in actual.candidate_descriptions if isinstance(item, AbilityDescription))
        assert len(descriptions) == len(expected_abilities)
        factory = PokemonChampionEffectFactory()
        for value, ability in zip(descriptions, expected_abilities, strict=True):
            assert value.identifier == ability.identifier
            assert value.repository == Repository(support=ability.support_status.value, reason=ability.support_reason)
            assert value.factory == cls.effect(factory.create_ability_effect(ability.identifier).coverage)
        item_descriptions = tuple(item for item in actual.candidate_descriptions if isinstance(item, ItemDescription))
        assert tuple(value.factory for value in item_descriptions) == tuple(cls.effect(factory.create_item_effect(item).coverage) for item in source.command.items.candidate_identifiers)


class TestCoreConfigurationABI:
    """正式ABI的真实provider/factory差分，补上纯Core进程测试之外的边界验证。"""
    def test_stat_wire_preserves_all_profiles(self, damage_runner: Path) -> None:
        """比较64个受控与预设案例，包括原单增无降、有符号零和次正规性格。"""
        rng = random.Random(73149)
        cases: list[_StatCase] = []
        for index in range(64):
            nature = NatureModifier(attack=(1.1, -0.0, 5e-324, -0.125)[index % 4])
            command = StatSpaceCommand(preset_keys=("max_atk_plus", "max_hp", "max_hp_def_plus")) if index % 8 == 0 else StatSpaceCommand(
                mode=StatEnumerationMode.CONTROLLED, preset_keys=(), relevant_fields=tuple(rng.sample(tuple(StatField), rng.randint(1, 3))),
                ev_values=(0, 1, 4, 252), nature_modifiers=(nature,))
            cases.append(_StatCase(tuple(rng.randint(1, 255) for _ in range(6)), rng.choice((1, 50, 100)), command))
        results = _ABI.run(damage_runner, tuple(StatsOperation(input=_ABI.stats(_StatOracle.request(case))) for case in cases))
        for case, actual in zip(cases, results, strict=True):
            assert isinstance(actual, StatsResult)
            reference = _StatOracle.reference(case)
            assert actual.raw_profile_count == reference.raw_profile_count
            assert len(actual.classes) == len(reference.classes)
            for value, expected in zip(actual.classes, reference.classes, strict=True):
                assert value.actual == StatValues(*expected.actual)
                assert value.representative == Profile(ivs=StatValues(*expected.ivs), evs=StatValues(*expected.evs), nature=expected.nature)
                assert (value.label, value.member_count) == (expected.label, expected.member_count)

    def test_move_wire_keeps_complete_coverage(self, damage_runner: Path) -> None:
        """真实过滤、原始重复成员、具体ID与所有repository/factory理由全量对照。"""
        original = _dragonite_profile().moves
        cases = tuple(_MoveCase(original + original[:1], MoveSpaceCommand(slot_counts=slots,
            candidate_move_ids=ids)) for slots in ((), (1,), (1, 2), (2,)) for ids in ((), (245,), (8, 245)))
        inputs = tuple(_MoveOracle.request(case) for case in cases)
        results = _ABI.run(damage_runner, tuple(MovesOperation(input=_ABI.moves(value)) for value in inputs))
        for case, source, actual in zip(cases, inputs, results, strict=True):
            assert isinstance(actual, MovesResult); expected = _MoveOracle.reference(case)
            assert actual.raw_combination_count == expected.raw_combination_count and actual.coverage == expected.coverage
            assert len(actual.classes) == len(expected.classes)
            for value, reference in zip(actual.classes, expected.classes, strict=True):
                assert value.member_count == reference.member_count
                assert tuple((move.key, move.spec.name) for move in value.moves) == tuple((move.key, move.name) for move in reference.moves)
                for move in value.moves:
                    assert any(candidate.move is not None and move.spec == _ABI.move(candidate.move) for candidate in source.candidates)
            _ABI.check_descriptions(actual.candidate_descriptions, source.candidates)

    def test_space_wire_keeps_exact_original_weights(self, damage_runner: Path) -> None:
        """完整双方分区/顺序/代表/成员/权重与原实际用例逐字段一致。"""
        profile = replace(_dragonite_profile(), abilities=(AbilityConfigurationCandidate("multiscale"),
            AbilityConfigurationCandidate("Multiscale"), AbilityConfigurationCandidate("technician"),
            AbilityConfigurationCandidate("inner-focus"), AbilityConfigurationCandidate("pressure")),
            moves=(_move(245, "extreme-speed", Type.NORMAL, 80, pp=5, priority=2),
                   _move(8, "ice-punch", Type.ICE, 75, effect_identifier="ice_punch")))
        sides = tuple(_Side(profile, PokemonSpaceCommand(moves=MoveSpaceCommand(slot_counts=(1,)),
            stats=StatSpaceCommand(mode=StatEnumerationMode.CONTROLLED, preset_keys=(), relevant_fields=(StatField.ATTACK,),
                ev_values=(0, 1, 4), nature_modifiers=(NatureModifier.neutral(), NatureModifier.increase(StatField.ATTACK))),
            abilities=AbilitySpaceCommand(), items=ItemSpaceCommand(items), level=level)) for items in ((None,), (None, "choice-band")) for level in (1, 50))
        cases = tuple(_SpaceCase(first, second, assumption) for first in sides for second in sides for assumption in ConfigurationWeightAssumption)
        operations = tuple(SpaceOperation(input=SpaceInput(attacker=_ABI.side(case.attacker), defender=_ABI.side(case.defender),
            weight_assumption=case.assumption, max_raw_pairs=case.max_raw_pairs)) for case in cases)
        results = _ABI.run(damage_runner, operations)
        for case, actual in zip(cases, results, strict=True):
            assert isinstance(actual, SpaceResult)
            projected = SpaceReply(attacker=_ABI.project_side(actual.attacker), defender=_ABI.project_side(actual.defender),
                raw_pair_count=actual.raw_pair_count, pairs=tuple(PairClass(attacker_key=actual.attacker.classes[pair.attacker_class].key,
                    defender_key=actual.defender.classes[pair.defender_class].key, member_count=pair.member_count,
                    numerator=pair.weight.numerator, denominator=pair.weight.denominator) for pair in actual.pairs))
            assert projected == _SpaceOracle.reference(case) and actual.weight_assumption is case.assumption
            for source, side, name in ((case.attacker, actual.attacker, "attacker"), (case.defender, actual.defender, "defender")):
                move_descriptions = tuple(item for item in side.candidate_descriptions if isinstance(item, MoveDescription))
                _ABI.check_descriptions(move_descriptions, _SpaceOracle.side_request(source).moves.candidates)
                _ABI.check_rich_side(side, source, name)

    def test_factory_description_wire_is_complete(self, damage_runner: Path) -> None:
        """两个真实factory的完整状态/原文原因/缺失能力逐字段相同，含透明占位。"""
        operations = tuple(CoverageOperation(input=DescriptionInput(factory=factory,
            moves=(None, "ice-punch", "fake-out", "brick-break", "unknown"),
            abilities=(None, "multiscale", "inner-focus", "pressure", "pickpocket", "unknown"),
            items=(None, "choice-band", "life-orb", "unknown"))) for factory in ("standard", "transparent_inference"))
        results = _ABI.run(damage_runner, operations)
        for operation, actual in zip(operations, results, strict=True):
            assert isinstance(actual, CoverageResult)
            factory = PokemonChampionEffectFactory() if operation.input.factory == "standard" else TransparentPokemonChampionEffectFactory()
            expected = tuple(("move", factory.create_move_effect(identifier).coverage) for identifier in operation.input.moves)
            expected += tuple(("ability", factory.create_ability_effect(identifier).coverage) for identifier in operation.input.abilities)
            expected += tuple(("item", factory.create_item_effect(identifier).coverage) for identifier in operation.input.items)
            assert len(actual.effects) == len(expected)
            for value, (source, reference) in zip(actual.effects, expected, strict=True):
                assert value.source == source and value.factory == operation.input.factory
                assert Effect(identifier=value.identifier, status=value.status, reason=value.reason,
                    missing_capabilities=value.missing_capabilities) == _ABI.effect(reference)
