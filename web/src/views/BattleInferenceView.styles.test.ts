import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

// Vitest 会把普通 CSS 模块转换为空导出；合同测试直接读取源码，避免把转换器行为误判为样式缺失。
const candidateStyles = readFileSync(
  'src/components/inference/CandidateMovePoolSelector.css',
  'utf8',
);
const viewStyles = readFileSync('src/views/BattleInferenceView.css', 'utf8');

describe('BattleInferenceView responsive styles', () => {
  it('collapses symmetric columns and bounded cards before a 320px viewport can overflow', () => {
    /** 页面和双侧候选池都使用可收缩 grid 列，并在窄屏改为单列，不引入固定内容宽度。 */
    expect(viewStyles).toMatch(/\.battle-side-grid\s*\{[\s\S]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);/);
    expect(viewStyles).toMatch(/@media \(max-width:\s*760px\)[\s\S]*\.battle-side-grid[\s\S]*grid-template-columns:\s*minmax\(0, 1fr\);/);
    expect(viewStyles).toMatch(/@media \(max-width:\s*420px\)[\s\S]*max-width:\s*100%;[\s\S]*min-width:\s*0;/);
    expect(candidateStyles).toMatch(/\.candidate-pool\s*\{[\s\S]*min-width:\s*0;[\s\S]*overflow:\s*hidden;/);
    expect(candidateStyles).toContain('overflow-wrap: anywhere');
  });
});
