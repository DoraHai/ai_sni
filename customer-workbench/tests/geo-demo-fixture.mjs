// Synthetic local fixture only. Never imported by production code.
import {demoToken, demoEngines} from '../js/geo-project-demo.mjs';
export function demoFixture() {
  let id = 10000;
  const counts = (samples) => {
    const mentioned = samples.filter((s) => s.mentioned === true).length;
    return {sample_count: samples.length, mentioned_count: mentioned, unknown_mention_count: 0,
      mention_rate: Math.round(1000000 * mentioned / samples.length) / 10000};
  };
  const group = (ids, probe) => {
    const questions = ids.map((qid) => ({id: qid, unit_id: qid < 85 ? 20 : 19, is_brand_probe: probe,
      question: `合成夹具问题 ${qid} <script>`, by_engine: demoEngines.map(([engine_key]) => {
        const samples = Array.from({length: 30}, (_, day) => ({snapshot_id: ++id,
          captured_at: new Date(Date.UTC(2026, 9, 19, 16) + day * 86400000).toISOString(), mentioned: day % 3 === 0}));
        return {engine_key, ...counts(samples), samples};
      })}));
    return {status: 'available', ...counts(questions.flatMap((q) => q.by_engine.flatMap((c) => c.samples))), questions};
  };
  const ordinary = group([83, 84, 86, 87, 88, 89], false), brand_probe = group([85], true);
  return {tenant_id: 15, project_id: 3, read_only: true, data: {demo_batch: {
    status: 'available', batch_token: demoToken, source_kind: 'simulated', sample_mode: 'mock_persona',
    period: {start_date: '2026-10-20', end_date: '2026-11-18', timezone: 'Asia/Shanghai'},
    saved_sample_count: ordinary.sample_count + brand_probe.sample_count,
    engine_keys: demoEngines.map(([key]) => key), ordinary, brand_probe,
    basis: {kind: 'saved_batch_records', selection: 'note_independent_token', ownership: 'current_project_binding',
      daily_grid_complete: true, simulated: true, sample_mode: 'mock_persona', patrol_linked: false, fingerprint: 'synthetic-only'},
  }}};
}
