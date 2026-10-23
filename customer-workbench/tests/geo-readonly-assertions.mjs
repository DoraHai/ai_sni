import assert from 'node:assert/strict';

// Check the rendered built app, including associated and accessible control labels.
export async function assertNoPatrolControls(page) {
  const controls = await page.$$eval('#app button, #app input, #app select, #app textarea, #app a, #app [role="switch"], #app [role="button"], #app [data-resource], #app [data-params]', (nodes) =>
    nodes.map((node) => [node.textContent, node.getAttribute('aria-label'), node.name, node.id,
      node.getAttribute('href'), ...Object.values(node.dataset),
      ...Array.from(node.labels || [], (label) => label.textContent)].filter(Boolean).join(' ')));
  for (const label of controls)
    assert.doesNotMatch(label, /自动.{0,12}(检测|巡检|采集)|手动.{0,12}(检测|次数|上限)|每天手动|每日手动|强制关停|强制关闭|解锁|visibility-patrol|self.service|manual.daily.limit|manual.limit.revision/i);
  assert.equal(await page.$('#app [name="enabled"], #app [name="manual_daily_limit"], #app [name="expected_revision"]'), null);
}
