import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import type { PokemonDetail } from '../api/calculator';
import PokemonSummaryCard from './PokemonSummaryCard.vue';

const SCIZOR: PokemonDetail = {
  pokemon_id: 212,
  identifier: 'scizor',
  display_name: '巨钳螳螂',
  form_identifier: null,
  types: ['bug', 'steel'],
  type_names: ['虫', '钢'],
  sprite_url: '/api/v1/assets/pokemon/212/sprite',
  base_stats: {
    hp: 70,
    attack: 130,
    defense: 100,
    special_attack: 55,
    special_defense: 80,
    speed: 65,
  },
};

describe('PokemonSummaryCard', () => {
  it('renders the selected pokemon image in the responsive visual slot', () => {
    /**
     * 选中 Pokémon 后，摘要卡必须使用统一的 pokemon-summary-card 响应式容器，并把图片放入
     * pokemon-sprite 视觉槽位。测试同时固定图片 URL、alt、懒加载属性和名称信息，确保放大样式
     * 只改变视觉占比，不会破坏现有图片接口、可访问性文本或摘要内容；攻击方和防守方复用同一个
     * 组件，因此该结构断言也保护双方使用完全一致的图片尺寸与布局规则。
     */
    const wrapper = mount(PokemonSummaryCard, { props: { pokemon: SCIZOR } });

    const card = wrapper.get('[data-testid="pokemon-summary-card"]');
    const visual = wrapper.get('[data-testid="pokemon-summary-visual"]');

    expect(card.classes()).toEqual(expect.arrayContaining(['summary-box', 'pokemon-summary-card']));
    expect(visual.element.tagName).toBe('IMG');
    expect(visual.classes()).toContain('pokemon-sprite');
    expect(visual.attributes('src')).toBe(SCIZOR.sprite_url);
    expect(visual.attributes('alt')).toBe(SCIZOR.display_name);
    expect(visual.attributes('loading')).toBe('lazy');
    expect(wrapper.text()).toContain('巨钳螳螂');
    expect(wrapper.text()).toContain('scizor');
  });

  it('keeps the same visual slot when the sprite fails to load', async () => {
    /**
     * sprite 请求失败时，组件不能移除整个图片区域或挤压右侧名称和属性标签。测试先触发 img error，
     * 再确认视觉槽位切换为同时带 pokemon-sprite 与 placeholder 的占位元素，并继续位于相同的
     * pokemon-summary-card 容器中；占位元素保持 aria-hidden，名称和属性仍然可见。该场景保护成功
     * 图片与失败占位共享同一套桌面和移动端尺寸变量，避免加载失败造成明显布局跳动或阻断计算流程。
     */
    const wrapper = mount(PokemonSummaryCard, { props: { pokemon: SCIZOR } });

    await wrapper.get('img.pokemon-sprite').trigger('error');

    const visual = wrapper.get('[data-testid="pokemon-summary-visual"]');
    expect(wrapper.find('img.pokemon-sprite').exists()).toBe(false);
    expect(visual.element.tagName).toBe('DIV');
    expect(visual.classes()).toEqual(expect.arrayContaining(['pokemon-sprite', 'placeholder']));
    expect(visual.attributes('aria-hidden')).toBe('true');
    expect(wrapper.get('[data-testid="pokemon-summary-card"]').classes()).toContain(
      'pokemon-summary-card',
    );
    expect(wrapper.text()).toContain('巨钳螳螂');
    expect(wrapper.text()).toContain('虫');
    expect(wrapper.text()).toContain('钢');
  });
});
