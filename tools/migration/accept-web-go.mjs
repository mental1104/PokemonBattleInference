import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';

const { chromium } = createRequire('/build/p6-browser/package.json')('playwright');
const requireSprites = process.env.PBI_STACK_REQUIRE_SPRITES === '1';
const loadedImages = [];

/** page为真实页面，selector定位实际img；成功后将尺寸和公开HTTP原文摘要写入loadedImages。
 * 占位div、破图、非PNG及代理错误都会失败；只在显式提供素材的完整栈验收中调用。
 */
async function verifyLoadedImage(page, selector) {
  const element = page.locator(selector).first();
  await element.scrollIntoViewIfNeeded();
  // Vue遇到破图会切成占位节点；限定等待时间并在错误中保留具体选择器。
  await page.waitForFunction(value => {
    const image = document.querySelector(value);
    return image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0;
  }, selector, { timeout: 30000 }).catch(error => {
    throw new Error(`Image did not decode: ${selector}`, { cause: error });
  });
  const dimensions = await element.evaluate(image => ({ width: image.naturalWidth, height: image.naturalHeight, source: image.currentSrc }));
  const response = await page.request.get(dimensions.source);
  assert.equal(response.status(), 200, 'the image must be served by the real API');
  assert.match(response.headers()['content-type'], /^image\/png/);
  const bytes = await response.body();
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  loadedImages.push({ selector, ...dimensions, sha256: createHash('sha256').update(bytes).digest('hex'), etag: response.headers().etag });
}

/** side 为真实页面列，query 为中文名称，id 为唯一知识 ID；通过用户搜索/点击加载完整资料。 */
async function selectPokemon(page, side, query, id) {
  const column = page.getByTestId(`${side}-column`);
  await column.getByTestId('pokemon-search-input').fill(query);
  await column.locator(`[data-pokemon-id="${id}"]`).click();
}

/** page为计算器真实页面，reports保存公开请求/响应；返回本次创建再删除的配置身份。
 * 新建、编辑、重载和删除全部通过Vue可见控件；公开列表独立核对持久化，不修改应用状态。
 */
async function verifyConfigurationManagement(page, reports) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const column = page.getByTestId('attacker-column');
  await column.getByRole('button', { name: '管理配置', exact: true }).click();
  const editor = page.locator('.stat-config-editor');
  await page.getByRole('button', { name: '新增配置', exact: true }).click();
  await editor.getByLabel('配置名称', { exact: true }).fill('Browser persisted attack');
  await editor.locator('label').filter({ hasText: '适用 Pokémon' }).locator('select').selectOption('pokemon');
  await editor.locator('input[type="number"]').nth(0).fill('252');
  await editor.locator('input[type="number"]').nth(1).fill('100');
  const createdResponse = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/v1/stat-configurations'));
  await editor.getByRole('button', { name: '保存配置', exact: true }).click();
  const creation = await createdResponse;
  assert.equal(creation.status(), 201);
  const created = await creation.json();
  await writeFile(`${reports}/configuration-create-request.json`, creation.request().postData());
  await writeFile(`${reports}/configuration-created.json`, JSON.stringify(created, null, 2));
  assert.equal(created.name, 'Browser persisted attack');
  assert.equal(created.pokemon_id, 212);
  assert.equal(created.evs.hp, 252);
  assert.equal(created.evs.attack, 100);
  // 等刷新完成再编辑同一条记录，避免把创建后的异步表单回填误判为编辑。
  await page.locator('.stat-config-sidebar-item.active').filter({ hasText: created.name }).waitFor();
  await editor.getByLabel('配置名称', { exact: true }).fill('Browser edited attack');
  await editor.locator('label').filter({ hasText: '性格' }).locator('select').selectOption('adamant');
  await editor.locator('input[type="number"]').nth(1).fill('252');
  const updatedResponse = page.waitForResponse(response => response.request().method() === 'PUT' && response.url().includes('/v1/stat-configurations/'));
  await editor.getByRole('button', { name: '保存配置', exact: true }).click();
  const update = await updatedResponse;
  assert.equal(update.status(), 200);
  const updated = await update.json();
  await writeFile(`${reports}/configuration-update-request.json`, update.request().postData());
  await writeFile(`${reports}/configuration-updated.json`, JSON.stringify(updated, null, 2));
  assert.equal(updated.id, created.id);
  assert.equal(updated.name, 'Browser edited attack');
  assert.equal(updated.nature_id, 'adamant');
  assert.equal(updated.evs.attack, 252);
  assert.equal(updated.evs.hp, 252);
  assert.notEqual(updated.snapshot_profile_id, created.snapshot_profile_id);
  await page.reload({ waitUntil: 'networkidle' });
  await selectPokemon(page, 'attacker', '巨钳螳螂', 212);
  await column.getByRole('button', { name: '管理配置', exact: true }).click();
  await page.locator('.stat-config-sidebar-item').filter({ hasText: updated.name }).click();
  assert.equal(await editor.getByLabel('配置名称', { exact: true }).inputValue(), updated.name);
  assert.equal(await editor.locator('label').filter({ hasText: '性格' }).locator('select').inputValue(), 'adamant');
  assert.equal(await editor.locator('input[type="number"]').nth(1).inputValue(), '252');
  await page.screenshot({ path: `${reports}/configuration-reloaded.png`, fullPage: true });
  const listURL = `${new URL(creation.url()).origin}/api/v1/stat-configurations?role=attacker&pokemon_id=212`;
  const persisted = await page.request.get(listURL);
  assert.equal(persisted.status(), 200);
  const before = await persisted.json();
  await writeFile(`${reports}/configuration-persisted.json`, JSON.stringify(before, null, 2));
  assert.deepEqual(before.items.find(item => item.id === created.id), updated);
  await editor.getByRole('button', { name: '删除', exact: true }).click();
  const deletedResponse = page.waitForResponse(response => response.request().method() === 'DELETE' && response.url().includes('/v1/stat-configurations/'));
  await page.getByRole('button', { name: '确认删除', exact: true }).click();
  assert.equal((await deletedResponse).status(), 204);
  await page.locator('.stat-config-sidebar-item').filter({ hasText: updated.name }).waitFor({ state: 'detached' });
  const after = await page.request.get(listURL);
  assert.equal(after.status(), 200);
  const deleted = await after.json();
  await writeFile(`${reports}/configuration-after-delete.json`, JSON.stringify(deleted, null, 2));
  assert.ok(deleted.items.every(item => item.id !== created.id));
  await page.locator('.stat-config-modal header').getByRole('button', { name: '×', exact: true }).click();
  return { id: created.id, status: 'created_updated_reloaded_deleted' };
}

