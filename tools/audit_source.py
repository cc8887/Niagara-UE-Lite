"""Reject binaries, archives, local absolute paths and credential-like text in Git changes."""
import argparse,json,re,subprocess
from pathlib import Path

BINARY_SUFFIXES={'.exe','.dll','.so','.a','.lib','.o','.obj','.pdb','.debug','.sym','.zip','.gz','.tar','.tgz','.7z','.rar','.uasset','.umap','.uexp','.ubulk','.pak','.bin','.ucas','.utoc'}
LOCAL_PATH=re.compile(r'(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/])|/(?:opt|mnt|home|Users)/')
SECRET=re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{25,}|AKIA[A-Z0-9]{16}|sk-proj-[A-Za-z0-9_-]{25,})\b')


def git(*args):return subprocess.check_output(['git',*args])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--staged',action='store_true');a=p.parse_args()
    root=Path(git('rev-parse','--show-toplevel').decode().strip())
    names=set(git('diff',*(['--cached'] if a.staged else []),'--name-only','--diff-filter=ACMR','-z').decode().split('\0'))
    if not a.staged:names.update(git('ls-files','--others','--exclude-standard','-z').decode().split('\0'))
    names.discard('');issues=[];total=0
    for name in sorted(names):
        data=git('show',':'+name) if a.staged else (root/name).read_bytes();total+=len(data)
        if Path(name).suffix.lower() in BINARY_SUFFIXES or '.so.' in name or data.startswith((b'MZ',b'\x7fELF',b'PK\x03\x04',b'\x1f\x8b')):
            issues.append({'path':name,'issue':'binary/archive/native asset'});continue
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:issues.append({'path':name,'issue':'non-text bytes'});continue
        for number,line in enumerate(text.splitlines(),1):
            if LOCAL_PATH.search(line):issues.append({'path':name,'line':number,'issue':'absolute local path'})
            if SECRET.search(line):issues.append({'path':name,'line':number,'issue':'credential-like text; value withheld'})
    print(json.dumps({'ok':not issues,'files':len(names),'bytes':total,'issues':issues},indent=2))
    if issues:raise SystemExit(1)


if __name__=='__main__':main()
