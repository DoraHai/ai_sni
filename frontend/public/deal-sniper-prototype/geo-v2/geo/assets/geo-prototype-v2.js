const visibilityPages = new Set([
  'keywordAnalysis',
  'questionAnalysis',
  'citationAnalysis',
  'competitors',
  'trends',
  'diagnosis'
]);

const commonAnswer = {
  now: ['我现在怎么样？', '品牌在核心 AI 提问中有基础曝光，但推荐顺位和引用稳定性还不够。'],
  why: ['为什么？', 'AI 更偏好能被验证的品牌事实、清晰结构和第三方可信来源。'],
  next: ['下一步怎么办？', '优先补齐高价值提问对应的知识库事实，再生成可引用内容并追踪效果。']
};

const pages = {
  overview: {
    name: 'GEO概览',
    tag: 'AI BRAND OVERVIEW',
    title: '从业务、关键词和 AI 提问出发，看清品牌在 AI 世界里的整体表现。',
    desc: '统一查看品牌提及、推荐位置、AI 引用和竞品变化，帮助市场团队判断哪些业务正在被 AI 看见，哪些问题需要优先优化。',
    steps: [
      ['查看表现', '品牌是否被 AI 提及和推荐'],
      ['定位变化', '识别增长、下滑和竞品影响'],
      ['发现机会', '找到值得优先优化的提问'],
      ['推动行动', '进入内容、知识库和追踪任务']
    ],
    heroTags: ['整体表现', '机会发现', '竞品变化', '行动建议'],
    heroActions: ['查看本周建议', '导出经营简报'],
    answer: {
      now: ['经营判断', 'AI品牌认知正在改善，但增长集中在 CRM 业务，尚未形成稳定的全业务推荐能力。'],
      why: ['核心原因', 'AI 更愿意引用结构清晰、事实可验证的内容；新增 GEO 文章拉动了 DeepSeek 与 ChatGPT 的表现。'],
      next: ['管理动作', '本周应优先批准内容供给、可信信源和 MES 防守三项动作，避免资源分散。']
    },
    design: 'GEO 概览遵循 Dashboard Template：先用 Hero 建立业务判断，再用三张 Current Situation 解释现状、原因和行动；表格只作为后半段证据，页面最后以本周优化计划收束。',
    body: overviewBody
  },
  business: {
    name: '业务管理',
    tag: '定义优化对象',
    title: '先把业务边界说清楚，AI 才知道应该在哪些场景里推荐你。',
    desc: '按品牌下的业务线管理产品、解决方案、目标客户和核心卖点，确保后续关键词、AI 提问和内容都围绕明确业务展开。',
    steps: ['新增业务', '补充卖点', '绑定关键词', '查看优化进度'],
    answer: {
      now: ['我现在怎么样？', 'CRM 业务覆盖较完整，智能客服业务缺少案例和解决方案说明。'],
      why: ['为什么？', 'AI 回答更容易引用有清晰对象、适用场景和客户证据的业务资料。'],
      next: ['下一步怎么办？', '先补智能客服的行业案例，再把案例关联到高价值关键词。']
    },
    design: '业务管理是整个数据模型的起点，用业务语言组织资产，避免用户从技术任务或采集配置开始。',
    body: businessBody
  },
  keywords: {
    name: '关键词管理',
    tag: '连接用户需求',
    title: '关键词不是拿来堆排名的，而是用来发现用户会向 AI 问什么。',
    desc: '围绕业务沉淀关键词，并识别这些关键词背后的真实购买场景、常见问题和内容机会。',
    steps: ['选择业务', '维护关键词', '生成AI提问', '追踪推荐率'],
    answer: {
      now: ['我现在怎么样？', '核心词覆盖稳定，长尾决策词不足。'],
      why: ['为什么？', 'AI 回答常从具体问题进入，泛关键词很难直接触发品牌推荐。'],
      next: ['下一步怎么办？', '把“CRM 软件”拆成选型、价格、行业方案和替代方案等提问簇。']
    },
    design: '关键词页弱化传统 SEO 排名，强调关键词如何变成 AI 提问和品牌推荐机会。',
    body: keywordBody
  },
  questions: {
    name: 'AI提问管理',
    tag: '管理 AI 入口',
    title: '用户不会只搜索关键词，他们会直接问 AI：哪个品牌更适合我？',
    desc: '把关键词转化为真实 AI 提问，按业务价值、购买阶段和品牌机会管理，形成可持续优化清单。',
    steps: ['生成提问', '评估价值', '查看AI回答', '加入优化'],
    answer: {
      now: ['我现在怎么样？', '高价值提问已有 126 条，其中 38 条品牌未被推荐。'],
      why: ['为什么？', '多数未推荐提问缺少对应的直答内容和可验证案例。'],
      next: ['下一步怎么办？', '优先优化成交意图高且竞品已出现的提问。']
    },
    design: 'AI 提问是 GEO 的核心工作对象，页面用业务价值排序，而不是让用户面对技术 Prompt 列表。',
    body: questionBody
  },
  recommend: {
    name: 'AI推荐',
    tag: '自动发现机会',
    title: '输入一个关键词，系统帮你找到值得优化的提问、产品和解决方案。',
    desc: '结合官网、公众号、知识库、产品、案例和解决方案，自动推荐可加入优化的关键词与 AI 提问。',
    steps: ['输入关键词', '分析品牌资产', '生成建议清单', '一键加入优化'],
    answer: {
      now: ['我现在怎么样？', 'CRM 相关资产充足，但推荐问题集中在价格和对比场景。'],
      why: ['为什么？', 'AI 更容易在选型和比较问题中推荐品牌。'],
      next: ['下一步怎么办？', '把“CRM 软件哪个好”和“免费 CRM 怎么选”加入本周优化。']
    },
    design: 'AI 推荐放在优化管理里，像 GEO 顾问一样主动给建议，减少用户从零规划的负担。',
    body: recommendBody
  },
  visibility: visibilityPage('AI品牌画像', 'AI 品牌画像不是看一次 AI 回答，而是看 AI 长期如何理解你的品牌。', '基于近 30 天多个 AI 平台公开回答，综合分析品牌整体认知、推荐倾向、引用偏好、优势、短板以及优化方向，帮助团队了解品牌在 AI 世界中的长期形象。', [['整体认知', '了解 AI 对品牌的总体评价与推荐倾向'], ['品牌标签', '发现 AI 提及的关键词与品牌定位'], ['优势短板', '识别已建立的优势与需补强领域'], ['优化方向', '生成可落地的优化建议']]),
  keywordAnalysis: visibilityPage('关键词分析', '看清每个关键词背后的品牌机会', '按关键词查看品牌提及、竞品占位和 AI 引用情况，判断哪些词值得优先投入内容。', ['选择业务', '切换关键词', '分析AI回答', '生成优化建议']),
  questionAnalysis: visibilityPage('AI提问分析', '逐条分析 AI 为什么推荐或不推荐你', '围绕具体 AI 提问拆解回答内容、品牌出现位置、竞品出现原因和下一步补强动作。', ['选择AI提问', '查看AI回答', '分析推荐原因', '加入内容任务']),
  citationAnalysis: visibilityPage('AI引用分析', '找到 AI 愿意引用的内容来源', '分析 AI 回答引用了哪些官网、文章、FAQ、案例或第三方页面，帮助品牌建设更可信的内容入口。', ['查看引用来源', '判断可信度', '定位缺失内容', '补充可引用材料']),
  competitors: visibilityPage('竞品分析', '看清竞品为什么更容易被 AI 推荐', '比较品牌与竞品在关键词、AI 提问、回答理由和引用来源上的差距，形成可执行的反超策略。', ['选择竞品', '对比提及率', '分析引用差距', '生成反超动作']),
  trends: visibilityPage('趋势分析', '持续追踪 AI 对品牌认知的变化', '把品牌提及、推荐顺位、AI 引用和竞品变化放到时间线上，识别优化动作是否真的产生影响。', ['查看趋势', '标记动作', '解释波动', '复盘效果']),
  diagnosis: {
    name: 'GEO优化诊断',
    tag: '体检报告',
    title: '像体检报告一样告诉你：品牌为什么不容易被 AI 引用，以及应该先改哪里。',
    desc: '从品牌基础、内容质量、网站可解析能力、AI引用能力和竞品差距五个维度给出评分、原因和优化建议。',
    steps: ['检查品牌基础', '评估内容质量', '检测可解析能力', '生成优化处方'],
    answer: {
      now: ['我现在怎么样？', '整体评分 72，网站可解析能力和 AI 引用能力拖慢增长。'],
      why: ['为什么？', 'FAQPage、Product、Article 等结构化信息不足，AI 难以稳定理解页面内容。'],
      next: ['下一步怎么办？', '先补 Organization、Product、FAQPage 和 sitemap，再更新高价值内容。']
    },
    design: '诊断页归入 AI 可见性，不独立成一级菜单；采用体检报告方式，告诉市场团队每个问题为什么影响 AI 引用以及如何优化。',
    body: diagnosisBody
  },
  knowledge: {
    name: '知识库',
    tag: '沉淀可信事实',
    title: 'AI 引用你的前提，是你先把品牌事实、案例和答案整理成可信素材。',
    desc: '统一维护品牌、产品、解决方案、FAQ、案例、官网内容、公众号内容和上传资料，让 GEO 文章生成有事实依据。',
    steps: ['维护品牌事实', '补充产品资料', '沉淀案例FAQ', '注入文章生成'],
    answer: {
      now: ['我现在怎么样？', '品牌和产品资料较完整，案例与 FAQ 仍缺少行业标签。'],
      why: ['为什么？', 'AI 更容易引用有明确场景、结果数据和更新时间的事实。'],
      next: ['下一步怎么办？', '优先补 6 个行业案例和 20 条购买决策 FAQ。']
    },
    design: '知识库是内容中心的事实底座，页面按市场团队熟悉的素材类型组织，而不是按文件或接口组织。',
    body: knowledgeBody
  },
  articles: {
    name: 'GEO文章',
    tag: '优化内容',
    title: 'AI 不会因为文章多而引用你，而是因为内容可信、结构清晰、事实可验证。',
    desc: '从高价值 AI 提问出发，结合品牌知识、案例和可信来源生成更容易被 AI 理解和引用的内容，并持续追踪引用效果。',
    steps: ['选择AI提问', '注入品牌事实', 'AI生成并优化', '发布并追踪引用'],
    answer: {
      now: ['我现在怎么样？', '本周有 7 篇文章建议生成，其中 3 篇关联高价值未推荐提问。'],
      why: ['为什么？', '这些提问已有搜索意图和竞品露出，但品牌缺少可引用的直答内容。'],
      next: ['下一步怎么办？', '先生成“CRM软件哪个好”文章，并绑定业务、关键词和 AI 提问。']
    },
    design: 'GEO 文章页顶部放 AI 推荐写作，让用户直接从 AI 提问进入内容生产，并追踪发布后的 AI 引用次数。',
    body: articlesBody
  },
  brandSettings: settingPage('品牌设置', '让 AI 正确认识你的品牌是谁、做什么、适合谁。', '维护品牌名称、官网、行业、核心能力、目标客户和品牌边界，保证后续 AI 分析和内容生成不跑偏。', ['完善品牌资料', '校验品牌事实', '设置禁用表述', '同步知识库']),
  models: settingPage('AI模型', '选择需要持续观察的 AI 模型，不需要理解技术细节。', '配置 ChatGPT、DeepSeek、Gemini、Claude、豆包、Kimi、通义等模型的观察范围和展示名称。', ['选择模型', '设置区域', '确认频率', '查看覆盖']),
  permissions: settingPage('团队权限', '让市场、品牌和内容团队按职责协同优化 AI 品牌表现。', '按角色管理品牌负责人、内容运营、审核人和管理者权限，确保优化动作可协作、可追踪。', ['添加成员', '分配角色', '设置审批', '追踪协作'])
};

