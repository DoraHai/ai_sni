# SEM backend log rotation

`sem-backend.service` appends stdout and stderr to files under
`/var/log/sem-backend`. Install `sem-backend.logrotate` as a separately reviewed
operations change; ordinary frontend or backend application deployment does not
install system configuration.

## Controlled installation

1. Confirm the active service still writes to the two paths declared in
   `deploy/sem-backend.logrotate`, and confirm both files remain owned by
   `root:root`. systemd opens these append targets before starting the process.
2. Back up an existing `/etc/logrotate.d/sem-backend` file, if present.
3. Compare the reviewed repository file with the proposed server file.
4. Install it as `/etc/logrotate.d/sem-backend`, owned by `root:root` with mode
   `0644`.
5. Run `logrotate -d /etc/logrotate.d/sem-backend` and review the dry-run output.
6. Verify the next scheduled rotation and confirm `sem-backend` remains active.

The configuration uses `copytruncate` because systemd keeps the append-only log
file descriptors open. Installing it does not require restarting `sem-backend`.
It rotates daily, retains 14 archives, and rotates an active log at the next
scheduled check when it exceeds 50 MiB. Rotation runs as `root:root` to match
the active files; it does not change the service process user.

Rollback consists of restoring the backed-up logrotate file, or removing the
new file when no previous version existed. It does not modify application
releases or database data.
