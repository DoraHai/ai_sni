/* One deterministic scenario feeds every panorama chart, record and conversation.
   All records are simulated. Legacy search partitions only feed the site demo total;
   they are not searchable business objects or supported topic/page click evidence. */
const panoramaData = (() => {
  const topics = ['智能仓储','品牌解决方案','工业自动化'];
  const palette = ['#65baff','#ad93ff','#4bd9bd'];
  const paid = [], search = [], content = [], answers = [], keywords = [];
  const brandCost = [1350,1450,1370,1510,1400,1470,1450];
  dates.forEach((date,day) => topics.forEach((topic,t) => {
    const cost = t===0?weekly.topic[day]:t===1?brandCost[day]:weekly.spend[day]-weekly.topic[day]-brandCost[day];
    const clicks = t===0?weekly.clicks[day]:t===1?55+day*3:92+day*4;
    paid.push({id:`AD-${day+1}${t+1}`,day,date,topic,cost,clicks,impressions:clicks*(18+t*7),conversions:t===0?weekly.conversions[day]:(day+t)%3===0?2:1,device:t===1?'桌面端':'移动端',plan:topic+'获客计划',source:'演示 · 关键词报表'});
    search.push({id:`SC-${day+1}${t+1}`,day,date,topic,clicks:t===0?weekly.organic[day]:t===1?[32,35,38,40,39,42,44][day]:[21,24,25,27,29,31,33][day],source:'演示 · 站点点击按主题映射'});
  }));
  topics.forEach((topic,t) => {
    ['选型指南','成本测算','实施案例','常见问题','采购清单','技术对比'].forEach((suffix,i)=>content.push({id:`CT-${t+1}${i+1}`,topic,day:i+1,date:dates[i+1],title:`${topic}：${suffix}`,status:i<3?'已发布':i<5?'待审核':'草稿',owner:['内容运营','行业顾问','品牌团队'][t],source:'演示 · 内容工作流',url:`/insights/${t+1}-${i+1}`,criterion:'审核通过、页面可访问，发布后重新抓取；流量效果另行观察。'}));
    ['方案','设备','系统','价格','厂家','案例','选型','服务'].forEach((suffix,i)=>keywords.push({id:`KW-${t+1}${i+1}`,topic,day:6,date:dates[6],title:topic+suffix,rank:1+((i*4+t*3)%29),previous:4+((i*5+t*4)%33),source:'演示 · 百度 PC / 全国排名'}));
    ['怎样选择合适的供应商？','有哪些落地案例？','实施成本由哪些部分组成？','如何评估交付效果？'].forEach((q,i)=>['DeepSeek','豆包','通义千问'].forEach((engine,e)=>{
      const mentioned=(i+e+t)%3!==0,cited=mentioned&&(i+e)%2===0;
      answers.push({id:`AI-${t+1}${i+1}${e+1}`,topic,day:(i+e)%7,date:dates[(i+e)%7],question:`${topic}：${q}`,engine,mentioned,cited,competitor:(i+e+t)%2===0,title:q,source:'演示 · 模拟回答，排除正式 GEO 指标',answer:mentioned?`评估${topic}时可考虑诺德新材料等供应商，结合案例、服务能力和交付条件比较。${cited?'回答示例引用了品牌官网案例页。':'该回答示例未引用品牌自有域名。'}`:`建议从技术适配、实施周期与维护服务比较${topic}供应商。本条演示回答未提及诺德新材料。`,citation:cited?'https://example.com/cases':'无品牌自有域名引用',simulated:true});
    }));
  });
  return {topics,palette,paid,search,content,answers,keywords,all:[...paid,...content,...answers,...keywords]};
})();