function visibilityPage(name, title, desc, steps) {
  return {
    name,
    tag: 'AI可见性',
    title,
    desc,
    steps,
    answer: commonAnswer,
    design: 'AI 可见性页面统一使用“业务 → 关键词 → AI 提问”对象切换器，让用户在同一分析对象下查看不同维度，避免每页重新理解筛选逻辑。',
    body: visibilityBody
  };
}

function settingPage(name, title, desc, steps) {
  return {
    name,
    tag: '设置',
    title,
    desc,
    steps,
    answer: {
      now: ['我现在怎么样？', '基础配置已可支撑日常优化，但仍有部分协作和品牌边界待完善。'],
      why: ['为什么？', '清晰设置能减少内容生成偏差，也让团队知道谁负责下一步动作。'],
      next: ['下一步怎么办？', '完善关键配置后，再进入可见性概览查看品牌表现。']
    },
    design: '设置页保持业务化表达，不强调接口和采集任务，只告诉市场团队这些配置如何影响品牌优化效果。',
    body: settingsBody
  };
}

function renderPage(key) {
  const page = pages[key] || pages.overview;
  const isBrandPortrait = key === 'visibility';
  document.body.dataset.page = key;
  document.querySelector('.product-kicker').textContent = isBrandPortrait ? 'AI 可见性 / AI 品牌画像' : 'AI 品牌优化平台';
  document.querySelector('.top-actions').innerHTML = isBrandPortrait
    ? `
      <span class="top-meta">更新时间：2026-08-22</span>
      <span class="top-meta">基于最近 30 天 AI 回答自动生成 ⓘ</span>
      <button class="ghost-icon" aria-label="分享">⌯</button>
      <button>↓ 导出品牌画像</button>
      <button class="primary">✦ 查看优化建议</button>`
    : `
      <button class="ghost-icon" aria-label="搜索">⌕</button>
      <button class="ghost-icon" aria-label="通知">◦</button>
      <button>↓ 导出经营简报</button>
      <button class="primary">↓ 查看本周建议</button>
      <button class="user-pill" aria-label="当前用户">DZ</button>`;
  document.getElementById('topPageName').textContent = page.name;
  document.getElementById('heroTag').textContent = page.tag;
  document.getElementById('heroTitle').textContent = page.title;
  document.getElementById('heroDesc').textContent = page.desc;
  document.getElementById('heroTags').innerHTML = (page.heroTags || [page.tag]).map(tag => `<span>${tag}</span>`).join('');
  const heroActionLabels = isBrandPortrait ? ['查看优化建议', '导出品牌画像'] : (page.heroActions || ['查看建议', '导出简报']);
  document.getElementById('heroActions').innerHTML = heroActionLabels.map((label, index) => `<button class="${index === 0 ? 'primary' : ''}">${label}</button>`).join('');
  document.getElementById('heroSteps').innerHTML = page.steps.map((step, index) => (
    `<div class="step-card"><b>${String(index + 1).padStart(2, '0')}</b><span>${Array.isArray(step) ? step[0] : step}</span>${Array.isArray(step) ? `<small>${step[1]}</small>` : ''}</div>`
  )).join('');
  const answerRow = document.getElementById('answerRow');
  answerRow.hidden = isBrandPortrait;
  answerRow.innerHTML = isBrandPortrait ? '' : key === 'overview'
    ? `
      <article class="answer-card now"><i>▮</i><div><span>Current Situation</span><small>经营状态</small><strong>品牌认知在改善，但增长还不够均衡。</strong><p>CRM 拉动明显，MES 与海外业务仍需要管理层关注。</p><button>查看经营判断 →</button></div></article>
      <article class="answer-card why"><i>◌</i><div><span>Why It Matters</span><small>原因判断</small><strong>AI 正在奖励可信内容，而不是内容数量。</strong><p>新增 GEO 内容被引用，说明结构化事实和信源开始发挥作用。</p><button>查看证据摘要 →</button></div></article>
      <article class="answer-card next"><i>◎</i><div><span>Management Focus</span><small>本周重点</small><strong>资源应集中到 3 个可见的品牌经营动作。</strong><p>扩内容、补信源、防守 MES，避免团队继续分散做监测。</p><button>查看建议 →</button></div></article>`
    : ['now', 'why', 'next'].map(type => (
      `<article class="answer-card ${type}"><i>${type === 'now' ? '▮' : type === 'why' ? '◌' : '◎'}</i><div><span>${page.answer[type][0]}</span><strong>${page.answer[type][1]}</strong><p>${type === 'now' ? '查看详细表现 →' : type === 'why' ? '查看关键原因 →' : '查看本周建议 →'}</p></div></article>`
    )).join('');
  document.getElementById('pageBody').className = `page-body ${key === 'diagnosis' ? 'single' : ''}`;
  document.getElementById('pageBody').innerHTML = page.body(key);
  document.getElementById('designNote').innerHTML = key === 'overview' ? '' : `<b>为什么这样设计：</b>${page.design}`;
  document.getElementById('designNote').hidden = key === 'overview';
  document.getElementById('objectSwitcher').classList.toggle('visible', visibilityPages.has(key));
  document.getElementById('brandContext').classList.toggle('visible', key === 'overview');
  document.getElementById('pageBody').classList.toggle('overview-page', key === 'overview');
  document.querySelectorAll('.nav-leaf').forEach(button => button.classList.toggle('active', button.dataset.page === key));
  const activeSection = document.querySelector(`.nav-leaf[data-page="${key}"]`)?.closest('.nav-section');
  if (activeSection) activeSection.classList.add('open');
}

