import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';

const { chromium } = createRequire('/build/p6-browser/package.json')('playwright');

/** side 为真实页面列，query 为中文名称，id 为唯一知识 ID；通过用户搜索/点击加载完整资料。 */
async function selectPokemon(page, side, query, id) {
  const column = page.getByTestId(`${side}-column`);
  await column.getByTestId('pokemon-search-input').fill(query);
  await column.locator(`[data-pokemon-id="${id}"]`).click();
}

/** 验收原 Vue→Nginx→Go→独立 Core 的真实选择与计算；报告只写本次私有目录。 */
async function main() {
  const endpoint = process.env.PBI_STACK_WEB_URL;
  assert.ok(endpoint, 'PBI_STACK_WEB_URL is required');
  const reports = '/reports/browser';
  await mkdir(reports, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(endpoint, { waitUntil: 'networkidle' });
    await page.getByRole('heading', { name: 'Pokémon 伤害计算器' }).waitFor();
    await selectPokemon(page, 'attacker', '巨钳螳螂', 212);
    await selectPokemon(page, 'defender', '幸福蛋', 242);
    await page.getByTestId('move-search-input').fill('子弹拳');
    await page.getByTestId('embedded-move-list').getByRole('button', { name: /子弹拳/ }).click();
    const received = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/v1/calculator/damage'));
    await page.getByRole('button', { name: '开始计算', exact: true }).click();
    const response = await received;
    assert.equal(response.status(), 200, 'real calculator request must succeed');
    const result = await response.json();
    assert.equal(result.damage.rolls.length, 16);
    assert.ok(result.damage.min > 0 && result.damage.max >= result.damage.min);
    const damage = `${result.damage.min}-${result.damage.max}`;
    await page.locator('.result-band .metric strong').filter({ hasText: damage }).waitFor();
    assert.equal(await page.locator('.action-band .error').count(), 0);
    assert.deepEqual(errors, [], 'the real application must not raise JavaScript errors');
    await writeFile(`${reports}/calculator-response.json`, JSON.stringify(result, null, 2));
    await page.screenshot({ path: `${reports}/desktop-calculator.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: `${reports}/phone-calculator.png`, fullPage: true });
    const dimensions = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: innerWidth }));
    assert.ok(dimensions.content <= dimensions.viewport + 1, 'phone layout must fit the viewport');
    await writeFile(`${reports}/acceptance.json`, JSON.stringify({ status: 'PASS', pokemon: [212, 242], move: 418, damage, dimensions, errors }, null, 2));
  } catch (error) {
    await page.screenshot({ path: `${reports}/failure.png`, fullPage: true });
    await writeFile(`${reports}/failure.txt`, `${error.stack}\n${errors.join('\n')}`);
    throw error;
  } finally {
    await context.tracing.stop({ path: `${reports}/trace.zip` });
    await browser.close();
  }
}

await main();
