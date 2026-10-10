// One-time archive of the console reminders the administrator asked to clear.
// Exact source and signal hashes preserve new incidents on the same source.
// This changes notification visibility only; accounting and job state stay intact.
export const platformAlertArchive=Object.freeze({
  clearedAt:'2026-10-10T07:24:07.740083+00:00',
  unpricedPeriod:'2026-10',
  controlsState:'schema_pending',
  items:Object.freeze([
    ['a5311049fcd2033ac527f6420c7e5d634cbb245f46a86af7f1d0d816733a5beb','2143ac16ceff5088b4e503354d499a1e2a4af25d95ffea3eede4eb0cc1715d56'],
    ['e548751164c99a271c32037a1dce9e2dda5cd40df3ea0f5bd383bbe9b753f21a','ae29332dc932684b5f92c08b14c6ccfb167c20beeeee2ba0493cb62054771024'],
    ['7df0bb267ece833341edd7daa038df735e804f395e7fa53afaf369949714dec8','61600b9ed832f814e9b0bc146daaffcabcd6e67c7d5ae8615d8c7c1664f9e1d7'],
    ['d6cf717a52fdfaf30a33c3d49aca3fdb5a409016e2108638c33f3da96969b4b8','e908e395c6ed2420c24bc83aa1322615a1940e913e8b2728dc47ecea50deae3e'],
    ['9951d4b9d7492e430210543f574304f57fb201a19975139909531e483b31f3cd','c0d12074bb05a6049909a45f26da2afd69599cc336ae3d25156940c9de9fd822'],
    ['4e4f32ed94d41c4a7f59b16bd52ddf6ec46f26fe264224b011c7f3c8c51d962b','dee17fb85a19753699cf88a479a0f3370930c3132197a2853c765d611bd4876f'],
    ['8788ff27960f51f109296285803ebc3d6d289ff040365f7ed59d543c8c809fcd','dee17fb85a19753699cf88a479a0f3370930c3132197a2853c765d611bd4876f'],
    ['3ad61b47091eb0f12059f08d4d96b4c053000f96dc8e5b76f92cf6a783fac88b','a93e07a61c6aa377ff0cab8913c9577f39ad5c196bbcb50350be2a731817925c'],
    ['e81a9928d183c723d585219ac6f1cedc027081d6b1d168238ca055ce76190686','e72a52bb3442c77f1afadd7ba6d7d1e23d5b7adc08fdb5cb8d94945d4944cbd6'],
  ].map(Object.freeze)),
});
const archiveApplies=snapshot=>Date.parse(snapshot.generated_at)>=Date.parse(platformAlertArchive.clearedAt);
export function visiblePlatformAlerts(snapshot){
  const applies=archiveApplies(snapshot);
  return (snapshot.alerts||[]).filter(alert=>!applies||!platformAlertArchive.items.some(([id,signal])=>alert.id===id&&alert.signal===signal));
}
export function platformNotifications(snapshot,formatCount=String){
  const applies=archiveApplies(snapshot);
  const alerts=visiblePlatformAlerts(snapshot).filter(alert=>alert.handling?.status!=='resolved');
  // This is a recurring pricing reminder for the billing period, rather than
  // an incident for each additional unpriced call. Amounts remain on Costs.
  if(snapshot.api_costs?.unpriced>0&&(!applies||snapshot.api_costs.period!==platformAlertArchive.unpricedPeriod)){
    alerts.unshift({tenant_id:null,severity:'warning',message:`本月 ${formatCount(snapshot.api_costs.unpriced)} 次调用尚未定价，请按接口维护单价。`});
  }
  if(snapshot.controls?.state!=='enabled'&&(!applies||snapshot.controls?.state!==platformAlertArchive.controlsState)){
    alerts.push({tenant_id:null,severity:'warning',message:'接口配置与预算管理尚未启用，调用计量继续运行。'});
  }
  return alerts;
}