function overviewBody() {
  return `
    <section class="panel brief-recommendation">
      <div class="brief-section-head">
        <span class="panel-kicker">Recommendation</span>
        <h2>本周建议批准 3 个动作：扩充 CRM 可信内容、补齐第三方信源、立即防守 MES 业务。</h2>
        <p>这些动作预计比继续增加监测报表更能提升 AI 推荐率和品牌引用稳定性。</p>
      </div>
      <div class="brief-action-grid">
        ${briefAction('01', '批准 CRM 选型内容包', '围绕“CRM软件哪个好”生成 1 篇决策长文、3 条 FAQ、2 个案例引用块。', '预期拉动核心提问推荐率 +5%')}
        ${briefAction('02', '补齐第三方可信来源', '优先补行业媒体、客户案例、公开报告三类可被 AI 验证的材料。', '降低 AI 推荐理由不稳定风险')}
        ${briefAction('03', '启动 MES 防守任务', '针对竞品 A 已领先的 6 个 MES 提问建立对比内容和事实澄清页。', '防止业务线被竞品持续占位')}
      </div>
    </section>

    <section class="panel brief-situation">
      <div class="brief-section-head">
        <span class="panel-kicker">Current Situation</span>
        <h2>经营判断</h2>
      </div>
      <div class="brief-judgement-list">
        ${briefJudgement('增长有效，但不均衡', 'AI 品牌提及率提升到 62%，主要由 CRM 业务贡献；ERP 基本平稳，MES 下滑。')}
        ${briefJudgement('内容资产正在产生杠杆', '8月12日后新增 GEO 内容被 DeepSeek 与 ChatGPT 引用，说明“可信内容供给”是主要增长变量。')}
        ${briefJudgement('风险不是流量，而是认知被替代', 'MES 相关 AI 回答开始更多引用竞品内容，若不处理，会影响后续销售线索的品牌优先级。')}
      </div>
    </section>

    <section class="panel brief-evidence">
      <div class="brief-section-head">
        <span class="panel-kicker">Evidence</span>
        <h2>证据摘要</h2>
        <p>图表只作为经营判断的证据，不作为页面主角。</p>
      </div>
      <div class="brief-evidence-grid">
        <div class="brief-metrics">
          ${briefMetric('品牌提及率', '62%', '+8.4%')}
          ${briefMetric('AI推荐率', '41%', '+5.2%')}
          ${briefMetric('AI引用次数', '1,248', '+12.7%')}
        </div>
        <div class="brief-mini-chart">
          <svg viewBox="0 0 420 120" role="img" aria-label="近30天 AI 品牌提及率趋势">
            <path d="M20 96 H400" class="axis"/>
            <path d="M20 68 H400" class="grid"/>
            <path d="M20 40 H400" class="grid"/>
            <polyline points="20,88 70,82 120,78 170,72 220,56 270,47 330,34 400,26" class="brand-line"/>
            <polyline points="20,92 70,88 120,84 170,81 220,78 270,74 330,71 400,68" class="competitor-line"/>
          </svg>
          <p>8月12日后提及率明显上升，与新发布内容时间吻合。</p>
        </div>
        <div class="brief-model-proof">
          ${modelRank('1', 'DeepSeek', '71')}
          ${modelRank('2', 'ChatGPT', '63')}
          ${modelRank('3', 'Claude', '58')}
          ${modelRank('6', 'Gemini', '39')}
        </div>
      </div>
    </section>

    <section class="panel brief-risks">
      <div class="brief-section-head">
        <span class="panel-kicker">Risks</span>
        <h2>需要 CEO 知道的风险</h2>
      </div>
      <div class="brief-risk-grid">
        ${riskMini('MES系统', '过去7天提及率下降 14%', '竞品 A 上升 11%，建议本周立刻补对比内容')}
        ${riskMini('海外业务', 'Gemini 表现明显落后', '第三方英文信源不足，影响国际客户触达')}
        ${riskMini('官网可信度', '官网引用少于第三方媒体', '产品页结构和更新时间需要修复')}
      </div>
    </section>

    <section class="panel brief-decision">
      <div>
        <span class="panel-kicker">CEO Decision</span>
        <h2>本周需要拍板</h2>
        <p>批准市场团队把资源集中到三个可见的 AI 品牌经营动作。</p>
      </div>
      <div class="brief-decision-actions">
        <button class="action-button primary">批准本周优化计划</button>
        <button class="action-button">导出经营简报</button>
      </div>
    </section>`;
}

