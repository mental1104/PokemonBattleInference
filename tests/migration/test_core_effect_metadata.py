"""完整工厂能力与推演摘要机制集合的正式ABI差分，默认Describe合同保持原样。"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pokeop.application.battle_inference_effect_factory import TransparentPokemonChampionEffectFactory
from pokeop.application.use_cases.infer_one_on_one_battle._core import _mechanism_coverage
from pokeop.domain.battle.effects.factories import PokemonChampionEffectFactory
from pokeop.domain.battle.effects.protocols import EffectCoverageStatus
from tests.migration.test_core_configuration_abi import DescriptionInput, QueriedEffect, _ABI
from tests.migration.test_core_damage import damage_runner


class _Contract(BaseModel):
    """JSON固定边界，冻结字段且拒绝丢失/额外字段。"""
    model_config = ConfigDict(frozen=True, extra="forbid")


class MetadataInput(DescriptionInput):
    """显式请求扩展元数据，未请求时不得改变旧golden响应。"""
    include_capabilities: Literal[True] = True


class MetadataOperation(_Contract):
    """仅扩展已有describe操作，不创建第二个工厂映射入口。"""
    kind: Literal["configuration_coverage"] = "configuration_coverage"
    input: MetadataInput


class MetadataBatch(_Contract):
    """保持原批次原子性与操作顺序。"""
    schema_version: Literal[1] = 1
    operations: tuple[MetadataOperation, ...]


class Capability(_Contract):
    """原工厂子能力的完整身份、状态、原文原因。"""
    identifier: str
    status: EffectCoverageStatus
    reason: str


class MetadataEffect(QueriedEffect):
    """基础Describe事实及全部supported/unsupported能力，不仅缺失列表。"""
    capabilities: tuple[Capability, ...]


class MetadataResult(_Contract):
    """原_mechanism_coverage规则直接由Core输出，调用方不再复刻集合语义。"""
    kind: Literal["configuration_coverage"]
    mode: Literal["describe"]
    effects: tuple[MetadataEffect, ...]
    included_mechanisms: tuple[str, ...]
    excluded_mechanisms: tuple[str, ...]


class MetadataEnvelope(_Contract):
    """明确本批真实ABI版本，不接受旧二进制的缺字段响应。"""
    schema_version: Literal[1]
    engine_version: Literal["0.10.0"]
    rules_version: Literal["calculation-rules.v10"]
    results: tuple[MetadataResult, ...]


class TestCoreEffectMetadata:
    """标准与透明composition的完整字段、集合和旧默认响应均独立验证。"""
    def test_complete_factory_records_and_mechanism_summary(self, damage_runner: Path) -> None:
        """两真实工厂全机制逐字段比较，覆盖FakeOut四能力、透明占位和InnerFocus旧aspects语义。"""
        operations = tuple(MetadataOperation(input=MetadataInput(factory=factory,
            moves=(None, "ice-punch", "fake-out", "brick-break", "unimplemented", "fake_out"),
            abilities=(None, "technician", "multiscale", "inner-focus", "pressure", "pickpocket", "unimplemented"),
            items=(None, "choice-band", "life-orb", "unimplemented"))) for factory in ("standard", "transparent_inference"))
        process = subprocess.run([str(damage_runner.parent / "pbi_abi_vectors")],
            input=MetadataBatch(operations=operations).model_dump_json() + "\n", text=True, capture_output=True, check=True, timeout=30)
        envelope = MetadataEnvelope.model_validate_json(process.stdout)
        assert len(envelope.results) == len(operations)
        for operation, actual in zip(operations, envelope.results, strict=True):
            factory = PokemonChampionEffectFactory() if operation.input.factory == "standard" else TransparentPokemonChampionEffectFactory()
            products = tuple(factory.create_move_effect(identifier) for identifier in operation.input.moves)
            products += tuple(factory.create_ability_effect(identifier) for identifier in operation.input.abilities)
            products += tuple(factory.create_item_effect(identifier) for identifier in operation.input.items)
            assert len(actual.effects) == len(products)
            for effect, product in zip(actual.effects, products, strict=True):
                original = product.coverage
                reference = _ABI.effect(original)
                assert (effect.identifier, effect.status, effect.reason, effect.missing_capabilities) == (
                    reference.identifier, reference.status, reference.reason, reference.missing_capabilities)
                assert effect.source == original.source_kind.value and effect.factory == operation.input.factory
                assert effect.capabilities == tuple(Capability(identifier=value.identifier, status=value.status, reason=value.reason) for value in original.capabilities)
            included, excluded = _mechanism_coverage(products)
            assert actual.included_mechanisms == included and actual.excluded_mechanisms == excluded
