"""暴露独立于基础伤害计算器的 1v1 多回合推演用户旅程。"""

from __future__ import annotations

from dataclasses import replace

from fastapi import HTTPException

from pokeop.api.schemas.inference import (
    BattleInferenceJourneyResponse,
    DragoniteWeavileJourneyRequest,
    battle_inference_journey_response,
)
from pokeop.application.battle_inference_effect_factory import (
    TransparentPokemonChampionEffectFactory,
)
from pokeop.application.configuration_space import (
    ConfigurationSpaceError,
    MechanismSupportStatus,
    PokemonConfigurationProfile,
)
from pokeop.application.repositories.battle_inference import (
    BattleInferencePokemonProfile,
)
from pokeop.application.use_cases.infer_one_on_one_battle import (
    BattleActionPolicyKind,
    BattleInferenceExecutionError,
    InferFixedOneOnOneBattleCommand,
    InferOneOnOneBattleUseCase,
    PokemonInferenceSelection,
)
from pokeop.application.use_cases.load_battle_inference_profile import (
    BattleInferenceProfileNotFound,
)
from pokeop.domain.battle.inference_rules import BattleInferenceRules
from pokeop.persistence.battle_inference.repository import (
    MaterializedViewBattleInferenceRepository,
)


_DRAGONITE_ID = 149
_WEAVILE_ID = 461
_BRICK_BREAK_ID = 280
_ICE_PUNCH_ID = 8
_FAKE_OUT_ID = 252
_NEUTRAL_ABILITY_IDENTIFIERS = frozenset({"pressure", "pickpocket"})


class _JourneyInferenceUseCase(InferOneOnOneBattleUseCase):
    """为页面旅程显式放行采用中性假设的合法特性候选。"""

    @staticmethod
    def _configuration_profile(
        profile: BattleInferencePokemonProfile,
        rules: BattleInferenceRules,
    ) -> PokemonConfigurationProfile:
        """把中性假设白名单从 repository unsupported 转成可执行候选。

        Args:
            profile: persistence 已还原当前 version group 的 Pokémon profile。
            rules: 当前推演规则轴。

        Returns:
            保留全部原候选，并只把透明工厂可解释处理的特性标记为可执行的配置 profile。
        """
        converted = InferOneOnOneBattleUseCase._configuration_profile(profile, rules)
        return replace(
            converted,
            abilities=tuple(
                replace(
                    ability,
                    support_status=MechanismSupportStatus.SUPPORTED,
                    support_reason=(
                        "该合法特性尚未实现；页面旅程采用透明中性假设并在结果中报告缺口。"
                    ),
                )
                if ability.identifier in _NEUTRAL_ABILITY_IDENTIFIERS
                else ability
                for ability in converted.abilities
            ),
        )


def _use_case() -> InferOneOnOneBattleUseCase:
    """创建 HTTP 边界使用的完整推演 composition root。

    Returns:
        使用物化视图 repository、透明中性特性假设和精确图求解器的 application 用例。
    """
    return _JourneyInferenceUseCase(
        repository=MaterializedViewBattleInferenceRepository(),
        effect_factory=TransparentPokemonChampionEffectFactory(),
    )


def _command(
    request: DragoniteWeavileJourneyRequest,
) -> InferFixedOneOnOneBattleCommand:
    """把受控页面输入转换为固定 1v1 推演命令。

    Args:
        request: 快龙特性、玛纽拉行动方案和双方能力预设。

    Returns:
        只允许快龙使用劈瓦、玛纽拉使用冰冻拳或击掌奇袭组合的固定命令。
    """
    pressure_plan = request.weavile_plan == "fake-out-pressure"
    return InferFixedOneOnOneBattleCommand(
        rules=BattleInferenceRules(),
        attacker=PokemonInferenceSelection(
            pokemon_id=_DRAGONITE_ID,
            move_ids=(_BRICK_BREAK_ID,),
            ability_identifier=request.dragonite_ability,
            stat_preset_key=request.dragonite_stat_preset,
        ),
        defender=PokemonInferenceSelection(
            pokemon_id=_WEAVILE_ID,
            move_ids=(
                (_ICE_PUNCH_ID, _FAKE_OUT_ID)
                if pressure_plan
                else (_ICE_PUNCH_ID,)
            ),
            ability_identifier="pressure",
            stat_preset_key=request.weavile_stat_preset,
        ),
        attacker_policy=BattleActionPolicyKind.FIRST_LEGAL,
        defender_policy=(
            BattleActionPolicyKind.UNIFORM_RANDOM
            if pressure_plan
            else BattleActionPolicyKind.FIRST_LEGAL
        ),
    )


async def dragonite_vs_weavile(
    request: DragoniteWeavileJourneyRequest,
) -> BattleInferenceJourneyResponse:
    """执行快龙 vs 玛纽拉固定旅程并返回可解释概率结果。

    Args:
        request: 页面允许调整的受控场景参数。

    Returns:
        配置、胜负平概率、期望回合、图统计、代表路径和机制覆盖。

    Raises:
        HTTPException: 规则轴或 Pokémon 资料不存在时返回 404；输入不能收敛或图无法
            完整求解时返回 422。
    """
    try:
        result = _use_case().execute_fixed(_command(request))
    except BattleInferenceProfileNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (BattleInferenceExecutionError, ConfigurationSpaceError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return battle_inference_journey_response(result)


urlpatterns = [
    {
        "path": "/dragonite-vs-weavile",
        "endpoint": dragonite_vs_weavile,
        "methods": ["POST"],
        "response_model": BattleInferenceJourneyResponse,
        "summary": "推演快龙 vs 玛纽拉的多回合结果",
    },
]