function businessBody() {
  return standardBody('业务线健康度', [
    metric('CRM', '82', '关键词与 FAQ 覆盖完整，但缺少中大型客户案例。', '补充行业案例'),
    metric('智能客服', '64', 'AI 回答常引用竞品，因为我方解决方案页不够清晰。', '完善解决方案'),
    metric('数据分析平台', '71', '产品定义清楚，但对比内容不足。', '生成选型文章')
  ], '业务与关键词关系', [
    ['CRM', 'CRM软件、客户管理系统', '126 条 AI 提问', '34 篇内容'],
    ['智能客服', 'AI客服、客服机器人', '88 条 AI 提问', '19 篇内容'],
    ['数据分析平台', 'BI工具、数据看板', '73 条 AI 提问', '14 篇内容']
  ]);
}

function keywordBody() {
  return standardBody('关键词机会池', [
    metric('CRM软件', '高', '品牌已被提及，但推荐理由不稳定。', '补强对比内容'),
    metric('免费CRM', '中', '价格类提问多，但知识库缺少版本说明。', '补价格FAQ'),
    metric('销售自动化', '高', '竞品占位明显，品牌缺少场景文章。', '加入优化')
  ], '关键词到 AI 提问', [
    ['CRM软件', 'CRM软件哪个好？', '推荐率 34%', '生成文章'],
    ['免费CRM', '免费CRM适合小团队吗？', '推荐率 18%', '补FAQ'],
    ['销售自动化', '销售自动化工具怎么选？', '推荐率 22%', '补案例']
  ]);
}

