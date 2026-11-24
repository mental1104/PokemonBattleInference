"""正式ABI验证原具体44100case、关联快照完整性与真实composition严格准入。"""
from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from pokeop.application.configuration_space.one_on_one.commands import OneOnOneMovePoolCommand
from pokeop.application.repositories.battle_inference import MechanismSupportStatus
from pokeop.domain.battle.context import MoveCategory
from pokeop.domain.battle.effects.protocols import EffectSourceKind
from pokeop.domain.models.types import Type
from tests.migration.test_core_configuration_abi import Effect
from tests.migration.test_core_damage import ExactFraction, MoveSnapshot, damage_runner
from tests.migration.test_core_job_move_pool import AdmissionInput as OriginalAdmission, JobInput as OriginalJob, JobReply, JobCase, _Oracle
from tests.migration.test_core_state import MoveSpecSnapshot


class _Contract(BaseModel):
    """冻结完整正式边界，不把未知字段丢弃成假成功。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class AdmissionCandidate(_Contract):
    """原repository事实与明确允许无effect的调用上下文。"""
    source: EffectSourceKind
    effect_identifier: str | None
    mechanism_identifier: str
    repository_reason: str
    base_executable: bool
    allow_no_effect: bool


class AdmissionInput(_Contract):
    """strict边界显式选择真实工厂与repository composition。"""
    mode: Literal["admission"] = "admission"
    factory: Literal["standard", "transparent_inference"]
    repository_mode: Literal["raw", "factory_reconciled"]
    candidates: tuple[AdmissionCandidate, ...]


class Fact(AdmissionCandidate):
    """关联一侧、具体moveID及完整招式快照，不依赖数组位置表达归属。"""
    side: Literal["attacker", "defender"]
    move_id: int | None
    move: MoveSpecSnapshot | None


class Snapshot(_Contract):
    """同一知识/命令主轴下的完整准入事实，不声称验证数据库真伪。"""
    ruleset_id: str
    version_group_id: int
    calculation_revision: str
    candidates: tuple[Fact, ...]


class JobInput(_Contract):
    """真正具体case规划，分页不改变完整pool总量。"""
    command: OneOnOneMovePoolCommand
    admission: Snapshot
    offset: int
    limit: int


class JobOperation(_Contract):
    """正式job-v1独立操作，未使用通用等价空间。"""
    kind: Literal["job_move_pool"] = "job_move_pool"
    input: JobInput


class AdmissionOperation(_Contract):
    """创建前全量strict收集操作。"""
    kind: Literal["configuration_coverage"] = "configuration_coverage"
    input: AdmissionInput


class Batch(_Contract):
    """正式完整原子批次。"""
    schema_version: Literal[1] = 1
    operations: tuple[Annotated[JobOperation | AdmissionOperation, Field(discriminator="kind")], ...]


class Case(_Contract):
    """全部canonical身份与精确全局均匀权重。"""
    ordinal: int
    configuration_pair_id: str
    attacker_configuration_id: str
    defender_configuration_id: str
    attacker_move_ids: tuple[int, ...]
    defender_move_ids: tuple[int, ...]
    configuration_weight: ExactFraction


class JobResult(_Contract):
    """完整全局数量和可继续分页位置，不以一页长度替代case_count。"""
    kind: Literal["job_move_pool"]
    case_count: int
    attacker_move_set_count: int
    defender_move_set_count: int
    offset: int
    next_offset: int
    has_more: bool
    cases: tuple[Case, ...]


class Admission(_Contract):
    """完整Core strict事实与缺失子能力。"""
    source: EffectSourceKind
    mechanism_identifier: str
    factory: Literal["standard", "transparent_inference"]
    repository_mode: Literal["raw", "factory_reconciled"]
    coverage: Effect
    status: MechanismSupportStatus
    reason: str
    selectable: bool
    missing_mechanism_identifiers: tuple[str, ...]


class AdmissionResult(_Contract):
    """所有候选完整准入结果，不能在第一个失败处截断列表。"""
    kind: Literal["configuration_coverage"]
    mode: Literal["admission"]
    candidates: tuple[Admission, ...]


class Envelope(_Contract):
    """当前成功版本的完整结果。"""
    schema_version: Literal[1]
    engine_version: Literal["0.7.0"]
    rules_version: Literal["calculation-rules.v7"]
    results: tuple[Annotated[JobResult | AdmissionResult, Field(discriminator="kind")], ...]


class Error(_Contract):
    """错误不携带部分cases/results，文本只用于诊断。"""
    code: str
    message: str


class FailedEnvelope(_Contract):
    """整个批次失败，严格拒绝多余results字段。"""
    schema_version: Literal[1]
    engine_version: Literal["0.7.0"]
    rules_version: Literal["calculation-rules.v7"]
    error: Error


class _ABI:
    """只构造合法测试事实和投影结果，不重写旧组合/canonical/SHA/strict算法。"""
    @staticmethod
    def snapshot(command: OneOnOneMovePoolCommand) -> Snapshot:
        """command为原真实命令；构造明确无附加效果的合法基础招式知识快照。"""
        facts: list[Fact] = []
        for side, selection in (("attacker", command.attacker), ("defender", command.defender)):
            for identifier in selection.candidate_move_ids:
                spec = MoveSpecSnapshot(move_id=identifier, name=f"basic-{identifier}",
                    move=MoveSnapshot(type=Type.NORMAL, category=MoveCategory.PHYSICAL, power=40),
                    max_pp=10, priority=0, accuracy=100, effect_identifier=None)
                facts.append(Fact(side=side, source=EffectSourceKind.MOVE, move_id=identifier, move=spec,
                    effect_identifier=None, mechanism_identifier=f"basic-{identifier}", repository_reason="Raw legal basic move.",
                    base_executable=True, allow_no_effect=True))
            facts.append(Fact(side=side, source=EffectSourceKind.ABILITY, move_id=None, move=None,
                effect_identifier=selection.fixed.ability_identifier, mechanism_identifier=selection.fixed.ability_identifier,
                repository_reason="Raw legal ability.", base_executable=True, allow_no_effect=False))
            facts.append(Fact(side=side, source=EffectSourceKind.ITEM, move_id=None, move=None,
                effect_identifier=selection.fixed.item_identifier, mechanism_identifier=selection.fixed.item_identifier or "none",
                repository_reason="Raw controlled held item.", base_executable=True, allow_no_effect=selection.fixed.item_identifier is None))
        return Snapshot(ruleset_id=command.ruleset_id, version_group_id=command.version_group_id,
            calculation_revision=command.calculation_revision, candidates=tuple(facts))

    @classmethod
    def operation(cls, command: OneOnOneMovePoolCommand, offset: int, limit: int) -> JobOperation:
        """由原command直接组装正式有界页，完整事实与主轴只来自该command。"""
        return JobOperation(input=JobInput(command=command, admission=cls.snapshot(command), offset=offset, limit=limit))

    @staticmethod
    def lines(runner: Path, requests: tuple[Batch, ...]) -> tuple[str, ...]:
        """实际调用正式ABI进程；返回每条完整原始响应便于严格成功/错误解码。"""
        process = subprocess.run([str(runner.parent / "pbi_abi_vectors")],
            input="".join(value.model_dump_json() + "\n" for value in requests), text=True, capture_output=True, check=True, timeout=180)
        lines = tuple(process.stdout.splitlines()); assert len(lines) == len(requests)
        return lines

    @staticmethod
    def project(value: JobResult) -> JobReply:
        """正式全部字段投影到旧oracle，不改变权重、顺序或任何身份文本。"""
        return JobReply(case_count=value.case_count, attacker_move_set_count=value.attacker_move_set_count,
            defender_move_set_count=value.defender_move_set_count, cases=tuple(JobCase(ordinal=item.ordinal,
                configuration_pair_id=item.configuration_pair_id, attacker_configuration_id=item.attacker_configuration_id,
                defender_configuration_id=item.defender_configuration_id, attacker_move_ids=item.attacker_move_ids,
                defender_move_ids=item.defender_move_ids, numerator=item.configuration_weight.numerator,
                denominator=item.configuration_weight.denominator) for item in value.cases))


class TestCoreJobMovePoolABI:
    """具体身份、全量准入、关联完整性和全批原子拒绝。"""
    def test_all_44100_cases_across_real_pages(self, damage_runner: Path) -> None:
        """三页覆盖完整10+10组合，所有canonical pair/sideSHA/顺序/权重逐字段相同。"""
        command = replace(_Oracle.command(10, 10), calculation_revision="battle-inference.summary-exploration.v2")
        operations = tuple(_ABI.operation(command, offset, 14700) for offset in (0, 14700, 29400, 44100))
        replies = _ABI.lines(damage_runner, tuple(Batch(operations=(value,)) for value in operations))
        total = 0
        for operation, line in zip(operations, replies, strict=True):
            envelope = Envelope.model_validate_json(line); assert len(envelope.results) == 1
            value = envelope.results[0]; assert isinstance(value, JobResult)
            assert _ABI.project(value) == _Oracle.job(OriginalJob(command=command, offset=operation.input.offset, limit=operation.input.limit))
            assert value.offset == operation.input.offset and value.next_offset == value.offset + len(value.cases)
            assert value.has_more == (value.next_offset < command.configuration_pair_count)
            total += len(value.cases)
        assert total == 44100

    def test_explicit_none_item_keeps_original_canonical_identity(self, damage_runner: Path) -> None:
        """damage_runner运行正式ABI；原'none'选择无效果事实，同时完整保留与null不同的canonical身份。"""
        baseline = _Oracle.command(2, 2)
        command = replace(
            baseline,
            attacker=replace(baseline.attacker, fixed=replace(baseline.attacker.fixed, item_identifier="none")),
            defender=replace(baseline.defender, fixed=replace(baseline.defender.fixed, item_identifier="none")),
        )
        operation = _ABI.operation(command, 0, 10)
        # 原受控repository的'none'候选effect为None，不能从原始命令字符串猜成实际道具效果。
        candidates = tuple(
            fact.model_copy(update={"effect_identifier": None, "allow_no_effect": True})
            if fact.source is EffectSourceKind.ITEM else fact
            for fact in operation.input.admission.candidates
        )
        snapshot = operation.input.admission.model_copy(update={"candidates": candidates})
        operation = operation.model_copy(update={"input": operation.input.model_copy(update={"admission": snapshot})})
        line = _ABI.lines(damage_runner, (Batch(operations=(operation,)),))[0]
        envelope = Envelope.model_validate_json(line)
        result = envelope.results[0]
        assert isinstance(result, JobResult)
        expected = _Oracle.job(OriginalJob(command=command, offset=0, limit=10))
        assert _ABI.project(result) == expected
        original_null = _Oracle.job(OriginalJob(command=baseline, offset=0, limit=10))
        assert result.cases[0].configuration_pair_id != original_null.cases[0].configuration_pair_id

    def test_complete_strict_collection_uses_original_composition(self, damage_runner: Path) -> None:
        """raw/reconciled和两个真实factory的全部strict字段，包含透明PARTIAL与no_effect。"""
        originals = tuple(OriginalAdmission(source=source, factory=factory, repository_mode=repository,
            effect_identifier=identifier, mechanism_identifier=identifier or "none", repository_reason="Raw repository projection.",
            repository_status=MechanismSupportStatus.PARTIAL, base_executable=executable, allow_no_effect=allow)
            for factory in ("standard", "transparent_inference") for repository in ("raw", "factory_reconciled")
            for source, identifiers in ((EffectSourceKind.MOVE, (None, "ice_punch", "fake_out", "unknown")),
                (EffectSourceKind.ABILITY, (None, "pressure", "pickpocket", "inner_focus", "multiscale")),
                (EffectSourceKind.ITEM, (None, "choice_band", "unknown"))) for identifier in identifiers
            for executable in (False, True) for allow in (False, True))
        operations = tuple(AdmissionOperation(input=AdmissionInput(factory=value.factory, repository_mode=value.repository_mode,
            candidates=(AdmissionCandidate(source=value.source, effect_identifier=value.effect_identifier,
                mechanism_identifier=value.mechanism_identifier, repository_reason=value.repository_reason,
                base_executable=value.base_executable, allow_no_effect=value.allow_no_effect),))) for value in originals)
        replies = _ABI.lines(damage_runner, tuple(Batch(operations=(value,)) for value in operations))
        for request, line in zip(originals, replies, strict=True):
            envelope = Envelope.model_validate_json(line); assert len(envelope.results) == 1
            value = envelope.results[0]; assert isinstance(value, AdmissionResult) and len(value.candidates) == 1
            actual = value.candidates[0]; expected = _Oracle.admission(request)
            assert (actual.status, actual.selectable, actual.reason, actual.missing_mechanism_identifiers) == (
                expected.status, expected.selectable, expected.reason, expected.missing_mechanism_identifiers)
            assert actual.coverage == Effect(identifier=expected.coverage.identifier, status=expected.coverage.status,
                reason=expected.coverage.reason, missing_capabilities=expected.coverage.missing_capabilities)
            assert actual.source is request.source and actual.factory == request.factory and actual.repository_mode == request.repository_mode

    def test_snapshot_mismatch_and_unsupported_are_atomic(self, damage_runner: Path) -> None:
        """缺项、重复、外来ID/主轴、非法no_effect及真实不支持不能返回缩小后的成功池。"""
        command = _Oracle.command(3, 4); baseline = _ABI.operation(command, 0, 4)
        snapshot = baseline.input.admission
        failures: list[tuple[JobOperation, str]] = []
        for facts in (snapshot.candidates[:-1], snapshot.candidates + snapshot.candidates[:1],
                (snapshot.candidates[0].model_copy(update={"move_id": 999}),) + snapshot.candidates[1:]):
            failures.append((baseline.model_copy(update={"input": baseline.input.model_copy(update={"admission": snapshot.model_copy(update={"candidates": facts})})}), "invalid_input"))
        failures.append((baseline.model_copy(update={"input": baseline.input.model_copy(update={"admission": snapshot.model_copy(update={"calculation_revision": "another-revision"})})}), "invalid_input"))
        bad = tuple(value.model_copy(update={"allow_no_effect": True}) if value.source is EffectSourceKind.ABILITY else value for value in snapshot.candidates)
        failures.append((baseline.model_copy(update={"input": baseline.input.model_copy(update={"admission": snapshot.model_copy(update={"candidates": bad})})}), "invalid_input"))
        unsupported = snapshot.candidates[0].model_copy(update={"effect_identifier": "ice_punch", "allow_no_effect": False})
        failures.append((baseline.model_copy(update={"input": baseline.input.model_copy(update={"admission": snapshot.model_copy(update={"candidates": (unsupported,) + snapshot.candidates[1:]})})}), "unsupported"))
        foreign_command = replace(command, ruleset_id="another-ruleset")
        failures.append((baseline.model_copy(update={"input": baseline.input.model_copy(update={"command": foreign_command,
            "admission": snapshot.model_copy(update={"ruleset_id": foreign_command.ruleset_id})})}), "unsupported"))
        replies = _ABI.lines(damage_runner, tuple(Batch(operations=(baseline, operation, baseline)) for operation, _ in failures))
        for line, (_, code) in zip(replies, failures, strict=True):
            error = FailedEnvelope.model_validate_json(line); assert error.error.code == code
            assert "results" not in json.loads(line)

    def test_page_byte_budget_is_separate_from_complete_pool(self, damage_runner: Path) -> None:
        """合法大canonical身份令页面超过32MiB时整批RESOURCE_LIMIT，不返回成功前缀。"""
        command = _Oracle.command(10, 10, profile_id="x" * 140000)
        operation = _ABI.operation(command, 0, 130)
        # 仅两侧profile文本就已超过页字节上限；输入仍小于8MiB，不是命中请求限制。
        assert 2 * len(command.attacker.fixed.stat_profile_id) * operation.input.limit > 32 * 1024 * 1024
        request = Batch(operations=(operation,)); assert len(request.model_dump_json().encode()) < 8 * 1024 * 1024
        line = _ABI.lines(damage_runner, (request,))[0]
        response = FailedEnvelope.model_validate_json(line)
        assert response.error.code == "resource_limit" and "results" not in json.loads(line)
