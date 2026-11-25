"""真实原 repository 装饰器与透明/标准 provider 的完整配置差分。"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pokeop.application.battle_inference_effect_factory import TransparentPokemonChampionEffectFactory
from pokeop.application.composition.battle_inference_repository import FactoryReconciledBattleInferenceRepository
from pokeop.application.configuration_space.commands import AbilitySpaceCommand, GenerateConfigurationSpaceCommand, ItemSpaceCommand, MoveSpaceCommand, PokemonSpaceCommand, StatSpaceCommand
from pokeop.application.configuration_space.generator import GenerateConfigurationSpaceUseCase, PokemonConfigurationGenerator
from pokeop.application.configuration_space.model_base import ConfigurationWeightAssumption, StatEnumerationMode
from pokeop.application.repositories.battle_inference import BattleInferencePokemonProfile, MechanismSupportStatus
from pokeop.application.use_cases.infer_one_on_one_battle._core import InferOneOnOneBattleUseCase
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.factories import BattleEffectAbstractFactory, PokemonChampionEffectFactory
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.domain.battle.stats import NatureModifier
from pokeop.domain.models.pokemon_fields import StatField
from tests.application.composition.test_battle_inference_repository import _Repository, _capability, _profile
from tests.migration.test_core_configuration_space import ErrorReply, PairClass, SideInput, SpaceReply, _Contract, _Oracle, _Side, configuration_space_runner


class _ContextSideInput(SideInput):
    """保留原完整候选，新增两项显式 composition；不预过滤或提升候选。"""
    factory: Literal["standard", "transparent_inference"]
    repository_mode: Literal["raw", "factory_reconciled"]


class _ContextSpaceInput(_Contract):
    """双方可采用不同真实 generator，全部计算仍交给 Core。"""
    attacker: _ContextSideInput
    defender: _ContextSideInput
    weight_assumption: ConfigurationWeightAssumption
    max_raw_pairs: int = 1000000


@dataclass
class _RawRepository(_Repository):
    """真实装饰器的只读原 profile 端口，不在测试中模拟 reconciliation。"""
    profile: BattleInferencePokemonProfile

    def get_pokemon_profile(self, *, ruleset_id: str, version_group_id: int, pokemon_id: int) -> BattleInferencePokemonProfile:
        """参数为原 repository 三轴；返回未过滤、未对账的原 profile。"""
        return self.profile


@dataclass(frozen=True)
class _ContextSide:
    """原 PG projection、命令及真实 composition 的独立输入事实。"""
    raw: BattleInferencePokemonProfile
    command: PokemonSpaceCommand
    factory: Literal["standard", "transparent_inference"]
    repository_mode: Literal["raw", "factory_reconciled"]

    def effect_factory(self) -> BattleEffectAbstractFactory:
        """返回原正式工厂，不自建支持列表或复刻覆盖。"""
        return TransparentPokemonChampionEffectFactory() if self.factory == "transparent_inference" else PokemonChampionEffectFactory()

    def side(self, *, reconciled: bool) -> _Side:
        """reconciled 控制原 source oracle 装饰器；Core 输入始终使用 raw。"""
        profile = self.raw
        if reconciled and self.repository_mode == "factory_reconciled":
            loaded = FactoryReconciledBattleInferenceRepository(_RawRepository(profile), self.effect_factory()).get_pokemon_profile(
                ruleset_id="pokemon-champion", version_group_id=25, pokemon_id=profile.pokemon_id)
            assert loaded is not None
            profile = loaded
        return _Side(InferOneOnOneBattleUseCase._configuration_profile(profile, BattleInferenceRules()), self.command)

    def request(self) -> _ContextSideInput:
        """机械投影 raw 合法候选；promotion、factory 过滤和组合均在 Core 执行。"""
        return _ContextSideInput(**_Oracle.side_request(self.side(reconciled=False)).model_dump(),
            factory=self.factory, repository_mode=self.repository_mode)


class _ContextOracle:
    """实际 composition→provider→归并→两种精确权重的原完整入口。"""

    @staticmethod
    def profile(status: MechanismSupportStatus) -> BattleInferencePokemonProfile:
        """status 是原 repository 三态；返回含附加效果、纯伤害、动态基础缺口的合法知识。"""
        original = _profile()
        base_move = original.moves[0]
        moves = (
            replace(base_move, move_id=245, identifier="extreme-speed", display_name="Extreme Speed", effect_identifier=None,
                capability=_capability(EffectSourceKind.MOVE, "extreme-speed", MechanismSupportStatus.SUPPORTED)),
            replace(base_move, capability=_capability(EffectSourceKind.MOVE, "ice-punch", status)),
            replace(base_move, move_id=252, identifier="fake-out", display_name="Fake Out", effect_identifier="fake-out",
                capability=_capability(EffectSourceKind.MOVE, "fake-out", status)),
            replace(base_move, move_id=33, identifier="tackle", display_name="Tackle", effect_identifier=None,
                capability=_capability(EffectSourceKind.MOVE, "tackle", status)),
            original.moves[1],
            replace(base_move, move_id=150, identifier="splash", display_name="Splash", category=MoveCategory.STATUS, power=None,
                effect_identifier=None, capability=_capability(EffectSourceKind.MOVE, "splash", MechanismSupportStatus.UNSUPPORTED)),
        )
        abilities = tuple(replace(original.abilities[0], ability_id=100 + index, identifier=identifier, effect_identifier=identifier,
            capability=_capability(EffectSourceKind.ABILITY, identifier, MechanismSupportStatus.SUPPORTED if identifier == "technician" else status))
            for index, identifier in enumerate(("technician", "pressure", "pickpocket", "inner-focus")))
        return replace(original, moves=moves, abilities=abilities)

    @staticmethod
    def command(requested: tuple[str, ...] = ()) -> PokemonSpaceCommand:
        """requested 为原命令特性池；其余维度小而真实，保留首代表和成员权重。"""
        return PokemonSpaceCommand(moves=MoveSpaceCommand(slot_counts=(1,)),
            stats=StatSpaceCommand(mode=StatEnumerationMode.CONTROLLED, preset_keys=(), relevant_fields=(StatField.HP,),
                ev_values=(0, 1), nature_modifiers=(NatureModifier.neutral(),)),
            abilities=AbilitySpaceCommand(requested), items=ItemSpaceCommand((None, "life-orb")), level=50)

    @staticmethod
    def reference(attacker: _ContextSide, defender: _ContextSide, assumption: ConfigurationWeightAssumption) -> SpaceReply | ErrorReply:
        """两侧为真实原事实；直接调用原装饰器和生成器，返回全部行为、覆盖与原错误。"""
        first, second = attacker.side(reconciled=True), defender.side(reconciled=True)
        first_generator, second_generator = PokemonConfigurationGenerator(attacker.effect_factory()), PokemonConfigurationGenerator(defender.effect_factory())
        try:
            left = first_generator.generate(first.profile, first.command, side="attacker")
            right = second_generator.generate(second.profile, second.command, side="defender")
            result = GenerateConfigurationSpaceUseCase(first_generator, second_generator).execute(
                GenerateConfigurationSpaceCommand(attacker=first.command, defender=second.command, weight_assumption=assumption),
                attacker_profile=first.profile, defender_profile=second.profile)
            return SpaceReply(attacker=_Oracle.side_reply(left), defender=_Oracle.side_reply(right), raw_pair_count=str(result.statistics.raw_configuration_count),
                pairs=tuple(PairClass(attacker_key=repr(value.representative.attacker.behavior_signature),
                    defender_key=repr(value.representative.defender.behavior_signature), member_count=str(value.member_count),
                    numerator=str(value.weight.value.numerator), denominator=str(value.weight.value.denominator)) for value in result.equivalence_classes))
        except ValueError as error:
            return ErrorReply(error=str(error))

    @classmethod
    def compare(cls, runner: Path, cases: tuple[tuple[_ContextSide, _ContextSide, ConfigurationWeightAssumption], ...]) -> None:
        """runner 为真实 C++；每条完整 DTO 严格等价，不只检查 pressure 被选中。"""
        requests = tuple(_ContextSpaceInput(attacker=left.request(), defender=right.request(), weight_assumption=weight) for left, right, weight in cases)
        process = subprocess.run((str(runner),), input="".join(value.model_dump_json() + "\n" for value in requests),
            text=True, capture_output=True, check=True, timeout=180)
        lines = process.stdout.splitlines()
        assert len(lines) == len(cases), process.stderr
        for case, line in zip(cases, lines, strict=True):
            expected = cls.reference(*case)
            actual = ErrorReply.model_validate_json(line) if isinstance(expected, ErrorReply) else SpaceReply.model_validate_json(line)
            assert actual == expected, (case[0].factory, case[0].repository_mode, case[0].command.abilities)


class TestCoreConfigurationComposition:
    """透明 reference provider 与 strict admission 是两个原合同，不能互相冒充。"""

    def test_full_real_composition_and_mixed_sides(self, configuration_space_runner: Path) -> None:
        """比较全部 factory/repository 三态、命令排除、两权重和异侧 composition。"""
        sides = tuple(_ContextSide(_ContextOracle.profile(status), _ContextOracle.command(requested), factory, mode)
            for factory in ("standard", "transparent_inference") for mode in ("raw", "factory_reconciled")
            for status in MechanismSupportStatus if status.value in ("supported", "partial", "unsupported")
            for requested in ((), ("technician",)))
        cases = tuple((side, sides[(index + 7) % len(sides)], weight) for index, side in enumerate(sides) for weight in ConfigurationWeightAssumption)
        _ContextOracle.compare(configuration_space_runner, cases)

    def test_original_empty_ability_error_and_pressure_reference(self, configuration_space_runner: Path) -> None:
        """inner_focus 仍被原 PARTIAL provider 排除；pressure 的 missing 不阻止 reference。"""
        cases: list[tuple[_ContextSide, _ContextSide, ConfigurationWeightAssumption]] = []
        for factory, mode in (("transparent_inference", "raw"), ("transparent_inference", "factory_reconciled"), ("standard", "factory_reconciled")):
            for ability in ("inner-focus", "pressure", "pickpocket"):
                side = _ContextSide(_ContextOracle.profile(MechanismSupportStatus.UNSUPPORTED), _ContextOracle.command((ability,)), factory, mode)
                cases.append((side, side, ConfigurationWeightAssumption.UNIFORM_RAW_CONFIGURATION))
        _ContextOracle.compare(configuration_space_runner, tuple(cases))