function questionBody() {
  return standardBody('AI提问优先级', [
    metric('CRM软件哪个好？', '★★★★★', '购买意图强，竞品已稳定出现。', '立即优化'),
    metric('中小企业怎么选CRM？', '★★★★', '品牌被提及但没有进入前三推荐。', '补选型框架'),
    metric('免费CRM适合销售团队吗？', '★★★', 'AI 回答引用旧价格信息。', '更新事实')
  ], 'AI回答分析', [
    ['CRM软件哪个好？', '品牌第 3 位', '竞品 A 第 1 位', '缺少案例证据'],
    ['中小企业怎么选CRM？', '品牌被提及', '推荐理由弱', '补行业方案'],
    ['免费CRM适合销售团队吗？', '未推荐', '引用旧资料', '更新价格FAQ']
  ]);
}

function recommendBody() {
  return `
    <section class="panel">
      <div class="panel-head"><div><span class="panel-kicker">AI推荐输入</span><h2>关键词：CRM软件</h2><p>系统基于官网、公众号、知识库、产品、案例和解决方案给出优化建议。</p></div><button>重新分析</button></div>
      <div class="recommend-list">
        ${recommend('建议关键词', '客户管理系统、销售自动化、免费CRM', '这些词更接近购买决策，适合加入优化。')}
        ${recommend('建议AI提问', 'CRM软件哪个好？中小企业怎么选CRM？', 'AI 回答里已有竞品露出，适合优先抢占。')}
        ${recommend('建议产品/方案', '销售线索管理、客户跟进自动化', '当前官网资产完整，可直接生成内容。')}
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><div><span class="panel-kicker">一键加入优化</span><h2>推荐工作流</h2><p>把建议直接转成业务、关键词、AI提问和内容任务。</p></div></div>
      <table class="flow-table">
        <thead><tr><th>建议</th><th>关联对象</th><th>下一步</th></tr></thead>
        <tbody>
          <tr><td>CRM软件哪个好？</td><td>CRM / CRM软件</td><td><span class="tag">加入AI提问</span></td></tr>
          <tr><td>中小企业CRM选型</td><td>CRM / 客户管理系统</td><td><span class="tag">生成GEO文章</span></td></tr>
          <tr><td>销售自动化案例</td><td>CRM / 销售自动化</td><td><span class="tag warn">补知识库</span></td></tr>
        </tbody>
      </table>
    </section>`;
}

function visibilityBody(key) {
  if (key === 'visibility') return brandPortraitBody();

  const titleMap = {
    visibility: '可见性表现',
    keywordAnalysis: '关键词表现拆解',
    questionAnalysis: 'AI回答拆解',
    citationAnalysis: 'AI引用来源',
    competitors: '竞品差距',
    trends: '趋势变化'
  };
  return `
    <section class="panel main-analysis">
      <div class="panel-head"><div><span class="panel-kicker">核心分析</span><h2>${titleMap[key] || 'AI可见性分析'}</h2><p>当前对象：CRM → CRM软件 → CRM软件哪个好？</p></div><button>生成优化建议</button></div>
      <div class="model-strip">
        <span>AI 模型</span><b>ChatGPT</b><b>DeepSeek</b><b>Claude</b><b>Gemini</b><b>豆包</b><b>Kimi</b><b>通义千问</b>
      </div>
      <div class="overview-grid">
        ${insightMetric('品牌出现率', '68%', '+12%', 'ChatGPT 和 DeepSeek 表现最佳', '复用高质量 FAQ')}
        ${insightMetric('推荐率', '43%', '+8%', '推荐理由集中在易用性和行业方案', '补充案例证据')}
        ${insightMetric('平均排名位置', '2.6', '+0.6', 'Claude 引用了 4 个官网页面', '强化官网结构')}
        ${insightMetric('AI引用次数', '126', '+28', 'Kimi 与通义引用仍偏少', '补第三方来源')}
      </div>
      <div class="analysis-split">
        ${trendBlock('各模型品牌出现率对比')}
        <div class="finding-card">
          <span class="panel-kicker">关键发现</span>
          <ul>
            <li>ChatGPT 和 DeepSeek 表现最佳，推荐率分别为 55% 和 48%。</li>
            <li>Claude 引用了 4 个官网页面，可信度最高。</li>
            <li>Kimi 和通义中竞品出现频率较高，需要补强对比内容。</li>
          </ul>
          <button class="action-button primary">查看详细分析</button>
        </div>
      </div>
    </section>
    <section class="panel advisor-panel">
      <div class="panel-head"><div><span class="panel-kicker">AI 建议 TOP 3</span><h2>本周优先动作</h2><p>每条建议都能直接进入优化流程。</p></div><button>查看全部建议</button></div>
      <div class="recommend-list">
        ${recommend('加强产品案例内容', '在“CRM软件哪个好”中，案例内容缺失导致可信度不足。', '优先生成案例型 GEO 文章。')}
        ${recommend('补充 FAQ 结构化数据', '未检测到 FAQPage，影响 AI 引用。', '将核心问答同步到知识库和官网。')}
        ${recommend('增加第三方评测引用', '缺少权威媒体或第三方评测引用。', '补充行业媒体观点和客户案例。')}
      </div>
    </section>
    <section class="panel detail-panel">
      <div class="panel-head"><div><span class="panel-kicker">数据明细</span><h2>各模型回答对比</h2><p>明细放在最后，用来解释核心判断。</p></div></div>
      <table class="flow-table">
        <thead><tr><th>AI模型</th><th>品牌位置</th><th>推荐率</th><th>引用数</th><th>原因</th></tr></thead>
        <tbody>
          <tr><td>ChatGPT</td><td>1/5</td><td>55%</td><td>3</td><td>引用官网、案例和 FAQ，回答结构完整。</td></tr>
          <tr><td>DeepSeek</td><td>2/5</td><td>48%</td><td>2</td><td>推荐理由清晰，但缺少对比证据。</td></tr>
          <tr><td>Claude</td><td>2/5</td><td>46%</td><td>4</td><td>官网内容可信，但第三方来源不足。</td></tr>
        </tbody>
      </table>
    </section>`;
}

