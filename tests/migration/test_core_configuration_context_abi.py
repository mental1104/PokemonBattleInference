"""正式space codec对照原透明/标准composition，保留完整provider覆盖与独立factory事实。"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Literal

import pytest
from tests.migration.test_core_configuration_abi import (
    _ABI, _Contract, SideInput, SpaceResult, MoveDescription, AbilityDescription, ItemDescription, Repository,
)
from tests.migration.test_core_configuration_context import _ContextSide, _ContextOracle
from tests.migration.test_core_configuration_space import SpaceReply, ErrorReply, PairClass
from pokeop.application.configuration_space.model_base import ConfigurationWeightAssumption
from pokeop.application.repositories.battle_inference import MechanismSupportStatus


class _SideInput(SideInput):
    """正式完整原候选追加两个显式composition字段，不预提升状态。"""
    factory: Literal["standard","transparent_inference"]
    repository_mode: Literal["raw","factory_reconciled"]


class _SpaceInput(_Contract):
    """两侧可以独立使用原composition；全部分区/成员/权重仍来自Core。"""
    attacker: _SideInput
    defender: _SideInput
    weight_assumption: ConfigurationWeightAssumption
    max_raw_pairs: int=1000000


class _Operation(_Contract):
    """真正正式space输入，不使用纯runner的简化六能力数组或招式分类序号。"""
    kind: Literal["configuration_space"]="configuration_space"
    input: _SpaceInput


@pytest.fixture
def context_contract_runner() -> Path:
    """必须显式提供同新纯域配对的codec；缺环境单列SKIP。"""
    value=os.environ.get("PBI_CONFIGURATION_CONTEXT_CONTRACT_RUNNER")
    if value is None:
        pytest.skip("PBI_CONFIGURATION_CONTEXT_CONTRACT_RUNNER is required")
    path=Path(value)
    assert path.is_file()
    return path


class _Oracle:
    """正式边界的形状变换与原公开generator/factory完整结果比较。"""
    @staticmethod
    def side(value:_ContextSide) -> _SideInput:
        """value包含原raw repository和原命令；只投影输入，不提前过滤或修正。"""
        return _SideInput(**_ABI.side(value.side(reconciled=False)).model_dump(),factory=value.factory,repository_mode=value.repository_mode)

    @staticmethod
    def descriptions(actual:SpaceResult,first:_ContextSide,second:_ContextSide) -> None:
        """原raw理由独立保留；每项工厂事实来自与该侧相同的原真实factory。"""
        for result,source in ((actual.attacker,first),(actual.defender,second)):
            raw=source.side(reconciled=False)
            requested=_Oracle.side(source)
            moves=tuple(value for value in result.candidate_descriptions if isinstance(value,MoveDescription))
            pure=source.request()
            _ABI.check_descriptions(moves,pure.moves.candidates)
            abilities=tuple(value for value in result.candidate_descriptions if isinstance(value,AbilityDescription))
            assert len(abilities)==len(raw.profile.abilities)
            factory=source.effect_factory()
            for value,candidate in zip(abilities,raw.profile.abilities,strict=True):
                assert value.identifier==candidate.identifier
                assert value.repository==Repository(support=candidate.support_status.value,reason=candidate.support_reason)
                assert value.factory==_ABI.effect(factory.create_ability_effect(candidate.identifier).coverage)
            items=tuple(value for value in result.candidate_descriptions if isinstance(value,ItemDescription))
            assert tuple(value.factory for value in items)==tuple(_ABI.effect(factory.create_item_effect(identifier).coverage) for identifier in requested.items)

    @classmethod
    def compare(cls,runner:Path,cases:tuple[tuple[_ContextSide,_ContextSide,ConfigurationWeightAssumption],...]) -> None:
        """runner是真正正式codec；每例对照原composition全部字段，不只断言pressure是否存在。"""
        operations=tuple(_Operation(input=_SpaceInput(attacker=cls.side(first),defender=cls.side(second),weight_assumption=weight)) for first,second,weight in cases)
        process=subprocess.run([str(runner)],input="".join(value.model_dump_json()+"\n" for value in operations),text=True,capture_output=True,check=True,timeout=60)
        lines=process.stdout.splitlines()
        assert len(lines)==len(cases)
        for line,(first,second,weight) in zip(lines,cases,strict=True):
            expected=_ContextOracle.reference(first,second,weight)
            if isinstance(expected,ErrorReply):
                assert ErrorReply.model_validate_json(line)==expected
                continue
            actual=SpaceResult.model_validate_json(line)
            projected=SpaceReply(attacker=_ABI.project_side(actual.attacker),defender=_ABI.project_side(actual.defender),raw_pair_count=actual.raw_pair_count,
                pairs=tuple(PairClass(attacker_key=actual.attacker.classes[value.attacker_class].key,defender_key=actual.defender.classes[value.defender_class].key,
                    member_count=value.member_count,numerator=value.weight.numerator,denominator=value.weight.denominator) for value in actual.pairs))
            assert projected==expected
            cls.descriptions(actual,first,second)


class TestConfigurationContextCodec:
    """真实新composition与原默认space读取兼容，双侧可以独立选择工厂。"""
    def test_full_original_composition(self,context_contract_runner:Path) -> None:
        """48组完整分区/权重/候选理由/工厂事实，含跨侧不同composition。"""
        sides=tuple(_ContextSide(_ContextOracle.profile(status),_ContextOracle.command(requested),factory,mode)
            for factory in ("standard","transparent_inference") for mode in ("raw","factory_reconciled")
            for status in MechanismSupportStatus if status.value in ("supported","partial","unsupported") for requested in ((),("technician",)))
        cases=tuple((side,sides[(index+7)%len(sides)],weight) for index,side in enumerate(sides) for weight in ConfigurationWeightAssumption)
        _Oracle.compare(context_contract_runner,cases)

    def test_original_reference_and_empty_provider(self,context_contract_runner:Path) -> None:
        """原inner_focus排除和透明pressure/pickpocket的真实筛选及错误文案保真。"""
        cases=[]
        for factory,mode in (("transparent_inference","raw"),("transparent_inference","factory_reconciled"),("standard","factory_reconciled")):
            for ability in ("inner-focus","pressure","pickpocket"):
                side=_ContextSide(_ContextOracle.profile(MechanismSupportStatus.UNSUPPORTED),_ContextOracle.command((ability,)),factory,mode)
                cases.append((side,side,ConfigurationWeightAssumption.UNIFORM_RAW_CONFIGURATION))
        _Oracle.compare(context_contract_runner,tuple(cases))
