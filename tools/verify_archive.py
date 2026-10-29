"""Verify a freshly extracted standalone kit against its sealed file manifest."""
from pathlib import Path
import argparse
import hashlib
import json
import os

def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();root=a.root.resolve()
    manifest=json.loads((root/'package-manifest.json').read_text(encoding='utf-8'))
    total=0;stored=0;inodes=set();records={r['path']:r for r in manifest['records']}
    for record in manifest['records']:
        file=root/record['path']
        if not file.resolve().is_relative_to(root):raise ValueError('Manifest path escapes package')
        data=file.read_bytes()
        if len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256']:
            raise RuntimeError('Manifest mismatch: '+record['path'])
        total+=len(data)
        stat=file.stat();identity=(stat.st_dev,stat.st_ino)
        if identity not in inodes:stored+=len(data);inodes.add(identity)
        if 'hardlinkTo' in record:
            target=root/record['hardlinkTo']
            if record['hardlinkTo'] not in records or not target.resolve().is_relative_to(root):raise RuntimeError('Invalid hardlink target')
            if not os.path.samefile(file,target):raise RuntimeError('Archive lost library hardlink: '+record['path'])
    if total!=manifest['payloadBytes']:raise RuntimeError('Payload size mismatch')
    if 'storedPayloadBytes' in manifest and stored!=manifest['storedPayloadBytes']:raise RuntimeError('Stored payload size mismatch')
    links=root/'runtime-template-links.json'
    if links.exists():
        mapping=json.loads(links.read_text(encoding='utf-8'))
        if mapping.get('schema')!='niagara-runtime-template-links/1':raise RuntimeError('Invalid runtime template links')
        for link in mapping['files']:
            source=(root/link['source']).resolve();target=(root/'runtime-template'/link['path']).resolve()
            if not source.is_relative_to(root) or not target.is_relative_to(root/'runtime-template'):raise RuntimeError('Runtime link escapes package')
            if target.exists():raise RuntimeError('Runtime link unexpectedly duplicated')
            data=source.read_bytes()
            if len(data)!=link['bytes'] or hashlib.sha256(data).hexdigest()!=link['sha256']:raise RuntimeError('Runtime link integrity mismatch')
    if manifest['platform']=='Linux':
        for name in ['niagara-cli','backend/Engine/Binaries/Linux/UnrealEditor-Cmd','backend/Engine/Binaries/Linux/UnrealPak']:
            if not os.access(root/name,os.X_OK):raise RuntimeError('Lost executable permission: '+name)
        for file in (root/'runtime-template').glob('**/NiagaraStandalone-Linux-Shipping'):
            if not os.access(file,os.X_OK):raise RuntimeError('Runtime lost executable permission')
    print(json.dumps({'ok':True,'records':len(manifest['records']),'payloadBytes':total,
                      'storedPayloadBytes':stored,'hardlinkedFiles':manifest.get('hardlinkedFiles',0),'platform':manifest['platform']}))

if __name__=='__main__':main()