function brandPortraitBody() {
  return `
    <section class="brand-portrait-grid">
      <article class="portrait-card portrait-score">
        <div class="portrait-head"><h2>AI 整体评价</h2><span>较前 30 天提升 8 分</span></div>
        <div class="score-ring"><strong>78</strong><span>/100</span><em>良好</em></div>
        <p>AI 已形成“专业、CRM、企业服务”的基础认知，但海外市场和制造业案例仍偏弱。</p>
      </article>

      <article class="portrait-card portrait-models">
        <div class="portrait-head"><h2>AI 平台认知</h2><span>推荐倾向</span></div>
        ${portraitModel('DeepSeek', '★★★★★', '90', '+12')}
        ${portraitModel('ChatGPT', '★★★★☆', '81', '+10')}
        ${portraitModel('Claude', '★★★★☆', '75', '+15')}
        ${portraitModel('Gemini', '★★★☆☆', '51', '-3')}
        <button class="portrait-link">查看各平台详细表现 →</button>
      </article>

      <article class="portrait-card portrait-cloud">
        <div class="portrait-head"><h2>AI 品牌认知标签</h2><span>高频词</span></div>
        <div class="tag-cloud">
          <b>CRM</b><strong>专业</strong><em>企业</em><span>客户管理</span><span>SaaS</span><span>解决方案</span><span>销售自动化</span><span>功能全面</span><span>可靠稳定</span><span>数据安全</span>
        </div>
        <button class="portrait-link">查看全部标签 →</button>
      </article>

      <article class="portrait-card portrait-business">
        <div class="portrait-head"><h2>AI 最常提到的业务</h2><span>跨业务线</span></div>
        ${portraitBar('CRM', '68')}
        ${portraitBar('MES', '42')}
        ${portraitBar('ERP', '38')}
        ${portraitBar('WMS', '18')}
        ${portraitBar('SCM', '12')}
        <button class="portrait-link">查看全部业务 →</button>
      </article>

      <article class="portrait-card portrait-source">
        <div class="portrait-head"><h2>AI 引用偏好</h2><span>内容来源</span></div>
        <div class="source-donut"><strong>2,458</strong><span>总引用来源</span></div>
        <div class="source-list">
          ${portraitSource('产品介绍 / 官网页面', '38%', '#6356f1')}
          ${portraitSource('客户案例 / 成功案例', '26%', '#8b7cf6')}
          ${portraitSource('FAQ / 帮助中心', '18%', '#ff9f43')}
          ${portraitSource('行业媒体 / 第三方媒体', '11%', '#34c38f')}
          ${portraitSource('其他', '7%', '#7aa2ff')}
        </div>
      </article>

      <article class="portrait-card portrait-strength">
        <div class="portrait-head"><h2>AI 认为的品牌优势</h2><span>正向认知</span></div>
        ${portraitTrait('功能全面，覆盖 CRM 全流程', '76%')}
        ${portraitTrait('行业经验丰富，方案专业', '64%')}
        ${portraitTrait('实施服务专业，交付能力强', '58%')}
        ${portraitTrait('系统稳定可靠，安全性高', '55%')}
        ${portraitTrait('性价比高，投资回报明显', '48%')}
      </article>

      <article class="portrait-card portrait-weakness">
        <div class="portrait-head danger"><h2>AI 认为的品牌短板</h2><span>待补强</span></div>
        ${portraitTrait('制造业场景案例不足', '62%', true)}
        ${portraitTrait('海外市场认知度低', '57%', true)}
        ${portraitTrait('产品易用性认知不足', '45%', true)}
        ${portraitTrait('品牌知名度有待提升', '41%', true)}
        ${portraitTrait('内容更新频率偏低', '38%', true)}
      </article>

      <section class="portrait-card portrait-suggestions">
        <div class="portrait-head"><h2>AI 优化建议方向</h2><span>可加入任务</span></div>
        <div class="portrait-suggestion-grid">
          ${portraitSuggestion('加强制造业内容建设', '补充制造业行业案例、解决方案和场景化内容，提升 AI 认知。', '高优先级')}
          ${portraitSuggestion('提升海外市场内容覆盖', '建设多语言内容，增加海外客户案例和本地化解决方案。', '高优先级')}
          ${portraitSuggestion('完善 FAQ 和帮助中心', '补齐常见问题和使用指南，提升 AI 引用和推荐概率。', '中优先级')}
          ${portraitSuggestion('强化品牌内容传播', '增加品牌提及和权威媒体报道，提升品牌知名度。', '中优先级')}
          ${portraitSuggestion('优化官网内容结构', '优化信息架构和页面内容，提升 AI 抓取和理解效果。', '低优先级')}
        </div>
      </section>
    </section>`;
}

