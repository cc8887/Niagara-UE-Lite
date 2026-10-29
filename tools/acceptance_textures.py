"""Native texture import -> material -> Niagara renderer binding -> save/reload."""
from pathlib import Path
import argparse
import json
import math
import os
import struct
import subprocess
import sys
import uuid
import zlib

def png(path):
    size=64;raw=bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            dx,dy=(x-31.5)/31.5,(y-31.5)/31.5
            alpha=int(255*max(0,1-abs(dx)-abs(dy))**0.7)
            raw.extend((30,170,255,alpha))
    def chunk(t,d):return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',size,size,8,6,0,0,0))+
                     chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b''))

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--workspace',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    root=a.root.resolve();script=root/('scripts' if (root/'scripts').exists() else 'tools')/'niagara_cli.py'
    python=sys.executable
    if (root/'backend').exists():python=str(root/('backend/Engine/Binaries/ThirdParty/Python3/Win64/python.exe' if os.name=='nt' else 'backend/Engine/Binaries/ThirdParty/Python3/Linux/bin/python3'))
    prefix=[python,str(script),'--workspace',str(a.workspace),'--timeout','1800'];cases=[]
    def run(name,*args):
        proc=subprocess.run(prefix+list(args),capture_output=True,text=True,encoding='utf-8',errors='replace')
        (a.out/(name+'.json')).write_text(proc.stdout,encoding='utf-8');result=json.loads(proc.stdout)
        if proc.returncode or not result['ok']:raise RuntimeError(name+': '+proc.stdout[-2500:])
        cases.append({'name':name,'ok':True});return result
    source=a.out/'diamond.png';png(source)
    base='/Game/TextureAcceptance/Run_'+uuid.uuid4().hex[:8];tex=base+'/T_Diamond';material=base+'/M_Diamond';system=base+'/NS_Diamond'
    run('import-image','import-texture','--file',str(source),'--asset',tex)
    src=a.workspace/'Content'/Path(tex.removeprefix('/Game/')).with_suffix('.uasset')
    native=base+'/Native/T_Diamond';run('import-native','import-texture','--file',str(src),'--asset',native)
    run('create-material','create-material','--texture',native,'--asset',material)
    run('create-system','create','--asset',system,'--recipe',str(root/'examples/fountain.json'))
    recipe=a.out/'bind.json';recipe.write_text(json.dumps({'schema':'ue-niagara-recipe/1','operations':[
        {'op':'renderer-properties','emitter':'Fountain','renderer':0,'properties':{'Material':material+'.M_Diamond'}}]}))
    run('bind-material','edit','--asset',system,'--recipe',str(recipe))
    reloaded=run('reload','read','--asset',system)
    renderer=json.loads(reloaded['snapshot']['emitters'][0]['renderers'][0]['propertyValues'])
    if material not in json.dumps(renderer):raise AssertionError('Native material binding was not saved')
    report={'ok':True,'cases':cases,'system':system,'texture':native,'material':material,'visualValidation':False}
    (a.out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

if __name__=='__main__':main()
