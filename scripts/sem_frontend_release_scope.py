"""Decide whether a production push changed SEM frontend build inputs."""
import re
import subprocess
import sys


def requires_release(paths):
    return any(path.startswith(('frontend/', 'integrations/')) for path in paths)


def main():
    base, head = sys.argv[1:]
    if any(not re.fullmatch('[0-9a-f]{40}', ref) or ref == '0'*40 for ref in (base, head)):
        raise SystemExit('Require actual production commit identities')
    for ref in (base, head):
        subprocess.run(['git', 'cat-file', '-e', ref + '^{commit}'], check=True)
    result = subprocess.run(['git', 'diff', '--name-only', '-z', base, head], check=True, capture_output=True)
    paths = result.stdout.decode('utf-8').split('\0')
    print('sem_changed=' + ('true' if requires_release(paths) else 'false'))


if __name__ == '__main__':
    main()
