import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { semEvidenceSourceRevision, semEvidenceView } from './sem-evidence-preview.mjs';

const here = dirname(fileURLToPath(import.meta.url));

test('prototype display helper stays identical to the reviewed integration source', async () => {
  const [prototype, integration] = await Promise.all([
    readFile(resolve(here, 'sem-cockpit-display.mjs'), 'utf8'),
    readFile(resolve(here, '../../integrations/sem-cockpit/display.mjs'), 'utf8'),
  ]);
  assert.equal(prototype, integration);
  assert.equal(semEvidenceSourceRevision, '70018543b9e08edf411c0ac0263ff1a38f925502');
});

test('missing report scenario remains a labelled subtotal', () => {
  const view = semEvidenceView('missing');
  assert.equal(view.result.state, 'partial');
  assert.equal(view.result.value, null);
  assert.equal(view.result.observedValue, 42110);
  assert.match(view.result.text, /已观测小计/);
  assert.deepEqual(view.result.missingDates, ['2026-09-03']);
});

test('observed zero stays different from missing data', () => {
  const view = semEvidenceView('zero');
  assert.equal(view.result.state, 'available');
  assert.equal(view.result.value, 0);
  assert.equal(view.result.text, '0');
  assert.match(view.explanation, /与没有报告不同/);
});

test('partial phone evidence never becomes a complete total', () => {
  const view = semEvidenceView('phone');
  assert.equal(view.result.state, 'partial');
  assert.equal(view.result.value, null);
  assert.equal(view.result.knownSubtotal, 3);
  assert.match(view.result.text, /已知小计 3 次/);
  assert.match(view.explanation, /不代表电话拨通/);
});
