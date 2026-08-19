#!/usr/bin/env bash
set -euo pipefail

PROJECT="searchpilot"
SERVER="root@demo.mangoguai.com"
SSH_KEY="/Users/daisy/.ssh/daoju_deploy"
REMOTE_ROOT="/var/www/prototypes"
REMOTE_TARGET="${REMOTE_ROOT}/${PROJECT}"
REMOTE_BACKUP_ROOT="/var/backups/${PROJECT}"
TS="$(date +%Y%m%d-%H%M%S)"
PACKAGE_NAME="${PROJECT}-static-${TS}.tar.gz"
PACKAGE="/private/tmp/${PACKAGE_NAME}"
REMOTE_PACKAGE="/tmp/${PACKAGE_NAME}"
REMOTE_TMP="${REMOTE_ROOT}/.${PROJECT}-deploy-${TS}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

echo "== Growth Sniper deploy precheck =="
node --check shared/prototype-runtime-v2.js
node --check seo/assets/seo-content-v1.js
node --check seo/assets/seo-sidebar-v2.js
node --check geo/assets/geo-content-v1.js
node --check geo/assets/geo-sidebar-v1.js
node --check hub/assets/app.js
node --check sem/assets/app.js
node --check content/assets/app.js

node <<'NODE'
const fs = require('fs');
const path = require('path');
const files = [];
function walk(dir) {
  for (const name of fs.readdirSync(dir)) {
    if (['.git', '.agents', '.codex', 'scripts'].includes(name)) continue;
    const file = path.join(dir, name);
    const stat = fs.statSync(file);
    if (stat.isDirectory()) walk(file);
    else if (file.endsWith('.html')) files.push(file);
  }
}
walk('.');
const missing = [];
const dupIds = [];
const attr = /(?:src|href)=["']([^"']+)["']|id=["']([^"']+)["']/g;
for (const file of files) {
  const text = fs.readFileSync(file, 'utf8');
  const ids = {};
  let match;
  while ((match = attr.exec(text))) {
    if (match[1]) {
      const url = match[1];
      if (/^(https?:|#|mailto:|tel:|javascript:)/.test(url)) continue;
      const clean = url.split('?')[0].split('#')[0];
      if (!clean) continue;
      if (!fs.existsSync(path.resolve(path.dirname(file), clean))) missing.push(`${file} -> ${url}`);
    } else {
      ids[match[2]] = (ids[match[2]] || 0) + 1;
    }
  }
  for (const [id, count] of Object.entries(ids)) {
    if (count > 1) dupIds.push(`${file}#${id} x${count}`);
  }
}
if (missing.length || dupIds.length) {
  console.error(JSON.stringify({ missing, duplicateIds: dupIds }, null, 2));
  process.exit(1);
}
console.log(`HTML checked: ${files.length}, missing resources: 0, duplicate ids: 0`);
NODE

echo "== Create package: ${PACKAGE} =="
rm -f "${PACKAGE}"
COPYFILE_DISABLE=1 tar \
  --exclude='.DS_Store' \
  --exclude='._*' \
  --exclude='PROJECT_HANDOFF.md' \
  --exclude='scripts' \
  --exclude='.git' \
  --exclude='.agents' \
  --exclude='.codex' \
  -czf "${PACKAGE}" \
  index.html acquisition-preview.html content geo hub sem seo shared

echo "== Upload package =="
scp -i "${SSH_KEY}" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new "${PACKAGE}" "${SERVER}:${REMOTE_PACKAGE}"

echo "== Remote deploy =="
ssh -i "${SSH_KEY}" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new "${SERVER}" \
  "set -euo pipefail
   mkdir -p '${REMOTE_BACKUP_ROOT}' '${REMOTE_ROOT}'
   rm -rf '${REMOTE_TMP}'
   mkdir -p '${REMOTE_TMP}'
   tar -xzf '${REMOTE_PACKAGE}' -C '${REMOTE_TMP}'
   BACKUP_DIR='none'
   if [ -d '${REMOTE_TARGET}' ]; then
     BACKUP_DIR='${REMOTE_BACKUP_ROOT}/${TS}'
     mkdir -p \"\${BACKUP_DIR}\"
     cp -a '${REMOTE_TARGET}/.' \"\${BACKUP_DIR}/\"
   fi
   rm -rf '${REMOTE_TARGET}'
   mv '${REMOTE_TMP}' '${REMOTE_TARGET}'
   chown -R root:root '${REMOTE_TARGET}'
   rm -f '${REMOTE_PACKAGE}'
   echo \"backup_dir=\${BACKUP_DIR}\"
   echo 'nginx_check_start'
   nginx -t
   echo 'nginx_check_end'"

echo "== HTTP validation =="
if [ -n "${SEARCHPILOT_BASIC_AUTH:-}" ]; then
  curl -fsSI -u "${SEARCHPILOT_BASIC_AUTH}" "https://demo.mangoguai.com/${PROJECT}/" >/dev/null
  curl -fsSI -u "${SEARCHPILOT_BASIC_AUTH}" "https://demo.mangoguai.com/${PROJECT}/seo/dashboard.html?rev=seo-nav-v4" >/dev/null
  curl -fsSI -u "${SEARCHPILOT_BASIC_AUTH}" "https://demo.mangoguai.com/${PROJECT}/geo/dashboard.html?rev=geo-nav-v4" >/dev/null
  echo "authenticated_http=ok"
else
  curl -sSI "https://demo.mangoguai.com/${PROJECT}/" | head -n 1
  echo "Set SEARCHPILOT_BASIC_AUTH='user:password' for authenticated HTTP validation."
fi

echo "package=${PACKAGE_NAME}"
echo "remote_target=${REMOTE_TARGET}"
echo "url=https://demo.mangoguai.com/${PROJECT}/"
