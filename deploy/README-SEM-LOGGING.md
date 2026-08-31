# SEM backend log rotation

`sem-backend.service` appends stdout and stderr to files under
`/var/log/sem-backend`. Install `sem-backend.logrotate` only as a separately
reviewed operations change. Ordinary frontend and backend application releases
must not install system configuration.

## Controlled installation

1. Confirm `sem-backend.service` still writes to the two paths declared in
   `deploy/sem-backend.logrotate`.
2. Record the current owner and mode of `/var/log/sem-backend` and both active
   log files so rollback can restore them exactly.
3. Back up an existing `/etc/logrotate.d/sem-backend` file, if present, using a
   timestamped name outside the active configuration directory.
4. Compare the reviewed repository file with the proposed server file.
5. Install the reviewed file as `/etc/logrotate.d/sem-backend`, owned by
   `root:root` with mode `0644`.
6. Restrict `/var/log/sem-backend` to mode `0750` and both active log files to
   mode `0640`. Preserve their current owners unless the service definition has
   also been reviewed and changed.
7. Run `logrotate --debug --state /dev/null
   /etc/logrotate.d/sem-backend` and review the complete dry-run output.
8. Verify the next scheduled rotation, the rotated archive permissions, and
   that `sem-backend` remains active and `/health` still reports `db=ok`.

The configuration uses `copytruncate` because systemd keeps the append-only log
file descriptors open. Installing it does not require restarting
`sem-backend`. It rotates daily, retains 14 archives, and rotates an active log
at the next scheduled check when it exceeds 50 MiB. Rotation runs as
`root:root`, matching the production files observed when this configuration was
introduced; the installation procedure must re-check that assumption.

`copytruncate` can lose a small number of lines written between copying and
truncation. This trade-off avoids restarting the service or changing its file
descriptor lifecycle. A future journald migration should be reviewed as a
separate operational change.

Rollback restores the backed-up logrotate file, or removes the new file when no
previous version existed, and restores the recorded directory and file modes.
It does not modify application releases or database data.
