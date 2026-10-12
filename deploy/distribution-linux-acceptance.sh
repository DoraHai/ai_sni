#!/usr/bin/env bash
# Separate acceptance cluster and services. Never changes production units or Nginx.
set -euo pipefail
base=/opt/gsnipers-distribution-acceptance
work="$base/work/distribution-server-pilot-20261012"
actor=distacceptance
action=${1:?prepare|initialize|start|health|stop}
release=${2:-}
if [[ $(id -u) != 0 ]]; then echo 'Root is required for owned service setup' >&2; exit 1; fi
if [[ -n "$release" && ! "$release" =~ ^[0-9a-f]{40}$ ]]; then echo 'Invalid exact source commit' >&2; exit 1; fi
run_owned() { runuser -u "$actor" -- "$@"; }
if [[ "$action" == prepare ]]; then
  checksum=${3:?bundle SHA256 required}
  [[ "$checksum" =~ ^[0-9a-f]{64}$ ]]
  [[ -n "$release" ]]
  archive="/var/tmp/gsnipers-distribution-acceptance-$release.bundle"
  [[ $(sha256sum "$archive" | cut -d' ' -f1) == "$checksum" ]]
  if ! id "$actor" >/dev/null 2>&1; then useradd --system --home-dir "$base" --shell /sbin/nologin "$actor"; fi
  install -d -m 700 -o "$actor" -g "$actor" "$base" "$base/releases" "$base/work"
  destination="$base/releases/$release"
  [[ ! -e "$destination" ]] || { echo 'Do not replace an existing release' >&2; exit 1; }
  install -d -m 700 -o "$actor" -g "$actor" "$destination"
  install -m 600 -o "$actor" -g "$actor" "$archive" "$destination/source.bundle"
  for module in central seo geo; do
    run_owned git clone --quiet --no-checkout "$destination/source.bundle" "$destination/$module"
    pin="$release"
    [[ "$module" != seo ]] || pin=b4d8387123355348f79e26ea2838585c5106a4b9
    [[ "$module" != geo ]] || pin=46dacbd805afc00f37eba344306fde004039efed
    run_owned git -C "$destination/$module" checkout --quiet --detach "$pin"
    [[ $(run_owned git -C "$destination/$module" rev-parse HEAD) == "$pin" ]]
    [[ -z $(run_owned git -C "$destination/$module" status --porcelain) ]]
  done
  if [[ ! -d "$base/venv" ]]; then run_owned python3.11 -m venv "$base/venv"; fi
  # These locks belong to the reviewed native SEO pilot; there are no browser installs.
  run_owned "$base/venv/bin/python" -m pip install --disable-pip-version-check --timeout 20 --retries 2 --index-url https://mirrors.aliyun.com/pypi/simple/ -r "$destination/seo/requirements.txt" tzdata==2026.3
  run_owned bash -c 'cd "$1/customer-workbench"; npm ci --no-audit --no-fund; npm run build' _ "$destination/central"
  printf '{"prepared":true,"source_commit":"%s","production":false}\n' "$release"
elif [[ "$action" == initialize ]]; then
  [[ -n "$release" ]]
  [[ ! -e "$work" ]] || { echo 'Do not reinitialize an existing private cluster' >&2; exit 1; }
  snapshot="/var/tmp/gsnipers-distribution-acceptance-$release-snapshot.json"
  [[ -f "$snapshot" && $(sha256sum "$snapshot" | cut -d' ' -f1) == f75d382a54ec33f0c892cc4c6afcc17b082c130cc1b58236fb4dde48e383f609 ]]
  runner="$base/releases/$release/central/scripts/distribution_linux_acceptance.py"
  run_owned "$base/venv/bin/python" -B "$runner" bootstrap --release "$base/releases/$release"
  run_owned /usr/bin/initdb -D "$work/pg" -U distribution_acceptance --pwfile="$work/postgres.secret" --auth-local=peer --auth-host=scram-sha-256 --encoding=UTF8 >/dev/null
  install -d -m 700 -o "$actor" -g "$actor" "$work/pgsocket"
  # Explicit paths and loopback ports are the only permitted data/socket targets.
  [[ $(readlink -f "$work/pg") == "$work/pg" ]]
  [[ ! -e /etc/systemd/system/gsnipers-distribution-acceptance-db.service ]]
  cat > /etc/systemd/system/gsnipers-distribution-acceptance-db.service <<UNIT
[Unit]
Description=Independent distribution acceptance PostgreSQL (separate local data directory)
After=network.target
[Service]
User=$actor
Group=$actor
WorkingDirectory=$work
ExecStart=/usr/bin/postgres -D $work/pg -h 127.0.0.1 -p 55483 -c unix_socket_directories=$work/pgsocket -c max_connections=30 -c shared_buffers=128MB -c timezone=UTC
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$base
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl start gsnipers-distribution-acceptance-db
  for attempt in $(seq 1 30); do
    /usr/bin/pg_isready -h 127.0.0.1 -p 55483 -q && break
    sleep 1
  done
  /usr/bin/pg_isready -h 127.0.0.1 -p 55483 -q
  for module in seo geo; do
    run_owned bash -c 'export PGPASSWORD=$(cat "$1/postgres.secret"); createdb -h 127.0.0.1 -p 55483 -U distribution_acceptance "distribution_acceptance_$2"' _ "$work" "$module"
  done
  # The previously authorized snapshot is copied separately over SSH, never through GitHub.
  install -m 600 -o "$actor" -g "$actor" "$snapshot" "$work/customer-snapshot.json"
  for module in seo geo; do run_owned "$base/venv/bin/python" -B "$runner" initialize --module "$module"; done
  printf '{"initialized":true,"production":false,"private_credentials_printed":false}\n'
elif [[ "$action" == start ]]; then
  [[ -n "$release" && -f "$work/environment.json" ]]
  runner="$base/releases/$release/central/scripts/distribution_linux_acceptance.py"
  for module in seo geo; do
    name="gsnipers-distribution-acceptance-$module"
    [[ ! -e "/etc/systemd/system/$name.service" ]] || { echo 'Do not replace an existing unit' >&2; exit 1; }
    cat > "/etc/systemd/system/$name.service" <<UNIT
[Unit]
Description=Independent distribution acceptance $module (no production database)
After=network.target gsnipers-distribution-acceptance-db.service
Requires=gsnipers-distribution-acceptance-db.service
[Service]
User=$actor
Group=$actor
WorkingDirectory=$work
ExecStart=$base/venv/bin/python -B $runner serve --module $module
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=$base
ProtectHome=true
PrivateTmp=true
[Install]
WantedBy=multi-user.target
UNIT
  done
  systemctl daemon-reload
  systemctl start gsnipers-distribution-acceptance-seo gsnipers-distribution-acceptance-geo
  echo '{"started":true,"public_listener":false,"production":false}'
elif [[ "$action" == health ]]; then
  for module in seo geo; do
    port=55861; [[ "$module" != geo ]] || port=55862
    curl --fail --silent --cacert "$work/loopback.pem" "https://127.0.0.1:$port/acceptance/health"
    printf '\n'
  done
elif [[ "$action" == stop ]]; then
  systemctl stop gsnipers-distribution-acceptance-seo gsnipers-distribution-acceptance-geo
  systemctl stop gsnipers-distribution-acceptance-db
  echo '{"stopped":true,"production":false}'
else echo 'Unknown acceptance operation' >&2; exit 1; fi
