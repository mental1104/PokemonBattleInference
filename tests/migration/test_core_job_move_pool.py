"""原job-v1具体case/canonical身份和透明工厂strict准入的真实Core差分。"""

from __future__ import annotations

import os
import random
import subprocess
from dataclasses import replace
from itertools import islice
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict

from pokeop.application.battle_candidate_pool.listing import ListBattleCandidatePoolUseCase
from pokeop.application.battle_inference_effect_factory import TransparentPokemonChampionEffectFactory
from pokeop.application.composition.battle_inference_repository import FactoryReconciledBattleInferenceRepository
from pokeop.application.configuration_space.one_on_one.commands import FixedPokemonConfiguration, OneOnOneMovePoolCommand, PokemonMovePoolSelection
from pokeop.application.repositories.battle_inference import MechanismCapability, MechanismSupportStatus
from pokeop.application.use_cases._battle_inference_jobs.identity import case_definition
from pokeop.domain.battle.effects.factories import PokemonChampionEffectFactory
from pokeop.domain.battle.effects.protocols import EffectCoverageStatus, EffectSourceKind
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.models.types import Type
from tests.application.battle_candidate_pool.test_candidate_pool_and_admission import _ability, _item, _move, _repository, _type


class _Contract(BaseModel):
    """冻结完整测试协议，不以缺失字段或宽松dict隐藏身份差异。"""

    model_config = ConfigDict(frozen=True, extra="forbid")


class JobInput(_Contract):
    """直接复用原命令dataclass作为唯一合同事实源。"""

    mode: Literal["job"] = "job"
    command: OneOnOneMovePoolCommand
    offset: int
    limit: int


class JobCase(_Contract):
    """原case_definition的全部身份，加原迭代序号与精确均匀权重。"""

    ordinal: int
    configuration_pair_id: str
    attacker_configuration_id: str
    defender_configuration_id: str
    attacker_move_ids: tuple[int, ...]
    defender_move_ids: tuple[int, ...]
    numerator: str
    denominator: str


class JobReply(_Contract):
    """原具体池大小与一页真实case，不含等价代表/member_count替代物。"""

    case_count: int
    attacker_move_set_count: int
    defender_move_set_count: int
    cases: tuple[JobCase, ...]


class AdmissionInput(_Contract):
    """原strict私有算法的完整独立事实，repository_status仅用于证明其不是准入真相。"""

    mode: Literal["admission"] = "admission"
    source: EffectSourceKind
    factory: Literal["standard", "transparent_inference"]
    effect_identifier: str | None
    mechanism_identifier: str
    repository_reason: str
    repository_status: MechanismSupportStatus
    base_executable: bool
    allow_no_effect: bool
    repository_mode: Literal["raw", "factory_reconciled"] = "raw"


class Coverage(_Contract):
    """真实factory描述与全部原缺口的顺序投影。"""

    identifier: str
    status: EffectCoverageStatus
    reason: str
    missing_capabilities: tuple[str, ...]


class AdmissionReply(_Contract):
    """原严格准入的全部业务字段，含中文公开reason原文。"""

    status: MechanismSupportStatus
    selectable: bool
    reason: str
    missing_mechanism_identifiers: tuple[str, ...]
    coverage: Coverage


