import pytest

from pokeop.domain.battle.status.cleanup import clear_status_on_switch_out
from pokeop.domain.battle.status.kinds import VolatileStatusKind
from tests.domain.battle.helpers import CombatantStatusFactory


def test_switch_out_cleanup_clears_confusion_and_infatuation():
    """
    验证宝可梦离场时会清理所有会随离场消失的临时状态。本用例使用同时处于混乱和着迷的战斗状态作为输入，
    调用离场清理函数后，断言两个 volatile status 都不存在。这个测试锁住离场清理的基本契约，避免后续扩展
    交换、轮换或强制退场流程时，把混乱和着迷错误地保留到下一次上场，从而影响后续行动判定。
    """
    status = CombatantStatusFactory.confused_and_infatuated()

    cleared = clear_status_on_switch_out(status)

    assert not cleared.has_volatile(VolatileStatusKind.CONFUSION)
    assert not cleared.has_volatile(VolatileStatusKind.INFATUATION)


@pytest.mark.parametrize(
    "non_volatile",
    CombatantStatusFactory.persistent_non_volatile_statuses(),
)
def test_switch_out_cleanup_preserves_non_volatile_statuses(non_volatile):
    """
    验证宝可梦离场时不会清理会跨离场保留的主要异常状态。本用例对睡眠、麻痹、烧伤、冰冻、中毒和剧毒逐一
    构造状态快照，同时附带混乱和着迷作为待清理的临时状态。清理完成后应只移除 volatile status，并完整保留
    原来的 non-volatile status，确保离场规则不会破坏后续回合、换入后状态持续和伤害结算的基础语义。
    """
    status = CombatantStatusFactory.confused_and_infatuated(non_volatile)

    cleared = clear_status_on_switch_out(status)

    assert cleared.non_volatile == non_volatile
    assert not cleared.volatile
