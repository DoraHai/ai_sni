// Synthetic CONTRACT v1 payloads only. No application, DB, supplier or account access.
export const period = {
  timezone: 'Asia/Shanghai',
  week_end: '2026-10-19',
  start: '2026-10-12T00:00:00+08:00',
  end: '2026-10-19T00:00:00+08:00',
  closed: true,
};
const keys = [
  'geo.visibility.ai_mention_count_7d',
  'geo.visibility.ai_mention_rate_7d',
  'geo.visibility.ai_visibility_score',
];
export function weekly(ready = false) {
  return {
    week_end: period.week_end,
    period,
    sample_status: ready ? 'ready' : 'insufficient',
    message: ready ? null : '检测数据还不够',
    qualified_counts: {samples: ready ? 8 : 1, questions: ready ? 3 : 1, engines: ready ? 2 : 1},
    minimum_counts: {samples: 8, questions: 3, engines: 2},
    reason_codes: ready
      ? []
      : ['insufficient_samples', 'insufficient_questions', 'insufficient_engines'],
    own_domain_configured: ready,
    own_domains: ready ? ['example.com'] : [],
    qualified_mention_count: 0,
    qualified_own_domain_citation_count: 0,
    metrics: keys.map((key, i) => ({
      key,
      unit: ['count', 'percent', 'score'][i],
      value: ready ? 0 : null,
      status: ready ? 'available' : 'insufficient',
      reason_codes: ready ? [] : ['insufficient_samples'],
      trend_7d: null,
    })),
  };
}
export const observation = (mentioned = 1, total = 1) => ({
  mentioned,
  total,
  status: total ? 'observed' : 'no_observations',
  display_text: total ? `观测中提及 ${mentioned}/${total} 次` : '尚无可判读的真实观测',
  basis_code: 'saved_real_analyzed_answers',
  official_question_rate: null,
});
export const question = {
  id: 3,
  question: '合成问题：设备如何选型？',
  status: 'active',
  is_brand_probe: false,
  business: {id: 2, name: '合成业务'},
  unit: {id: 4, name: '合成单元'},
  observation: observation(),
  qualified_sample_count: 1,
  latest_answer_at: '2026-10-15T02:00:00Z',
  attention_reason_codes: [],
  detail_path: '',
};
export const answer = {
  id: 5,
  question_id: 3,
  question: {
    historical_text: '保存时的提问',
    current_text: question.question,
    historical_text_source: 'patrol_item',
  },
  engine: {
    key: 'fixture-engine',
    provider: '合成供应商',
    model: '合成模型',
    model_revision: null,
    metadata_source: 'patrol_item',
  },
  captured_at: '2026-10-15T02:00:00Z',
  captured_at_local: '2026-10-15T10:00:00+08:00',
  time_basis: 'stored_utc',
  source: {
    kind: 'real',
    sampling_method: 'unprimed_json_v2',
    analysis_status: 'completed',
    verified_server_record: true,
  },
  answer_excerpt: '已保存的回答节选',
  excerpt_truncated: true,
  mentions_brand: true,
  sample_eligibility: {eligible: true, reason_codes: []},
  week_membership: {within_window: true, included_in_cohort: true, reason_codes: []},
  metric_adoption: keys.map((key) => ({
    key,
    status: 'unavailable',
    reason_codes: ['insufficient_samples'],
  })),
  detail_path: '',
};
export const content = {
  id: 7,
  title: '合成内容任务',
  question_id: 3,
  question: question.question,
  stored_status: 'ready',
  pipeline_step: 'adapt',
  review: {
    status: 'approved',
    reviewed_at: '2026-10-14T00:00:00Z',
    covers_current_master: false,
    display_text: '',
  },
  latest_master: {id: 9, version_no: 2, title: '合成母稿', created_at: '2026-10-15T00:00:00Z'},
  variant_count: 1,
  published_record_count: 1,
  updated_at: '2026-10-15T00:00:00Z',
  detail_path: '',
};
export const article = {
  id: 9,
  task_id: 7,
  version_no: 2,
  kind: 'master',
  title: '合成母稿',
  body_markdown: '母稿全文\n<img src="https://outside.invalid/pixel" onerror="window.bad=true">',
  created_at: '2026-10-15T00:00:00Z',
};
export const variant = {
  id: 11,
  task_id: 7,
  article_id: 9,
  article_version_no: 2,
  channel: 'website',
  title: '合成渠道稿',
  stored_status: 'exported',
  created_at: '2026-10-15T00:00:00Z',
  updated_at: '2026-10-15T00:00:00Z',
  is_current_master: true,
  detail_path: '',
};
export const publication = {
  record_type: 'publication',
  id: 13,
  task_id: 7,
  variant_id: 11,
  article_id: 9,
  article_version_no: 2,
  is_current_master: true,
  title: '原生登记示例',
  channel: 'website',
  publish_mode: 'manual_export',
  stored_status: 'published',
  published_url: 'https://example.com/article?id=123',
  domain: 'example.com',
  url_state: 'available',
  published_at: '2026-10-16T00:00:00Z',
  updated_at: '2026-10-16T00:00:00Z',
  verification: {state: 'pending', checked_at: null, evidence_valid: false, reason_codes: []},
  task_path: '',
  variant_path: '',
  article_path: '',
};
export const receipt = {
  record_type: 'receipt',
  receipt_id: 'fixture-opaque-id',
  task_id: 7,
  variant_id: 11,
  article_id: 9,
  article_version_no: 2,
  is_current_master: true,
  title: '回执示例',
  channel: 'website',
  state: 'succeeded',
  updated_at: '2026-10-16T00:00:00Z',
  reason_code: null,
  display_text: '',
  task_path: '',
  variant_path: '',
};
export function page(items, more = false) {
  return {
    items,
    pagination: {
      limit: 20,
      returned_count: items.length,
      total_count: more ? items.length + 1 : items.length,
      has_more: more,
      next_cursor: more ? 'opaque-fixture-cursor' : null,
      truncated: more,
    },
  };
}
export function envelope(data, resource = 'overview') {
  return {
    schema_version: 'geo.client.v1',
    tenant_id: 1,
    project_id: 10,
    evaluated_at: '2026-10-20T04:00:00Z',
    read_only: true,
    scope: {
      ownership_basis: 'current_project_binding',
      binding_revision: 1,
      binding_state: 'bound',
      business_count: 1,
      question_count: 3,
    },
    basis: {
      kind: 'saved_records',
      aggregation_complete: true,
      last_data_at: '2026-10-15T02:00:00Z',
      period: /^(overview|visibility|questions|answers)/.test(resource) ? period : null,
      source_counts: /^(overview|visibility|questions|answers)/.test(resource)
        ? {real: 1, manual: 0, simulated: 0, unknown: 0}
        : null,
      unknown_time_count: /^(overview|visibility|questions|answers)/.test(resource) ? 0 : null,
      unknown_time_scope: /^(overview|visibility|questions|answers)/.test(resource)
        ? /^answers\//.test(resource)
          ? 'single_answer'
          : 'current_project_history'
        : null,
      exclusion_counts: [],
      note_codes: [],
    },
    data,
  };
}
export function geoFixture(resource, {more = false, ready = false} = {}) {
  if (resource === 'executions')
    return {
      project_id: 10,
      business_scope: {},
      service_plan: {
        revision: 0,
        enabled: true,
        status: 'active',
        interval_days: 7,
        advisor_user_id: 999,
      },
      advisor_name: 'DO_NOT_DISPLAY_ACCOUNT',
      blocker: {internal: 'DO_NOT_DISPLAY_INTERNAL'},
      effective_pause: false,
      prompts: [{id: 3, question: question.question}],
      items: [
        {
          id: 17,
          title: '合成服务任务',
          status: 'done',
          execution: {
            steps: [{title: '核对已存证据', done: true}],
            next_step: {internal: 'DO_NOT_DISPLAY_INTERNAL'},
            truncated: true,
          },
        },
      ],
      truncated: true,
      prompts_truncated: true,
      read_only: true,
    };
  let data;
  if (resource === 'overview')
    data = {
      project: {id: 10, name: '合成项目', brand_name: null, canonical_domain: 'example.com'},
      content: {
        time_basis: 'current_inventory',
        active_task_count: 1,
        pending_review_count: 1,
        approved_current_master_count: 0,
        task_count_with_master: 1,
        variant_count: 1,
        native_published_record_count: 1,
      },
      monitoring: {
        time_basis: 'closed_week',
        active_nonbrand_question_count: 3,
        attention_question_count: 1,
        no_real_observation_question_count: 1,
        some_nonmention_question_count: 0,
        observed_question_count: 2,
        saved_answer_count: 1,
        qualified_answer_count: 1,
        latest_answer_at: '2026-10-15T02:00:00Z',
      },
      weekly: weekly(ready),
      links: {},
    };
  else if (resource === 'visibility')
    data = {
      current: weekly(ready),
      previous: weekly(),
      comparison: {comparable: false, checks: {}, reason_codes: ['previous_week_insufficient']},
      engines: [
        {
          engine_key: 'fixture-engine',
          observation: observation(),
          qualified_sample_count: 1,
          qualified_question_count: 1,
        },
      ],
      definitions: {
        mention_count: '提及回答条数',
        mention_rate: '提及回答占合格样本的比例',
        visibility_score: '提及与自有域引用分数',
        qualification: '8 条回答、3 个问题、2 个引擎',
        ownership_basis: '当前项目归属',
      },
    };
  else if (resource === 'questions') data = page([structuredClone(question)], more);
  else if (resource === 'questions/3')
    data = {
      question,
      by_engine: [
        {engine_key: 'fixture-engine', observation: observation(), qualified_sample_count: 1},
      ],
      evidence: {
        answer_count: 1,
        excluded_answer_count: 0,
        unknown_time_count: 0,
        unknown_time_scope: 'current_project_history',
      },
      answers_path: '',
      content_path: '',
    };
  else if (resource === 'answers') data = page([answer], more);
  else if (resource === 'answers/5')
    data = {
      item: answer,
      raw_text:
        '合成回答完整原文\n<script>window.bad=true</script>\n![图片](https://outside.invalid/pixel)',
      citations: [
        {url: 'https://example.com/evidence?id=123', domain: 'example.com', url_state: 'available', is_own_domain: true},
        {url: null, domain: 'docs.example.com', url_state: 'suppressed', is_own_domain: true},
      ],
      comparison_metadata: {
        complete: true,
        reason_codes: [],
        model_identity_basis: 'recorded_request_model_alias',
        exact_model_revision_known: false,
      },
    };
  else if (resource === 'content') data = page([content], more);
  else if (resource === 'content/7')
    data = {
      task: content,
      master: article,
      variants_path: '',
      deliveries_path: '',
      receipt_summary: {succeeded: 1, failed: 0, unknown: 0, sending: 0, other: 0},
    };
  else if (resource === 'content/7/variants') data = page([variant], more);
  else if (resource === 'content/7/variants/11')
    data = {variant, body_markdown: '合成渠道稿全文', article_path: '', deliveries_path: ''};
  else if (resource === 'content/7/articles/9') data = {article, is_current_master: true};
  else if (resource === 'deliveries')
    data = {
      ...page([publication, receipt], more),
      counts: {
        publication_records: 1,
        receipt_records: 1,
        published_records: 1,
        stored_verified_publications: 0,
      },
    };
  else throw Error('Unknown synthetic resource: ' + resource);
  const filters = {
    questions: {status: 'all', is_brand_probe: null, attention: 'all', q: null},
    answers: {question_id: null, engine_key: null, source_kind: null, eligibility: 'all'},
    content: {question_id: null, review_status: null, include_archived: false, q: null},
    deliveries: {task_id: null, record_type: 'all'},
  };
  if (filters[resource]) data.filters = filters[resource];
  return envelope(data, resource);
}
