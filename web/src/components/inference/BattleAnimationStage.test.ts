import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type { BattleReportPresenterContext } from '../../presenters/battleEventPresenter';
import BattleAnimationStage from './BattleAnimationStage.vue';

const CONTEXT: BattleReportPresenterContext = {
  rulesetId: 'pokemon-champion',
  sides: {
    attacker: { pokemonId: 149, name: '快龙', maxHp: 166 },
    defender: { pokemonId: 149, name: '快龙', maxHp: 198 },
  },
  moveNames: { 337: '龙爪' },
};

describe('BattleAnimationStage', () => {
  it('uses the player back sprite and opponent front sprite in the battle layout', () => {
    /** 该测试锁住动画战场的站位资源合同：己方位于左下并请求 back_default，对手位于右上并请求 front_default。双快龙镜像战斗中双方 pokemon_id 相同，如果 slot 混淆，肉眼会看到两个同向正面图，因此必须在组件层直接断言图片 URL，避免物化视图和前端 fallback 的问题掩盖站位错误。 */
    const wrapper = mount(BattleAnimationStage, {
      props: {
        report: null,
        context: CONTEXT,
      },
    });

    const attackerImage = wrapper.get('.battle-animation-side--attacker img');
    const defenderImage = wrapper.get('.battle-animation-side--defender img');

    expect(attackerImage.attributes('src')).toContain('slot=back_default');
    expect(defenderImage.attributes('src')).toContain('slot=front_default');
  });
});
