"""Freeze four clean local components into a review bundle. Never deploy or apply SQL."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile


BASES = {
    'central': '729af3c4071d6f410ef12ecb88de6ca6a3559f13',
    'seo': 'ffce26e3636e72f5c98da7664662ea8b63fa31c1',
    'geo': 'b61e885627206029ff54bd6a572f6c1049b5dc25',
    'multihao': 'a6c4b36aa5b53591f872ab99ff44b4e93430663c',
}
ALLOW = {
    'central': ('app/api/distribution.py', 'app/distribution_', 'customer-workbench/',
                'scripts/distribution_', 'scripts/package_distribution_review.py',
                'tests/test_distribution_', 'docs/DISTRIBUTION_', 'requirements-distribution.txt'),
    'seo': ('app/seo_distribution_results.py', 'scripts/seo_distribution_results_schema.sql',
            'app/seo_publication_monitor.py', 'app/api/seo_page_captures.py', 'app/seo_scheduler.py',
            'tests/test_seo_scheduler.py', 'tests/test_seo_publication_monitor_',
            'tests/test_seo_distribution_', 'docs/SEO_DISTRIBUTION_RESULTS', 'docs/SEO_PUBLICATION_MONITOR'),
    'geo': ('app/geo/distribution_results.py', 'scripts/geo_distribution_results_schema.sql',
            'tests/test_geo_distribution_', 'docs/GEO_DISTRIBUTION_'),
    'multihao': ('src/main/distribution-', 'src/preload/distribution-candidate.ts',
                'scripts/build-distribution.mjs', 'scripts/verify-distribution-gui.mjs',
                'package.json', 'docs/DISTRIBUTION_CANDIDATE_GUI.md',
                'docs/DISTRIBUTION_EDITOR_INTEGRATION.md', 'docs/HANDOFF.md'),
}
DEPENDENCIES = {
    'central': ['app/distribution_control.py', 'app/distribution_scheduling.py',
                'scripts/distribution_control_schema.sql', 'scripts/distribution_scheduling_schema.sql',
                'requirements-distribution.txt', 'frontend/src/store/session.js',
                'frontend/src/store/sessionStorage.js', 'frontend/package-lock.json',
                'docs/DISTRIBUTION_LOCAL_HANDOFF_20261011.md', 'docs/DISTRIBUTION_SCHEDULING_HANDOFF_20261011.md',
                'docs/DISTRIBUTION_PUBLICATION_HANDOFF_20261011.md'],
    'seo': ['app/seo_distribution_sources.py', 'app/seo_distribution_media.py',
            'app/api/seo_distribution_media.py', 'scripts/seo_distribution_media_schema.sql',
            'scripts/seo_distribution_results_schema.sql'],
    'geo': ['app/geo/distribution_sources.py', 'app/geo/distribution_assets.py',
            'scripts/geo_distribution_results_schema.sql', 'docs/GEO_DISTRIBUTION_SOURCE_HANDOFF_20261011.md'],
    'multihao': ['docs/DISTRIBUTION_HOST.md', 'docs/DISTRIBUTION_PROTOCOL.md'],
}
SNAPSHOT_PREFIXES = {
    'central': ('app/distribution_', 'scripts/distribution_', 'tests/test_distribution_', 'docs/DISTRIBUTION_'),
    'seo': ('app/seo_distribution_', 'tests/test_seo_distribution_', 'docs/SEO_DISTRIBUTION_'),
    'geo': ('app/geo/distribution_', 'app/geo/distribution/', 'tests/test_geo_distribution_', 'docs/GEO_DISTRIBUTION_'),
    'multihao': ('src/main/distribution-', 'src/preload/distribution-candidate.ts',
                 'scripts/build-distribution.mjs', 'scripts/verify-distribution-gui.mjs', 'docs/DISTRIBUTION_'),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.PIPE)


def names(root, *args):
    return [name.decode('utf-8') for name in git(root, *args).split(b'\0') if name]


def safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe tracked path')
    if any(part in ('.env', 'node_modules', 'profiles', '.profiles', '.git') for part in path.parts):
        raise ValueError('Private runtime file is excluded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for component in BASES:
        parser.add_argument('--' + component, required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New directory, preferably under TEMP')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Output must be a new directory; no files are overwritten')
    roots = {name: getattr(args, name).resolve(strict=True) for name in BASES}
    entries = {}
    for name, root in roots.items():
        if output == root or root in output.parents:
            raise ValueError('Review bundle cannot be written inside a source checkout')
        if git(root, 'status', '--porcelain', '-z'):
            raise ValueError(name + ': commit and review all changes before packaging')
        head = git(root, 'rev-parse', 'HEAD').decode().strip()
        git(root, 'merge-base', '--is-ancestor', BASES[name], head)
        changed = names(root, 'diff', '--name-only', '-z', BASES[name], head)
        for path in changed:
            safe_name(path)
            if not path.startswith(ALLOW[name]):
                raise ValueError(name + ': unexpected component change: ' + path)
        tracked = set(names(root, 'ls-files', '-z'))
        dependencies = [path for path in DEPENDENCIES[name] if path in tracked]
        dependencies += [path for path in tracked if path.startswith(SNAPSHOT_PREFIXES[name])]
        if name == 'central':
            dependencies += [path for path in tracked if path.startswith('customer-workbench/')
                             and '/dist/' not in path and '/node_modules/' not in path]
        files = {}
        blobs = {}
        for path in sorted(set(changed + dependencies)):
            safe_name(path)
            if path not in tracked:
                raise ValueError('Deleted source requires explicit integration review: ' + path)
            data = git(root, 'show', head + ':' + path)
            blobs[path] = data
            files[path] = {'sha256': sha(data), 'bytes': len(data),
                           'worktree_sha256': sha((root / path).read_bytes()),
                           'role': 'changed' if path in changed else 'baseline-dependency'}
        patch = git(root, 'diff', '--binary', '--full-index', BASES[name], head, '--')
        entries[name] = {'root': str(root), 'base': BASES[name], 'commit': head,
                         'branch': git(root, 'branch', '--show-current').decode().strip(),
                         'files': files, 'patch_sha256': sha(patch), '_blobs': blobs, '_patch': patch}

    # Only include a clean, source-bound workbench build, never a mutable release.
    central = roots['central']
    build = central / 'customer-workbench/dist/customer-workbench'
    release = json.loads((build / 'release-manifest.json').read_text(encoding='utf-8'))
    if release['upstreamCommit'] != entries['central']['commit'] or release['sourceTreeClean'] is not True:
        raise ValueError('Build the committed, clean workbench before packaging')
    for path, expected in release['localSources'].items():
        safe_name(path)
        if sha((central / 'customer-workbench' / path).read_bytes()) != expected:
            raise ValueError('Workbench source changed since build: ' + path)
    for path, expected in release['canonicalSources'].items():
        if sha((central / 'frontend' / path).read_bytes()) != expected:
            raise ValueError('Canonical host source changed since build')
    if sha((central / 'frontend/package-lock.json').read_bytes()) != release['hostLockSha256']:
        raise ValueError('Host lock changed since build')
    if sha((central / 'customer-workbench/package-lock.json').read_bytes()) != release['independentLockSha256']:
        raise ValueError('Workbench lock changed since build')
    if set(path.name for path in build.iterdir()) != set(release['files']) | {'release-manifest.json'}:
        raise ValueError('Unexpected workbench build file')
    artifacts = {}
    for path in sorted(set(release['files']) | {'release-manifest.json'}):
        safe_name(path)
        data = (build / path).read_bytes()
        if path in release['files'] and release['files'][path] != {'sha256': sha(data), 'bytes': len(data)}:
            raise ValueError('Workbench artifact changed since build')
        artifacts[path] = data

    # Recheck all checkouts after reading, before writing a frozen artifact.
    for name, root in roots.items():
        if git(root, 'status', '--porcelain', '-z') or git(root, 'rev-parse', 'HEAD').decode().strip() != entries[name]['commit']:
            raise ValueError('Source changed during packaging: ' + name)
    output.mkdir(parents=True)
    for name, entry in entries.items():
        folder = output / name
        folder.mkdir()
        (folder / 'changes.patch').write_bytes(entry.pop('_patch'))
        for path, data in entry.pop('_blobs').items():
            target = folder / 'snapshot' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    for path, data in artifacts.items():
        target = output / 'workbench-build' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {
        'schema': 1, 'purpose': 'local-integration-review', 'production_ready': False,
        'components': entries, 'workbench_build': {path: {'sha256': sha(data), 'bytes': len(data)} for path, data in artifacts.items()},
        'central_schema_order': ['central/snapshot/scripts/distribution_control_schema.sql',
                                 'central/snapshot/scripts/distribution_scheduling_schema.sql',
                                 'central/snapshot/scripts/distribution_publication_schema.sql'],
        'native_schema_dependencies': {
            'seo': 'Original native schema and reviewed media migration before results schema',
            'geo': 'Original GEO schema and reviewed assets migration before results schema'},
        'required_before_enable': ['Integrate native routes/models and migrations on the authoritative production baseline',
                                  'Enable the reviewed SEO scheduler on the integrated deployment and verify worker recovery there',
                                  'Verify the existing GEO monitor worker is enabled and running on the integrated deployment',
                                  'Accept stable account identity, real editor/upload/readback using an authorized test account',
                                  'Verify actual human publication and public artwork, then official versioned deployment'],
        'sem_ai_takeover': False, 'automatic_final_submit': False,
        'notes': 'Component patches require their own exact bases. Snapshots are for review, not whole-tree replacement. '
                 'No SQL is executed. Git blobs may use LF; worktree hashes also record the bytes used by the workbench build.',
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (output / 'README.txt').write_text(
        'Local review bundle only. Read manifest.json and central/snapshot/docs/DISTRIBUTION_MONITOR_HANDOFF_20261011.md.\n'
        'Do not overlay full component checkouts or apply changes.patch to a different base.\n'
        'Production integration/migrations, real channel acceptance and deployed worker verification are still required.\n', encoding='utf-8')
    archive = output / 'distribution-review.zip'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob('*')):
            if path.is_file() and path != archive:
                bundle.write(path, path.relative_to(output).as_posix())
    print(json.dumps({'output': str(output), 'archive': str(archive), 'sha256': sha(archive.read_bytes()),
                      'commits': {name: entry['commit'] for name, entry in entries.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