class _Oracle:
    """仅负责原类型构造和完整投影；迭代/JSON/SHA/strict算法全委托原实现。"""

    @staticmethod
    def command(first_count: int, second_count: int, profile_id: str = "max_atk_plus") -> OneOnOneMovePoolCommand:
        """按给定池大小生成倒序候选，验证原规范化不依赖点击顺序。"""
        return OneOnOneMovePoolCommand(
            ruleset_id="pokemon-champion", version_group_id=25, calculation_revision="legacy-r1",
            attacker=PokemonMovePoolSelection(FixedPokemonConfiguration(149, None, 50, profile_id, "multiscale", None), tuple(range(first_count, 0, -1))),
            defender=PokemonMovePoolSelection(FixedPokemonConfiguration(461, 7, 50, profile_id, "technician", "choice-band"), tuple(range(100 + second_count, 100, -1))),
        )

    @staticmethod
    def job(request: JobInput) -> JobReply:
        """实际调用原惰性配置迭代与case_definition，不复制组合或canonical/hash算法。"""
        command = request.command
        cases: list[JobCase] = []
        for ordinal, config in enumerate(islice(command.iter_configurations(), request.offset, request.offset + request.limit), start=request.offset):
            item = case_definition(config)
            cases.append(JobCase(ordinal=ordinal, configuration_pair_id=item.configuration_pair_id,
                attacker_configuration_id=item.attacker_configuration_id, defender_configuration_id=item.defender_configuration_id,
                attacker_move_ids=item.attacker_move_ids, defender_move_ids=item.defender_move_ids,
                numerator="1", denominator=str(command.configuration_pair_count)))
        return JobReply(case_count=command.configuration_pair_count, attacker_move_set_count=command.attacker.move_set_count,
            defender_move_set_count=command.defender.move_set_count, cases=tuple(cases))

    @staticmethod
    def admission(request: AdmissionInput) -> AdmissionReply:
        """执行原HTTP composition工厂和原严格准入算法，raw三态不会替代factory判断。"""
        factory = PokemonChampionEffectFactory() if request.factory == "standard" else TransparentPokemonChampionEffectFactory()
        if request.source is EffectSourceKind.MOVE:
            coverage = factory.create_move_effect(request.effect_identifier).coverage
        elif request.source is EffectSourceKind.ABILITY:
            coverage = factory.create_ability_effect(request.effect_identifier).coverage
        else:
            coverage = factory.create_item_effect(request.effect_identifier).coverage
        repository = _repository({})
        capability = MechanismCapability(source_kind=request.source, identifier=request.mechanism_identifier,
            status=request.repository_status, reason=request.repository_reason)
        if request.repository_mode == "factory_reconciled":
            reconciler = FactoryReconciledBattleInferenceRepository(repository, factory)
            if request.source is EffectSourceKind.MOVE:
                raw_move = _move(1, "admission-case", _type(1, "normal", Type.NORMAL), request.repository_status,
                    power=50 if request.base_executable else None, effect_identifier=request.effect_identifier)
                category = MoveCategory.STATUS if request.base_executable and not request.allow_no_effect else MoveCategory.PHYSICAL
                capability = reconciler._move(replace(raw_move, capability=capability, category=category)).capability
            elif request.source is EffectSourceKind.ABILITY:
                raw_ability = _ability(request.mechanism_identifier, request.repository_status)
                capability = reconciler._ability(replace(raw_ability, capability=capability, effect_identifier=request.effect_identifier)).capability
            else:
                raw_item = _item(request.mechanism_identifier, request.repository_status)
                capability = reconciler._item(replace(raw_item, capability=capability, effect_identifier=request.effect_identifier)).capability
        use_case = ListBattleCandidatePoolUseCase(repository, factory)
        result = use_case._admission(
            capability, coverage,
            ruleset_id="pokemon-champion", version_group_id=25, expected_source_kind=request.source,
            base_executable=request.base_executable, allow_no_effect=request.allow_no_effect,
        )
        return AdmissionReply(status=result.status, selectable=result.selectable, reason=result.reason,
            missing_mechanism_identifiers=result.missing_mechanism_identifiers,
            coverage=Coverage(identifier=coverage.identifier, status=coverage.status, reason=coverage.reason,
                missing_capabilities=tuple(dict.fromkeys(coverage.unsupported_aspects + tuple(value.identifier for value in coverage.unsupported_capabilities)))))

    @staticmethod
    def lines(runner: Path, requests: tuple[JobInput | AdmissionInput, ...]) -> tuple[str, ...]:
        """批量运行真实C++并验证响应数量，完整44,100case同样走实际进程。"""
        result = subprocess.run([str(runner)], input="".join(value.model_dump_json() + "\n" for value in requests),
            text=True, capture_output=True, check=True, timeout=60)
        lines = tuple(result.stdout.splitlines())
        assert len(lines) == len(requests)
        return lines


@pytest.fixture
def job_move_pool_runner() -> Path:
    """外部真实编译入口；未提供时显式skip，不能把Python自身当作Core。"""
    value = os.getenv("PBI_JOB_MOVE_POOL_RUNNER")
    if value is None:
        pytest.skip("PBI_JOB_MOVE_POOL_RUNNER is required")
    runner = Path(value)
    assert runner.is_file()
    return runner


class TestCoreJobMovePool:
    """真实具体case与透明strict准入各保留其原独立业务语义。"""

    def test_all_44100_canonical_cases_and_bounded_pages(self, job_move_pool_runner: Path) -> None:
        """比较完整10+10池及64个随机页，逐字段核对每个pairJSON、两侧SHA和原顺序。"""
        rng = random.Random(854149)
        requests = [JobInput(command=_Oracle.command(10, 10), offset=0, limit=44100)]
        for index in range(64):
            first = rng.randint(1, 19)
            second = rng.randint(1, 20 - first)
            profile = "snapshot:" + "".join(chr(value) for value in range(128)) + ":end" if index == 0 else "preset:" + "a" * index + ":end"
            command = _Oracle.command(first, second, profile)
            offset = 0 if index == 0 else rng.randint(0, command.configuration_pair_count)
            limit = 32 if index == 0 else rng.randint(0, 32)
            requests.append(JobInput(command=command, offset=offset, limit=limit))
        lines = _Oracle.lines(job_move_pool_runner, tuple(requests))
        for line, request in zip(lines, requests, strict=True):
            assert JobReply.model_validate_json(line) == _Oracle.job(request)

    def test_real_transparent_and_standard_strict_admission(self, job_move_pool_runner: Path) -> None:
        """逐字段比较两真实工厂、全部四种raw覆盖状态/基础执行性/NO_EFFECT准入组合。"""
        requests: list[AdmissionInput] = []
        for source, identifiers in (
            (EffectSourceKind.MOVE, (None, "fake-out", "ice_punch", "brick break", "unknown-move")),
            (EffectSourceKind.ABILITY, (None, "pressure", "pickpocket", "inner-focus", "multiscale", "technician", "unknown-ability")),
            (EffectSourceKind.ITEM, (None, "choice-band", "life_orb", "unknown-item")),
        ):
            for identifier in identifiers:
                for factory in ("standard", "transparent_inference"):
                    for status in MechanismSupportStatus:
                        for base in (False, True):
                            for allow in (False, True):
                                requests.append(AdmissionInput(source=source, factory=factory, effect_identifier=identifier,
                                    mechanism_identifier=identifier or "base-identity", repository_reason=f"Repository {status.value}.",
                                    repository_status=status, base_executable=base, allow_no_effect=allow))
        requests += [request.model_copy(update={"repository_mode": "factory_reconciled"}) for request in requests]
        lines = _Oracle.lines(job_move_pool_runner, tuple(requests))
        assert tuple(AdmissionReply.model_validate_json(line) for line in lines) == tuple(_Oracle.admission(request) for request in requests)
