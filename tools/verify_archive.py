"""Verify a freshly extracted standalone kit against its sealed file manifest."""
from pathlib import Path
import argparse
import hashlib
import json
import os

def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();root=a.root.resolve()
    manifest=json.loads((root/'package-manifest.json').read_text(encoding='utf-8'))
    total=0
    for record in manifest['records']:
        file=root/record['path']
        if not file.resolve().is_relative_to(root):raise ValueError('Manifest path escapes package')
        data=file.read_bytes()
        if len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256']:
            raise RuntimeError('Manifest mismatch: '+record['path'])
        total+=len(data)
    if total!=manifest['payloadBytes']:raise RuntimeError('Payload size mismatch')
    if manifest['platform']=='Linux':
        for name in ['niagara-cli','backend/Engine/Binaries/Linux/UnrealEditor-Cmd','backend/Engine/Binaries/Linux/UnrealPak']:
            if not os.access(root/name,os.X_OK):raise RuntimeError('Lost executable permission: '+name)
        for file in (root/'runtime-template').glob('**/NiagaraStandalone-Linux-Shipping'):
            if not os.access(file,os.X_OK):raise RuntimeError('Runtime lost executable permission')
    print(json.dumps({'ok':True,'records':len(manifest['records']),'payloadBytes':total,'platform':manifest['platform']}))

if __name__=='__main__':main()
