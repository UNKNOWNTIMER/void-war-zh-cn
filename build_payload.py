"""Build a publication-safe payload from local verified source/package trees."""
import argparse
import json
from pathlib import Path
import shutil
from payload_format import ORIGINAL_SHA, ORIGINAL_FILES, PAYLOAD_FILES, build_delta, sha

def build(original, package, output, version):
    original, package, output = map(Path, (original, package, output))
    assert sha(original / 'data.win') == ORIGINAL_SHA, 'Unverified original game version'
    output.mkdir(parents=True, exist_ok=True)
    allowed = {'payload.json', 'engine.delta.gz', *PAYLOAD_FILES}
    for path in output.rglob('*'):
        assert not path.is_symlink(), 'Payload output must not contain links'
        if path.is_file(): assert path.relative_to(output).as_posix() in allowed, 'Unexpected payload file'
    delta = build_delta(original / 'data.win', package / 'data.win', output / 'engine.delta.gz')
    # A nearly complete engine is never a permissible public patch.
    assert delta['replacement_bytes'] < delta['data_size'] // 10
    assert delta['replacement_bytes'] < 8 * 1024 * 1024
    files = []
    for name in PAYLOAD_FILES:
        target = output / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(package / name, target)
        files.append({'path': name, 'sha256': sha(target), 'bytes': target.stat().st_size})
    compat_path = Path(__file__).parent / 'compatibility' / 'c35.json'
    compatibility = json.loads(compat_path.read_text('utf8')) if compat_path.exists() else {}
    manifest = {'schema': 1, 'game': 'Void War', 'game_version': '1.5.2b', 'steam_build_id': '25669267',
                'release_version': version, 'language_id': 3,
                'original_files': [{'path': p, 'sha256': sha(original / p)} for p in ORIGINAL_FILES],
                'delta': delta, 'delta_sha256': sha(output / 'engine.delta.gz'), 'files': files,
                'compatible_previous': compatibility,
                'license': 'Font: SIL Open Font License 1.1; see licenses/NotoSerif-OFL.txt',
                'privacy': 'No full game engine, original CSV, save files, or developer paths are included.'}
    (output / 'payload.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8')
    public = [p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()]
    assert set(public) == allowed
    report = {'status': 'PASS', 'public_files': sorted(public), 'original_engine_included': False,
              'original_csv_included': False, 'save_files_included': False, 'delta': delta,
              'payload_bytes': sum(p.stat().st_size for p in output.rglob('*') if p.is_file())}
    return report

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--original-dir', type=Path, required=True)
    p.add_argument('--package-dir', type=Path, required=True)
    p.add_argument('--output', type=Path, default=Path(__file__).parent / 'payload')
    p.add_argument('--version', default='2026.10.10')
    a = p.parse_args()
    print(json.dumps(build(a.original_dir, a.package_dir, a.output, a.version), ensure_ascii=False, indent=2))
