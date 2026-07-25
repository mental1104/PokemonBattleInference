import { describe, expect, it } from 'vitest';
import candidateStyles from '../components/inference/CandidateMovePoolSelector.css?raw';
import viewStyles from './BattleInferenceView.css?raw';

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
