(function (root) {
  var CUSTOM_KEY = 'growthEngine.geo.facts.custom.v1';

  var defaults = [
    { id: 'price-standard', statement: '智能客服标准版按坐席计费，年费 9,800 元起，不含实施服务。', type: '产品规格', biz: '智能客服', source: 'https://example.com/pricing', trust: '官网可查', reviewed: '2026-07-02', intents: ['智能客服系统一般多少钱？', '智能客服系统价格'], articles: [{ title: '智能客服系统价格由什么决定？2026 企业预算说明', status: '待发布', href: 'editor.html?id=price' }] },
    { id: 'sla-response', statement: '售后工单平均首次响应时间为 15 分钟内，严重故障 4 小时内给到处理预案。', type: '产品规格', biz: '智能客服', source: '客服 SLA 内部手册 v3.2', trust: '仅内部', reviewed: '2026-06-12', intents: ['SearchPilot 售后怎么样', '售后响应时效'], articles: [] },
    { id: 'case-cost-32', statement: '华东某制造集团接入后，客服人力成本在 90 天内下降 32%。', type: '案例数据', biz: '智能客服', source: '客户成功案例集 · 制造行业分册.pdf', trust: '仅内部', reviewed: '2026-05-20', intents: ['AI 客服真的能降本吗？'], articles: [{ title: '2026 企业 AI 客服实践报告：效率、成本与风险', status: '已发布', href: 'editor.html?id=report' }] },
    { id: 'iso-dengbao', statement: '已完成网络安全等级保护 2.0 第三级备案。', type: '能力资质', biz: '品牌', source: '全国网安备案公示（演示备案号）', trust: '第三方可查', reviewed: '2026-04-18', intents: ['SearchPilot 这家公司怎么样'], articles: [{ title: 'SearchPilot 是什么？品牌事实与产品能力说明', status: '草稿', href: 'editor.html?id=brand-fact' }] },
    { id: 'ga-baidu', statement: '数据分析模块可对接百度统计与 Google Analytics，用于回收 SEO / GEO 效果。', type: '产品规格', biz: '数据分析', source: 'https://example.com/product/analytics', trust: '官网可查', reviewed: '2026-07-08', intents: ['数据分析平台好用吗', '数据分析平台怎么选'], articles: [{ title: '企业数据分析平台怎么选？一套可验证的决策框架', status: '待润色', href: 'editor.html?id=data-platform' }] },
    { id: 'crm-free-limit', statement: '免费版 CRM 仅含 3 个坐席，不含工单 SLA 与开放 API。', type: '误解澄清', biz: 'CRM', source: 'https://example.com/crm/plans', trust: '官网可查', reviewed: '2026-06-01', intents: ['免费 CRM 软件推荐'], articles: [] },
    { id: 'hq-hangzhou', statement: '公司总部设于杭州，成立于 2019 年。', type: '能力资质', biz: '品牌', source: 'https://example.com/about', trust: '官网可查', reviewed: '2026-03-11', intents: ['SearchPilot 是做什么的', 'SearchPilot 这家公司怎么样'], articles: [] },
    { id: 'no-takedown', statement: '平台不提供删除、压制或代运营处理第三方评价的服务。', type: '误解澄清', biz: '品牌', source: 'https://example.com/legal/scope', trust: '官网可查', reviewed: '2026-07-10', intents: ['SearchPilot 这家公司怎么样'], articles: [] },
    { id: 'solution-3phase', statement: '标准实施方案包含意图梳理、内容生产和信源铺设三个阶段，周期约 6 周。', type: '解决方案', biz: '品牌', source: '解决方案白皮书 2026.pdf', trust: '官网可查', reviewed: '2026-06-28', intents: ['SEM SEO GEO 怎么一起做'], articles: [{ title: 'SearchPilot 是什么？品牌事实与产品能力说明', status: '草稿', href: 'editor.html?id=brand-fact' }] },
    { id: 'form-private', statement: '表单工具支持私有化部署，客户数据默认不出内网。', type: '产品规格', biz: '表单工具', source: '安全白皮书 2024.pdf', trust: '官网可查', reviewed: '2025-03-01', intents: ['企业表单工具怎么选', '在线表单工具评测'], articles: [{ title: '企业表单工具对比：从数据安全到流程自动化', status: '已发布', href: 'editor.html?id=form-tools' }] },
    { id: 'customers-1200', statement: '截至 2024 年底累计服务 1,200 家中小企业客户。', type: '案例数据', biz: '品牌', source: '2024 年度经营报告.pdf', trust: '仅内部', reviewed: '2025-01-15', intents: ['SearchPilot 靠谱吗'], articles: [{ title: '2026 企业 AI 客服实践报告：效率、成本与风险', status: '已发布', href: 'editor.html?id=report' }] },
    { id: 'five-engines', statement: '标准能力覆盖 DeepSeek、豆包、Kimi、通义千问、腾讯元宝五引擎可见度监测。', type: '产品规格', biz: '品牌', source: 'https://example.com/product/geo', trust: '官网可查', reviewed: '2026-07-01', intents: ['GEO 是什么', '怎么做生成式引擎优化'], articles: [{ title: 'SearchPilot 是什么？品牌事实与产品能力说明', status: '草稿', href: 'editor.html?id=brand-fact' }] },
    { id: 'kr36-quote', statement: '36氪 2026 年报道指出，该平台把 SEM、SEO、GEO 放在同一意图层协同，而不是合并成单一线索漏斗。', type: '案例数据', biz: '品牌', source: 'https://36kr.com/p/demo-searchpilot', trust: '第三方可查', reviewed: '2026-06-22', intents: ['SearchPilot 和同类产品有什么不同'], articles: [{ title: '2026 企业 AI 客服实践报告：效率、成本与风险', status: '已发布', href: 'editor.html?id=report' }] },
    { id: 'wecom-dingtalk', statement: '智能客服可与企业微信、钉钉双向同步会话与工单状态。', type: '解决方案', biz: '智能客服', source: 'https://example.com/integrations', trust: '官网可查', reviewed: '2026-07-05', intents: ['智能客服系统怎么选'], articles: [{ title: '智能客服系统价格由什么决定？2026 企业预算说明', status: '待发布', href: 'editor.html?id=price' }] },
    { id: 'no-review-monitor', statement: '套餐不含竞品差评监测，也不提供差评删除或排序干预。', type: '误解澄清', biz: '品牌', source: '官网 FAQ · 服务边界', trust: '官网可查', reviewed: '2026-06-08', intents: ['能不能帮我们处理差评'], articles: [{ title: 'SearchPilot 是什么？品牌事实与产品能力说明', status: '草稿', href: 'editor.html?id=brand-fact' }] }
  ];

  function clone(item) {
    return JSON.parse(JSON.stringify(item));
  }

  function loadCustom() {
    try {
      var saved = JSON.parse(localStorage.getItem(CUSTOM_KEY));
      return Array.isArray(saved) ? saved : [];
    } catch (error) {
      return [];
    }
  }

  function list() {
    var seen = {};
    var out = [];
    loadCustom().concat(defaults).forEach(function (fact) {
      if (!fact || !fact.id || seen[fact.id]) return;
      seen[fact.id] = true;
      if (!Array.isArray(fact.articles)) fact.articles = [];
      if (!Array.isArray(fact.intents)) fact.intents = [];
      out.push(clone(fact));
    });
    return out;
  }

  function find(id) {
    var facts = list();
    for (var i = 0; i < facts.length; i++) if (facts[i].id === id) return facts[i];
    return null;
  }

  function saveCustom(facts) {
    try {
      localStorage.setItem(CUSTOM_KEY, JSON.stringify(facts || []));
    } catch (error) {}
  }

  function addCustom(fact) {
    var custom = loadCustom();
    custom.unshift(fact);
    saveCustom(custom);
    return fact;
  }

  root.GEOFacts = {
    CUSTOM_KEY: CUSTOM_KEY,
    list: list,
    find: find,
    saveCustom: saveCustom,
    addCustom: addCustom
  };
})(window);