/** page沿用真实Vue页面，reports归档求解输入/响应/截图；返回实际候选数量与新配置身份。
 * 通过速度目标同时覆盖已有配置验证和EV/IV反推，最后将真实候选保存为212的双角色配置。
 */
async function verifySolver(page, reports) {
  await page.getByRole('button', { name: '配置反向求解', exact: true }).click();
  const subject = page.locator('.solver-side');
  await subject.getByTestId('pokemon-search-input').fill('巨钳螳螂');
  await subject.locator('[data-pokemon-id="212"]').click();
  await subject.locator('.preset-button').filter({ hasText: '无投入' }).click();
  await page.getByTestId('open-speed-goal-dialog').click();
  const dialog = page.getByRole('dialog');
  await dialog.getByTestId('pokemon-search-input').fill('幸福蛋');
  await dialog.locator('[data-pokemon-id="242"]').click();
  await dialog.locator('.preset-button').filter({ hasText: '无投入' }).click();
  await page.getByTestId('confirm-speed-goal-dialog').click();
  await page.getByTestId('speed-goal-summary-row').waitFor();
  const presetReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/configuration_solver/solve'));
  await page.getByRole('button', { name: '开始求解', exact: true }).click();
  const presetResponse = await presetReceived;
  assert.equal(presetResponse.status(), 200);
  const preset = await presetResponse.json();
  await writeFile(`${reports}/solver-preset-request.json`, presetResponse.request().postData());
  await writeFile(`${reports}/solver-preset-result.json`, JSON.stringify(preset, null, 2));
  assert.equal(preset.reachable, true);
  assert.ok(preset.candidates.length > 0);
  const speed = preset.candidates[0].speed_goals[0];
  assert.equal(speed.subject_speed, 85);
  assert.equal(speed.target_speed, 75);
  assert.equal(speed.speed_margin, 10);
  assert.equal(speed.satisfied, true);
  await page.locator('.speed-evidence-row').filter({ hasText: '己方 Speed 85 / 目标 Speed 75' }).waitFor();
  await page.getByTestId('spread-mode-toggle').click();
  const spreadReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/configuration_solver/search-spreads'));
  await page.getByRole('button', { name: '反推配置', exact: true }).click();
  const spreadResponse = await spreadReceived;
  assert.equal(spreadResponse.status(), 200);
  const spread = await spreadResponse.json();
  await writeFile(`${reports}/solver-spread-request.json`, spreadResponse.request().postData());
  await writeFile(`${reports}/solver-spread-result.json`, JSON.stringify(spread, null, 2));
  assert.equal(spread.reachable, true);
  assert.ok(spread.candidates.length > 0 && spread.candidates.length <= 10);
  assert.ok(spread.candidates.every(candidate => candidate.speed_goals.every(goal => goal.satisfied && goal.subject_speed > goal.target_speed)));
  const savedReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/v1/stat-configurations'));
  await page.getByRole('button', { name: '添加到专属配置', exact: true }).first().click();
  const savedResponse = await savedReceived;
  assert.equal(savedResponse.status(), 201);
  const saved = await savedResponse.json();
  await writeFile(`${reports}/solver-saved-configuration.json`, JSON.stringify(saved, null, 2));
  assert.equal(saved.pokemon_id, 212);
  assert.equal(saved.role, 'both');
  assert.deepEqual(saved.evs, spread.candidates[0].evs);
  assert.deepEqual(saved.ivs, spread.candidates[0].ivs);
  await page.getByRole('button', { name: '已添加到专属配置', exact: true }).first().waitFor();
  await page.screenshot({ path: `${reports}/solver-spread-saved.png`, fullPage: true });
  const damageGoals = await verifyDamageGoals(page, reports);
  return { presetCandidates: preset.candidates.length, spreadCandidates: spread.candidates.length, savedConfiguration: saved.id, damageGoals };
}

