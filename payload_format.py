"""Small replacement-only engine delta. Never stores original engine bytes."""
from __future__ import annotations
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import struct

MAGIC = b'VWZHDF1\n'
ORIGINAL_SHA = '1d8bb23910251b7bc50f1013efbec18ce0cf030894e7d2de50c4bdadfb9f8db9'
SUPPORTED_ORIGINALS = {
    ORIGINAL_SHA: {'game_version': '1.5.2b', 'steam_build_id': '25669267'},
    '336d857f6ca0b7a4d847c15094668ca8488ec5949eb0abf0439da1b331e5ec2f':
        {'game_version': '1.5.3 beta', 'steam_build_id': '25749411'},
}
ORIGINAL_FILES = ('data.win', 'lang/functionText_zh-Hans', 'lang/UIText_zh-Hans', 'lang/encounterText_zh-Hans')
EXTRA_FILES = ('NotoSerifSC-Black.otf', 'licenses/NotoSerif-OFL.txt')
PAYLOAD_FILES = ORIGINAL_FILES[1:] + EXTRA_FILES

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def byte_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def build_delta(original: Path, target: Path, output: Path) -> dict:
    a, b = original.read_bytes(), target.read_bytes()
    if len(a) != len(b):
        raise ValueError('Engine delta requires identical file lengths')
    ranges = []
    start = None
    for block in range(0, len(a), 65536):
        end = min(block + 65536, len(a))
        if a[block:end] == b[block:end]:
            if start is not None:
                ranges.append((start, block)); start = None
            continue
        for pos in range(block, end):
            if a[pos] != b[pos]:
                if start is None: start = pos
            elif start is not None:
                ranges.append((start, pos)); start = None
    if start is not None: ranges.append((start, len(a)))
    header = {'format': 1, 'source_sha256': byte_sha(a), 'target_sha256': byte_sha(b),
              'data_size': len(a), 'segments': len(ranges),
              'replacement_bytes': sum(z - x for x, z in ranges)}
    encoded = json.dumps(header, sort_keys=True, separators=(',', ':')).encode('ascii')
    with output.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=9) as f:
            f.write(MAGIC + struct.pack('<I', len(encoded)) + encoded)
            for x, z in ranges:
                f.write(struct.pack('<QI', x, z - x))
                f.write(hashlib.sha256(a[x:z]).digest())
                f.write(b[x:z])
    return header

def read_header(f) -> dict:
    if f.read(8) != MAGIC: raise ValueError('Invalid delta signature')
    size = struct.unpack('<I', f.read(4))[0]
    if not 1 <= size <= 4096: raise ValueError('Invalid delta header')
    h = json.loads(f.read(size))
    if h['format'] != 1 or not 0 <= h['segments'] <= 1000000:
        raise ValueError('Unsupported delta')
    return h

def apply_delta(original: Path, delta: Path, target: Path, expected: dict) -> None:
    if sha(original) != expected['source_sha256']:
        raise ValueError('Original engine SHA mismatch')
    with gzip.open(delta, 'rb') as f:
        header = read_header(f)
        if header != expected or original.stat().st_size != header['data_size']:
            raise ValueError('Delta metadata mismatch')
        shutil.copyfile(original, target)
        end = 0
        replacement_bytes = 0
        with target.open('r+b') as out:
            for _ in range(header['segments']):
                record = f.read(12)
                if len(record) != 12: raise ValueError('Truncated delta')
                offset, size = struct.unpack('<QI', record)
                digest, new = f.read(32), f.read(size)
                if not size or offset < end or offset + size > header['data_size'] or len(new) != size:
                    raise ValueError('Invalid replacement range')
                out.seek(offset)
                if hashlib.sha256(out.read(size)).digest() != digest:
                    raise ValueError('Replacement source mismatch')
                out.seek(offset); out.write(new)
                end = offset + size; replacement_bytes += size
            out.flush()
        if f.read(1) or replacement_bytes != header['replacement_bytes']:
            raise ValueError('Delta trailing bytes or count mismatch')
    if sha(target) != header['target_sha256']:
        raise ValueError('Patched engine SHA mismatch')
