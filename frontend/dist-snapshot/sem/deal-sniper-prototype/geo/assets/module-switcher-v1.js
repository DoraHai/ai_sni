(function () {
  // Legacy GEO pages used to inject a fixed module switcher in the top-right.
  // Keep navigation consistent with the current apps: the portal action belongs
  // at the bottom of the native left sidebar.
  var sidebar = document.querySelector('.sidebar');
  if (!sidebar || sidebar.querySelector('a[href*="/deal-sniper/portal"]')) return;

  var portal = document.createElement('a');
  portal.className = 'back-link';
  portal.href = 'https://sem.snipers.com.cn/deal-sniper/portal';
  portal.target = '_top';
  portal.textContent = '← 返回平台门户';
  sidebar.appendChild(portal);
})();
