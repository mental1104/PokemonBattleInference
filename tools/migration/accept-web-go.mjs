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

/** page借用浏览器HTTP客户端；base为真实代理根，jobId为本次服务返回身份。
 * expected为所需生命周期状态，report为独立观察记录；返回完整公开状态，超时或其他终态报错。
 */
async function waitForJob(page, base, jobId, expected, report) {
  const observations = [];
  const deadline = Date.now() + 45000;
  let status;
  do {
    const response = await page.request.get(`${base}/api/v1/inference/jobs/${encodeURIComponent(jobId)}`);
    assert.equal(response.status(), 200, 'task status must be readable');
    status = await response.json();
    observations.push(status);
    if (status.status === expected || ['succeeded', 'failed', 'cancelled', 'completed_with_failures'].includes(status.status)) break;
    await page.waitForTimeout(500);
  } while (Date.now() < deadline);
  await writeFile(report, JSON.stringify(observations, null, 2));
  assert.equal(status.status, expected, 'the real task must reach the required state');
  return status;
}

/** page为真实Vue页面，reports为本次报告目录；返回已完成任务身份和原始资源统计。
 * 通过可见示例/组合/提交控件发起任务，另用公开HTTP核对终态，不写入应用内部状态。
 */
async function verifyPersistentTask(page, reports) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole('button', { name: '固定配置精确推演', exact: true }).click();
  await page.getByRole('button', { name: '载入双快龙龙爪示例', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '已载入双快龙' }).waitFor();
  const combinationsReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/v1/inference/move-set-combinations'));
  await page.getByRole('button', { name: '生成技能组合', exact: true }).click();
  const combinations = await combinationsReceived;
  await writeFile(`${reports}/task-combinations.json`, await combinations.body());
  assert.equal(combinations.status(), 200, 'real move combinations must succeed');
  await page.locator('input[name="attacker-move-set"]').first().check();
  await page.locator('input[name="defender-move-set"]').first().check();
  const submitted = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/v1/inference/fixed-one-on-one-jobs'));
  await page.getByRole('button', { name: '提交精确推演任务', exact: true }).click();
  const acknowledgement = await submitted;
  await writeFile(`${reports}/task-request.json`, acknowledgement.request().postData());
  await writeFile(`${reports}/task-created.json`, await acknowledgement.body());
  assert.equal(acknowledgement.status(), 202, 'the real API must accept the task');
  const { job_id: jobId } = await acknowledgement.json();
  const base = new URL(acknowledgement.url()).origin;
  // 202不能替代真正消费；保存每次公开查询，便于识别revision不匹配造成的永久排队。
  const status = await waitForJob(page, base, jobId, 'succeeded', `${reports}/task-observations.json`);
  const card = page.locator('.battle-task-item').filter({ has: page.locator(`strong[title="${jobId}"]`) });
  await card.getByText(/已完成/).waitFor();
  await card.getByRole('button', { name: '查看详情', exact: true }).click();
  await page.getByRole('heading', { name: '所有可能性的概率总和', exact: true }).waitFor();
  const resultsResponse = await page.request.get(`${base}/api/v1/inference/configuration-jobs/${encodeURIComponent(jobId)}/results`);
  assert.equal(resultsResponse.status(), 200);
  const results = await resultsResponse.json();
  await writeFile(`${reports}/task-results.json`, JSON.stringify(results, null, 2));
  assert.equal(results.total, 1);
  assert.equal(results.items[0].status, 'succeeded');
  assert.equal(results.items[0].explanation?.version, 'battle-inference.explanation.v1');
  await page.screenshot({ path: `${reports}/task-detail.png`, fullPage: true });
  // 完成后从真实结果页按需重算Full图，再等实际探索请求完成和树状图可见。
  const graphReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/graph'));
  const explorationReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/explore'));
  await page.getByRole('button', { name: '打开树状图和战报', exact: true }).click();
  const graph = await graphReceived;
  await writeFile(`${reports}/task-graph.json`, await graph.body());
  assert.equal(graph.status(), 200, 'completed task graph must be rebuilt by Core');
  const exploration = await explorationReceived;
  await writeFile(`${reports}/task-exploration.json`, await exploration.body());
  assert.equal(exploration.status(), 200, 'the root must actually load');
  assert.ok((await exploration.json()).transition_groups.length > 0);
  await page.getByRole('heading', { name: '从起点向右追踪战斗路径', exact: true }).waitFor();
  await page.locator('.battle-tree-column').first().waitFor();
  await page.screenshot({ path: `${reports}/task-graph.png`, fullPage: true });
  return { jobId, status: status.status, nodes: results.items[0].node_count, edges: results.items[0].edge_count };
}

/** page沿用已完成任务的真实页面，reports归档取消请求及前后完整状态；返回实际取消的任务身份。
 * 四招均从正式候选控件选择，不注入延迟；只有先观察到running才点击服务器取消。
 */
async function verifyRunningCancellation(page, reports) {
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '返回', exact: true }).click();
  await page.getByRole('button', { name: '载入双快龙龙爪示例', exact: true }).click();
  for (const side of ['attacker', 'defender']) {
    for (const moveId of [17, 21, 56]) {
      const option = page.locator(`[data-testid="${side}-move-option"][data-move-id="${moveId}"]`);
      await option.click();
      assert.equal(await option.getAttribute('aria-pressed'), 'true');
    }
  }
  const combinationsReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/v1/inference/move-set-combinations'));
  await page.getByRole('button', { name: '生成技能组合', exact: true }).click();
  assert.equal((await combinationsReceived).status(), 200);
  await page.locator('input[name="attacker-move-set"]').first().check();
  await page.locator('input[name="defender-move-set"]').first().check();
  const submitted = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/v1/inference/fixed-one-on-one-jobs'));
  await page.getByRole('button', { name: '提交精确推演任务', exact: true }).click();
  const acknowledgement = await submitted;
  await writeFile(`${reports}/cancel-task-request.json`, acknowledgement.request().postData());
  await writeFile(`${reports}/cancel-task-created.json`, await acknowledgement.body());
  assert.equal(acknowledgement.status(), 202);
  const { job_id: jobId } = await acknowledgement.json();
  const base = new URL(acknowledgement.url()).origin;
  await waitForJob(page, base, jobId, 'running', `${reports}/cancel-task-running.json`);
  const card = page.locator('.battle-task-item').filter({ has: page.locator(`strong[title="${jobId}"]`) });
  const cancelled = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith(`/jobs/${jobId}/cancel`));
  await card.getByRole('button', { name: '取消', exact: true }).click();
  const cancellation = await cancelled;
  await writeFile(`${reports}/cancel-task-acknowledgement.json`, await cancellation.body());
  assert.equal(cancellation.status(), 200);
  const terminal = await waitForJob(page, base, jobId, 'cancelled', `${reports}/cancel-task-terminal.json`);
  await card.getByText(/已取消/).waitFor();
  await page.screenshot({ path: `${reports}/cancel-task.png`, fullPage: true });
  return { jobId, status: terminal.status };
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
    const task = await verifyPersistentTask(page, reports);
    const cancellation = await verifyRunningCancellation(page, reports);
    assert.deepEqual(errors, [], 'task pages must not raise JavaScript errors');
    await writeFile(`${reports}/acceptance.json`, JSON.stringify({ status: 'PASS', pokemon: [212, 242], move: 418, damage, dimensions, task, cancellation, errors }, null, 2));
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
