"""Build a clean local research distribution without journals, credentials or models."""
from pathlib import Path
import hashlib
import zipfile

ROOT = Path(__file__).resolve().parent
ROOT_FILES = (
    'LICENSE', 'THIRD_PARTY.md', 'README.md', 'START_HERE.txt', '.env.example',
    'START_WINDOWS.bat', 'INSTALL_ML.bat', 'DIAGNOSE_WINDOWS.bat',
    'run.py', 'run_local.sh', 'diagnose.py', 'requirements.txt', 'requirements-core.txt',
    'requirements-ml.txt', 'requirements-dev.txt', 'pytest.ini', 'build_local_package.py',
    'Dockerfile', 'compose.yaml', '.dockerignore', '.gitignore',
)


def build():
    paths = [ROOT / name for name in ROOT_FILES]
    for folder, patterns in {'backend': ['*.py'], 'frontend': ['*.js', '*.html', '*.css', '*.svg'],
                             'docs': ['*.md'], 'samples': ['*.md'], 'tests': ['*.py']}.items():
        for pattern in patterns: paths.extend((ROOT / folder).glob(pattern))
    paths = sorted(set(paths))
    for path in paths:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
            raise ValueError(f'Unsafe or missing package file: {path.name}')
    output = ROOT / 'dist'; output.mkdir(exist_ok=True)
    target = output / 'IndiaQuant-Local-2.1.zip'
    hashes = []
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            name = path.relative_to(ROOT).as_posix(); data = path.read_bytes()
            archive.writestr('india_quant_platform/' + name, data)
            hashes.append(hashlib.sha256(data).hexdigest() + '  ' + name)
        archive.writestr('india_quant_platform/SHA256SUMS.txt', '\n'.join(hashes) + '\n')
    print(f'Created {target} ({len(paths)} files plus checksums)')
    print('No .env, data directory, virtual environment, customer records or fitted model files included.')
    return target


if __name__ == '__main__': build()