function diagnosisBody() {
  const rows = [
    ['品牌基础', '82', '品牌名称、官网和产品定义清晰。', '补充品牌边界和禁用表述，避免 AI 误解。', 'good'],
    ['内容质量', '74', '有 FAQ 和案例，但部分内容缺少结论直答。', '把关键答案放到首段，并补充场景化小标题。', 'warn'],
    ['网站可解析能力', '58', 'FAQPage、Product、Article、Breadcrumb 不完整，AI 难以稳定理解页面。', '补 JSON-LD、Schema.org、Organization、Product、FAQPage、Article、Breadcrumb、robots.txt、sitemap.xml、Canonical，多语言站补 hreflang。', 'bad'],
    ['AI引用能力', '63', '官网可引用，但第三方来源不足。', '把案例、白皮书、帮助文档发布到更可信页面。', 'warn'],
    ['竞品差距', '69', '竞品在对比类问题里更常被推荐。', '生成竞品对比和选型框架内容。', 'warn']
  ];
  return `
    <section class="panel">
      <div class="panel-head"><div><span class="panel-kicker">体检报告</span><h2>GEO优化诊断</h2><p>每一项都说明状态、评分、原因和优化建议。</p></div><button>导出报告</button></div>
      <div class="diagnosis-list">
        ${rows.map(row => `<div class="diagnosis-item"><b>${row[0]}</b><strong>${row[1]}</strong><p><span class="tag ${row[4]}">${row[4] === 'good' ? '表现良好' : row[4] === 'bad' ? '优先修复' : '需要优化'}</span><br>${row[2]}</p><p>${row[3]}</p></div>`).join('')}
      </div>
    </section>`;
}

function knowledgeBody() {
  return `
    <section class="panel">
      <div class="panel-head"><div><span class="panel-kicker">素材类型</span><h2>品牌可信素材</h2><p>让所有内容生成都有明确事实来源。</p></div><button>上传资料</button></div>
      <div class="knowledge-grid">
        ${knowledge('品牌', '品牌介绍、核心能力、品牌边界', '38 条')}
        ${knowledge('产品', '功能说明、版本差异、适用场景', '64 条')}
        ${knowledge('解决方案', '行业方案、角色场景、落地路径', '27 条')}
        ${knowledge('FAQ', '选型、价格、对比、使用问题', '96 条')}
        ${knowledge('案例', '行业、规模、结果数据', '21 条')}
        ${knowledge('官网 / 公众号 / 上传资料', '可被内容生成复用的材料', '143 条')}
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><div><span class="panel-kicker">素材健康度</span><h2>下一步补什么</h2><p>优先补能影响 AI 推荐和引用的证据。</p></div></div>
      <div class="recommend-list">
        ${recommend('案例缺口', '智能客服缺少 3 个可公开客户案例', '补案例后可支撑“企业客服系统怎么选”提问。')}
        ${recommend('FAQ缺口', '价格、版本和替代方案问题不足', '这些内容更容易被 AI 摘取为答案。')}
      </div>
    </section>`;
}

function articlesBody() {
  return `
    <section class="panel">
      <div class="panel-head"><div><span class="panel-kicker">AI推荐写作</span><h2><span class="stars">★★★★★</span> CRM软件哪个好？</h2><p>关联业务：CRM；关键词：CRM软件；发布后追踪 AI 引用次数。</p></div><button class="action-button primary">立即生成</button></div>
      <div class="article-grid">
        ${article('企业 CRM 软件怎么选？', '待生成 · 预计提升推荐率', '绑定 12 条品牌事实、3 个案例')}
        ${article('免费 CRM 适合小团队吗？', '待优化 · 价格信息需更新', '绑定产品版本和 FAQ')}
        ${article('CRM 与销售自动化的区别', '已发布 · AI引用 18 次', '继续补第三方观点')}
        ${article('中小企业 CRM 选型清单', '草稿 · 缺少案例', '补客户案例后发布')}
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><div><span class="panel-kicker">文章追踪</span><h2>发布后的 AI 引用</h2><p>文章不是结束，持续追踪引用和推荐变化。</p></div></div>
      <table class="flow-table">
        <thead><tr><th>文章</th><th>AI引用</th><th>影响提问</th></tr></thead>
        <tbody>
          <tr><td>CRM 与销售自动化的区别</td><td>18 次</td><td>销售自动化工具怎么选？</td></tr>
          <tr><td>智能客服价格 FAQ</td><td>11 次</td><td>智能客服系统多少钱？</td></tr>
          <tr><td>企业数据平台选型框架</td><td>6 次</td><td>数据分析平台哪个好？</td></tr>
        </tbody>
      </table>
    </section>`;
}

function settingsBody() {
  return standardBody('基础配置', [
    metric('品牌资料', '完整', '品牌介绍、官网和行业已配置。', '补禁用表述'),
    metric('AI模型', '7 个', '已覆盖主流模型，适合日常品牌观察。', '确认重点模型'),
    metric('团队权限', '12 人', '内容、品牌、市场负责人已分工。', '补审核人')
  ], '配置影响', [
    ['品牌设置', '影响 AI 对品牌身份和能力的理解', '当前完整', '定期复核'],
    ['AI模型', '决定观察哪些 AI 回答', '7 个模型', '按市场重点调整'],
    ['团队权限', '决定谁能生成、审核和发布内容', '12 名成员', '设置审批']
  ]);
}

function standardBody(title, metrics, tableTitle, rows) {
  return `
    <section class="panel main-analysis">
      <div class="panel-head"><div><span class="panel-kicker">页面主体</span><h2>${title}</h2><p>围绕当前状态、原因和下一步动作组织信息。</p></div><button>新增</button></div>
      <div class="metric-list">${metrics.join('')}</div>
    </section>
    <section class="panel detail-panel">
      <div class="panel-head"><div><span class="panel-kicker">表格设计</span><h2>${tableTitle}</h2><p>表格只展示做决策需要的信息。</p></div></div>
      <table class="flow-table">
        <thead><tr><th>对象</th><th>关联内容</th><th>表现</th><th>操作</th></tr></thead>
        <tbody>${rows.map(row => `<tr><td>${row[0]}</td><td>${row[1]}</td><td>${row[2]}</td><td><span class="tag">${row[3]}</span></td></tr>`).join('')}</tbody>
      </table>
    </section>`;
}

