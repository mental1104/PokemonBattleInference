import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const styles = readFileSync('src/components/PokemonSummaryCard.css', 'utf8');

describe('PokemonSummaryCard responsive styles', () => {
  it('uses one desktop size variable for the image and placeholder slot', () => {
    /**
     * 桌面双栏布局需要把摘要图片从原来的 72px 提升到明显更醒目的 120px，同时图片和失败占位必须
     * 共享同一个尺寸来源。测试直接检查组件样式合同：容器声明 120px 自定义属性，grid 第一列引用
     * 该属性，pokemon-sprite 的宽高也使用同一变量并保留 object-fit contain。这样既避免多个 selector
     * 散落 magic number，也保证真实图片和 placeholder 永远占用相同区域，不会在加载失败时产生跳动。
     */
    expect(styles).toMatch(
      /\.pokemon-summary-card\s*\{[\s\S]*--pokemon-summary-sprite-size:\s*120px;/,
    );
    expect(styles).toMatch(
      /\.pokemon-summary-card \.summary-layout\s*\{[\s\S]*grid-template-columns:\s*var\(--pokemon-summary-sprite-size\) minmax\(0, 1fr\);/,
    );
    expect(styles).toMatch(
      /\.pokemon-summary-card \.pokemon-sprite\s*\{[\s\S]*width:\s*var\(--pokemon-summary-sprite-size\);[\s\S]*height:\s*var\(--pokemon-summary-sprite-size\);[\s\S]*object-fit:\s*contain;/,
    );
  });

  it('reduces the same visual slot to eighty eight pixels on narrow screens', () => {
    /**
     * 760px 以下页面会切换为单栏，其中约 320px 的窄视口仍需保留清晰图片且不能产生横向滚动。
     * 测试确认 media query 继续作用于同一个 pokemon-summary-card 容器，把共享尺寸变量调整为 88px，
     * 同时缩小卡片 padding 和 grid gap；图片、占位与文字仍沿用桌面相同结构，不使用绝对定位覆盖内容。
     * 该合同固定移动端最低辨识度，并让 minmax(0, 1fr) 为名称、identifier 和属性标签保留可收缩空间。
     */
    expect(styles).toMatch(/@media \(max-width:\s*760px\)/);
    expect(styles).toMatch(
      /@media \(max-width:\s*760px\)[\s\S]*\.pokemon-summary-card\s*\{[\s\S]*--pokemon-summary-sprite-size:\s*88px;[\s\S]*padding:\s*12px;/,
    );
    expect(styles).toMatch(
      /@media \(max-width:\s*760px\)[\s\S]*\.pokemon-summary-card \.summary-layout\s*\{[\s\S]*gap:\s*12px;/,
    );
    expect(styles).not.toContain('position: absolute');
  });
});