/** page为已有212及242速度目标的求解页面，reports保留攻防草稿/提交和最终结果证据。
 * 返回组合目标与纯伤害目标的真实候选数；同时验证编辑次数导致不可达时页面正确显示拒绝。
 */
async function verifyDamageGoals(page, reports) {
  await page.getByTestId('spread-mode-toggle').click();
  await page.locator('.solver-side .preset-button').filter({ hasText: '无投入' }).click();
  for (const goal of [
    { kind: 'attack', move: '子弹拳', repetitions: '3', label: '击倒次数' },
    { kind: 'defense', move: '拍击', repetitions: '1', label: '承受次数' },
  ]) {
    await page.getByTestId(`open-${goal.kind}-goal-dialog`).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByTestId('pokemon-search-input').fill('幸福蛋');
    await dialog.locator('[data-pokemon-id="242"]').click();
    await dialog.locator('.preset-button').filter({ hasText: '无投入' }).click();
    await dialog.getByLabel(goal.label, { exact: true }).fill(goal.repetitions);
    await dialog.getByTestId('move-search-input').fill(goal.move);
    await dialog.getByTestId('embedded-move-list').getByRole('button', { name: new RegExp(goal.move) }).click();
    await page.getByTestId('confirm-goal-dialog').click();
  }
  const mixedReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/configuration_solver/solve'));
  await page.getByRole('button', { name: '开始求解', exact: true }).click();
  const mixedResponse = await mixedReceived;
  assert.equal(mixedResponse.status(), 200);
  const mixed = await mixedResponse.json();
  await writeFile(`${reports}/solver-mixed-request.json`, mixedResponse.request().postData());
  await writeFile(`${reports}/solver-mixed-result.json`, JSON.stringify(mixed, null, 2));
  assert.equal(mixed.reachable, true);
  assert.equal(mixed.candidates.length, 1);
  const candidate = mixed.candidates[0];
  assert.equal(candidate.goals.length, 2);
  const attack = candidate.goals.find(goal => goal.kind === 'attack');
  const defense = candidate.goals.find(goal => goal.kind === 'defense');
  assert.equal(attack.move.move_id, 418);
  assert.equal(attack.selected_damage, 114);
  assert.equal(attack.total_damage, 342);
  assert.equal(attack.hp_threshold, 330);
  assert.equal(attack.satisfied, true);
  assert.equal(defense.move.move_id, 1);
  assert.equal(defense.selected_damage, 4);
  assert.equal(defense.hp_threshold, 145);
  assert.equal(defense.satisfied, true);
  assert.equal(candidate.speed_goals.length, 1);
  assert.equal(candidate.speed_goals[0].satisfied, true);
  await page.locator('.evidence-row').filter({ hasText: '3 次 × 114' }).waitFor();
  await page.screenshot({ path: `${reports}/solver-mixed.png`, fullPage: true });
  // 从页面删除速度目标，确保不携带扩展字段的原纯伤害调用路径也得到相同攻防证据。
  await page.getByRole('button', { name: '删除速度目标', exact: true }).click();
  const damageReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/configuration_solver/solve'));
  await page.getByRole('button', { name: '开始求解', exact: true }).click();
  const damageResponse = await damageReceived;
  assert.equal(damageResponse.status(), 200);
  const damage = await damageResponse.json();
  await writeFile(`${reports}/solver-damage-request.json`, damageResponse.request().postData());
  await writeFile(`${reports}/solver-damage-result.json`, JSON.stringify(damage, null, 2));
  assert.equal(damage.reachable, true);
  assert.deepEqual(damage.candidates[0].goals, candidate.goals);
  assert.equal(Object.hasOwn(damageResponse.request().postDataJSON(), 'speed_goals'), false);
  await page.getByRole('button', { name: '查看并编辑攻目标 幸福蛋', exact: true }).click();
  await page.getByRole('dialog').getByLabel('击倒次数', { exact: true }).fill('1');
  await page.getByTestId('confirm-goal-dialog').click();
  const rejectedReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/configuration_solver/solve'));
  await page.getByRole('button', { name: '开始求解', exact: true }).click();
  const rejectedResponse = await rejectedReceived;
  assert.equal(rejectedResponse.status(), 200);
  const rejected = await rejectedResponse.json();
  await writeFile(`${reports}/solver-unreachable-request.json`, rejectedResponse.request().postData());
  await writeFile(`${reports}/solver-unreachable-result.json`, JSON.stringify(rejected, null, 2));
  assert.equal(rejected.reachable, false);
  assert.equal(rejected.candidates.length, 0);
  const failed = rejected.rejected_goals.find(goal => goal.kind === 'attack');
  assert.equal(failed.satisfied, false);
  assert.equal(failed.repetitions, 1);
  assert.equal(failed.total_damage, 114);
  await page.getByRole('heading', { name: '当前不可达', exact: true }).waitFor();
  await page.locator('.evidence-row.failed').filter({ hasText: '1 次 × 114' }).waitFor();
  await page.screenshot({ path: `${reports}/solver-unreachable.png`, fullPage: true });
  return { mixedCandidates: mixed.candidates.length, damageCandidates: damage.candidates.length, editedUnreachable: true };
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
 * 通过可见控件提交并探索/回退/改选分支，另用公开HTTP核对终态，不写入应用内部状态。
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
  if (requireSprites) {
    await verifyLoadedImage(page, '.battle-tree-screen .battle-animation-side--attacker img');
    await verifyLoadedImage(page, '.battle-tree-screen .battle-animation-side--defender img');
  }
  await page.screenshot({ path: `${reports}/task-graph.png`, fullPage: true });
  // 根窗口可见后继续真实展开行动组，选择一条正式边，证明分页/路径前进合同也可由Web使用。
  const outcomesReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/outcomes'));
  await page.locator('.battle-tree-group > button').first().click();
  const outcomes = await outcomesReceived;
  assert.equal(outcomes.status(), 200);
  const outcomeResult = await outcomes.json();
  await writeFile(`${reports}/task-outcomes.json`, JSON.stringify(outcomeResult, null, 2));
  assert.ok(outcomeResult.transition_group.outcomes.length > 0);
  await page.getByRole('button', { name: '原始', exact: true }).click();
  const advanceReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/advance'));
  await page.locator('.battle-tree-exact-edge').first().click();
  const advance = await advanceReceived;
  assert.equal(advance.status(), 200);
  const advanced = await advance.json();
  await writeFile(`${reports}/task-advanced.json`, JSON.stringify(advanced, null, 2));
  assert.equal(advanced.cursor.steps.length, 1);
  assert.equal(advanced.node.node_id, outcomeResult.transition_group.outcomes[0].target_node_id);
  await page.locator('.battle-tree-column').nth(1).waitFor();
  assert.deepEqual(advanced.cumulative_probability, outcomeResult.transition_group.outcomes[0].cumulative_probability);
  await page.getByTestId('battle-current-node').getByText(`当前节点 · #${advanced.node.node_id}`, { exact: true }).waitFor();
  assert.equal(await page.getByTestId('battle-current-node').locator('footer small').innerText(), '1 / 256');
  await page.screenshot({ path: `${reports}/task-graph-advanced.png`, fullPage: true });
  // 从真实祖先节点返回ROOT，旧分支必须截断且精确概率恢复，不能叠乘之前路径。
  await page.locator('.battle-tree-column__node').first().click();
  await page.getByTestId('battle-current-node').getByText('当前节点 · #0', { exact: true }).waitFor();
  assert.equal(await page.locator('.battle-tree-column').count(), 1);
  assert.equal(await page.getByTestId('battle-current-node').locator('footer small').innerText(), '1 / 1');
  const repeatedOutcomesReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/outcomes'));
  await page.locator('.battle-tree-group > button').first().click();
  const repeatedOutcomes = await repeatedOutcomesReceived;
  assert.equal(repeatedOutcomes.status(), 200);
  assert.deepEqual(await repeatedOutcomes.json(), outcomeResult, 'root outcomes must remain stable after returning');
  await page.getByRole('button', { name: '聚合', exact: true }).click();
  await page.locator('.battle-tree-outcome-bucket').first().waitFor();
  assert.equal(await page.locator('.battle-tree-exact-edge').count(), 0);
  await page.screenshot({ path: `${reports}/task-graph-grouped.png`, fullPage: true });
  await page.getByRole('button', { name: '原始', exact: true }).click();
  const alternative = outcomeResult.transition_group.outcomes[1];
  assert.ok(alternative, 'the fixed real graph must expose another exact outcome');
  assert.notEqual(alternative.target_node_id, advanced.node.node_id);
  const changedReceived = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/advance'));
  await page.locator('.battle-tree-exact-edge').nth(1).click();
  const changedResponse = await changedReceived;
  assert.equal(changedResponse.status(), 200);
  const changed = await changedResponse.json();
  await writeFile(`${reports}/task-branch-changed.json`, JSON.stringify(changed, null, 2));
  assert.equal(changed.cursor.steps.length, 1);
  assert.equal(changed.cursor.steps[0].edge_id, alternative.edge_id);
  assert.equal(changed.node.node_id, alternative.target_node_id);
  assert.deepEqual(changed.cumulative_probability, alternative.cumulative_probability);
  await page.getByTestId('battle-current-node').getByText(`当前节点 · #${changed.node.node_id}`, { exact: true }).waitFor();
  assert.equal(await page.getByTestId('battle-current-node').locator('footer small').innerText(), '1 / 128');
  await page.screenshot({ path: `${reports}/task-graph-branch-changed.png`, fullPage: true });
  return { jobId, status: status.status, nodes: results.items[0].node_count, edges: results.items[0].edge_count,
    branchRevisit: { first: advanced.node.node_id, changed: changed.node.node_id, probability: changed.cumulative_probability } };
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
  // 独立Playwright库没有测试runner的默认动作时限；页面缺失时必须失败并归档，不能无限挂起。
  context.setDefaultTimeout(30000);
  context.setDefaultNavigationTimeout(45000);
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
    if (requireSprites) {
      await verifyLoadedImage(page, '[data-testid="attacker-column"] img[data-testid="pokemon-summary-visual"]');
      await verifyLoadedImage(page, '[data-testid="defender-column"] img[data-testid="pokemon-summary-visual"]');
      await verifyLoadedImage(page, 'button[aria-label="steel 属性"] img');
    }
    await writeFile(`${reports}/calculator-response.json`, JSON.stringify(result, null, 2));
    await page.screenshot({ path: `${reports}/desktop-calculator.png`, fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: `${reports}/phone-calculator.png`, fullPage: true });
    const dimensions = await page.evaluate(() => ({ content: document.documentElement.scrollWidth, viewport: innerWidth }));
    assert.ok(dimensions.content <= dimensions.viewport + 1, 'phone layout must fit the viewport');
    const configuration = await verifyConfigurationManagement(page, reports);
    const solver = await verifySolver(page, reports);
    const task = await verifyPersistentTask(page, reports);
    const cancellation = await verifyRunningCancellation(page, reports);
    assert.deepEqual(errors, [], 'task pages must not raise JavaScript errors');
    await writeFile(`${reports}/acceptance.json`, JSON.stringify({ status: 'PASS', pokemon: [212, 242], move: 418, damage, dimensions, configuration, solver, task, cancellation, errors }, null, 2));
  } catch (error) {
    await page.screenshot({ path: `${reports}/failure.png`, fullPage: true });
    await writeFile(`${reports}/failure.txt`, `${error.stack}\n${errors.join('\n')}`);
    // 保存实际DOM图源，便于区分API缺图、路径错误和浏览器解码失败。
    const images = await page.locator('img').evaluateAll(elements => elements.map(element => ({
      source: element.currentSrc || element.src, complete: element.complete,
      width: element.naturalWidth, height: element.naturalHeight,
    })));
    await writeFile(`${reports}/failed-page-images.json`, JSON.stringify(images, null, 2));
    throw error;
  } finally {
    // 部分图已成功而后续缺图时也保留证据，不能等整个任务闭环通过才写入。
    await writeFile(`${reports}/images.json`, JSON.stringify(loadedImages, null, 2));
    await context.tracing.stop({ path: `${reports}/trace.zip` });
    await browser.close();
  }
}

await main();