function insightMetric(name, value, delta, reason, action) {
  return `<article class="insight-card"><span>${name}</span><strong>${value}</strong><em>${delta}</em><p>${reason}</p><button>${action}</button></article>`;
}

function briefAction(no, title, text, impact) {
  return `<article class="brief-action"><b>${no}</b><strong>${title}</strong><p>${text}</p><em>${impact}</em></article>`;
}

function briefJudgement(title, text) {
  return `<article class="brief-judgement"><strong>${title}</strong><p>${text}</p></article>`;
}

function briefMetric(label, value, delta) {
  return `<article class="brief-metric"><span>${label}</span><strong>${value}</strong><em>${delta}</em></article>`;
}

function trendBlock(title = '趋势与变化') {
  return `<div class="trend-card"><div class="trend-head"><div><span class="panel-kicker">${title}</span><h3>结果 → 原因 → 建议</h3></div><b>近 30 天</b></div><div class="trend-bars"><i style="height:42%"></i><i style="height:48%"></i><i style="height:52%"></i><i style="height:58%"></i><i style="height:66%"></i><i style="height:72%"></i><i style="height:78%"></i></div><div class="trend-caption"><span>结果：品牌可见度持续上升</span><span>原因：FAQ 与官网页面被引用</span><span>建议：补充案例和第三方来源</span></div></div>`;
}

function businessBar(name, value, delta, width, isDown = false) {
  return `<article class="business-bar ${isDown ? 'down' : ''}"><div><b>${name}</b><span>提及率 ${value}</span></div><em>${delta}</em><i><u style="width:${width}%"></u></i></article>`;
}

function modelCard(name, value, note, width, weak = false) {
  return `<article class="model-card ${weak ? 'weak' : ''}"><div><b>${name}</b><span>${note}</span></div><strong>${value}</strong><i><u style="width:${width}%"></u></i></article>`;
}

function modelRank(rank, name, value) {
  return `<article class="model-rank"><b>${rank}</b><span>${name}</span><i><u style="width:${value}%"></u></i><em>${value}%</em></article>`;
}

function opportunityCard(priority, business, question, status, competitor, reason, suggestion, action) {
  return `<article class="opportunity-card"><div class="opportunity-head"><span>${priority}</span><b>${business}</b></div><h3>${question}</h3><dl><dt>现状</dt><dd>${status}</dd><dt>竞品</dt><dd>${competitor}</dd><dt>原因</dt><dd>${reason}</dd><dt>建议</dt><dd>${suggestion}</dd></dl><button class="action-button primary">${action}</button></article>`;
}

function updateCard(region, title, change, impact, suggestion) {
  return `<article class="update-card"><span>${region}</span><b>${title}</b><p><strong>变化：</strong>${change}</p><p><strong>对你的影响：</strong>${impact}</p><p><strong>建议：</strong>${suggestion}</p></article>`;
}

function updateMini(title, change, impact) {
  return `<article class="update-mini"><b>${title}</b><p>${change}</p><span>${impact}</span></article>`;
}

function riskCard(title, happened, why, action) {
  return `<article class="risk-card"><b>${title}</b><p><strong>发生了什么：</strong>${happened}</p><p><strong>为什么重要：</strong>${why}</p><p><strong>建议怎么办：</strong>${action}</p></article>`;
}

function riskMini(title, happened, detail) {
  return `<article class="risk-mini"><b>${title}</b><p>${happened}</p><span>${detail}</span></article>`;
}

function portraitModel(name, stars, score, delta) {
  return `<div class="portrait-model"><b>${name}</b><span>${stars}</span><strong>${score}</strong><em class="${delta.startsWith('-') ? 'down' : ''}">${delta}</em></div>`;
}

function portraitBar(label, value) {
  return `<div class="portrait-bar"><b>${label}</b><i><u style="width:${value}%"></u></i><span>${value}%</span></div>`;
}

function portraitSource(label, value, color) {
  return `<div class="portrait-source-row"><i style="background:${color}"></i><span>${label}</span><b>${value}</b></div>`;
}

function portraitTrait(text, value, danger = false) {
  return `<div class="portrait-trait ${danger ? 'danger' : ''}"><span>${text}</span><b>${value}</b></div>`;
}

function portraitSuggestion(title, text, priority) {
  return `<article class="portrait-suggestion"><b>${title}</b><p>${text}</p><span>${priority}</span></article>`;
}

function metric(name, value, reason, action) {
  return `<div class="metric-item"><div><b>${name}</b><p>${reason}</p></div><div class="metric-value"><strong>${value}</strong><em>${action}</em></div></div>`;
}

function recommend(title, text, reason) {
  return `<div class="recommend-item"><b>${title}</b><p>${text}</p><p>${reason}</p><span class="tag">一键加入优化</span></div>`;
}

function knowledge(title, text, count) {
  return `<div class="knowledge-item"><b>${title}</b><p>${text}</p><span class="tag">${count}</span></div>`;
}

function article(title, status, text) {
  return `<div class="article-item"><b>${title}</b><p>${status}</p><p>${text}</p><span class="tag">查看流程</span></div>`;
}

document.getElementById('prototypeNav').addEventListener('click', event => {
  const parent = event.target.closest('.nav-parent');
  if (parent) {
    parent.closest('.nav-section')?.classList.toggle('open');
    return;
  }
  const button = event.target.closest('[data-page]');
  if (!button) return;
  renderPage(button.dataset.page);
});

renderPage('overview');
