"""Create/verify an exact working-tree build-input tar without changing Git state."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

INPUTS = ('engine', 'gfootball', 'third_party', 'setup.py', 'pyproject.toml', 'MANIFEST.in', 'README.md', 'LICENSE')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def manifest(root):
    names = subprocess.check_output(['git', 'ls-files', '-co', '--exclude-standard', '-z', '--', *INPUTS], cwd=root)
    selected={name for name in names.decode().strip('\0').split('\0') if name and (root/name).is_file()}
    # CMake fingerprints actual resource files, including ignored runtime inputs.
    for prefix in ('engine/data','engine/fonts','third_party/fonts'):
        for path in (root/prefix).rglob('*'):
            if path.is_file(): selected.add(str(path.relative_to(root)))
    return {name:sha(root/name) for name in sorted(selected)}



def main():
    mode, root, destination, receipt = sys.argv[1:]
    root, destination, receipt = map(Path, (root, destination, receipt))
    current = manifest(root)
    if mode == 'create':
        if destination.exists() or receipt.exists():
            raise ValueError('Snapshot destinations must be new')
        with tarfile.open(destination, 'w') as archive:
            for name in current:
                archive.add(root / name, arcname=name, recursive=False)
        if current != manifest(root):
            raise ValueError('Build inputs changed during snapshot')
        receipt.write_text(json.dumps(dict(kind='exact_current_worktree_not_committed_HEAD', inputs=current,
                                          archive_sha256=sha(destination)), indent=2) + '\n')
    elif mode == 'verify':
        expected = json.loads(receipt.read_text())['inputs']
        if current != expected or any(sha(destination / name) != digest for name, digest in expected.items()):
            raise ValueError('Current/exported build inputs differ from exact snapshot')
    else:
        raise ValueError('Unknown snapshot mode')
    print(json.dumps(dict(passed=True, files=len(current), mode=mode)))


if __name__ == '__main__':
    main()
