"""Explicit local-only inputs for the audited 1.5.2b -> 1.5.3 beta port."""
from pathlib import Path
import argparse,hashlib
def inputs():
    root=Path(__file__).resolve().parents[1];beta=root/'beta153'
    p=argparse.ArgumentParser()
    p.add_argument('--stable-original',type=Path,default=root/'backup/data.win')
    p.add_argument('--stable-target',type=Path,default=root/'package/data.win')
    p.add_argument('--beta-original',type=Path,default=beta/'original/data.win')
    p.add_argument('--output',type=Path,default=beta/'package/data.win')
    p.add_argument('--audit-dir',type=Path,default=beta/'audit')
    a=p.parse_args()
    for path,digest in [(a.stable_original,'1d8bb23910251b7bc50f1013efbec18ce0cf030894e7d2de50c4bdadfb9f8db9'),
                        (a.stable_target,'f9a3f8471d84605a286b0245bd48af609ece4bb6cbde90b2804f681fbafb078a'),
                        (a.beta_original,'336d857f6ca0b7a4d847c15094668ca8488ec5949eb0abf0439da1b331e5ec2f')]:
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,'Input resource version is not verified'
    assert a.output.resolve() not in {x.resolve() for x in [a.stable_original,a.stable_target,a.beta_original]},'Output must be a separate working copy'
    a.output.parent.mkdir(parents=True,exist_ok=True);a.audit_dir.mkdir(parents=True,exist_ok=True)
    return a
