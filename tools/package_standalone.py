"""Stage and seal a prebuilt Niagara standalone kit. Developer-only tool."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile
from package_support import copy,tree,SOURCE_PREFIXES,SKIP

ROOT=Path(__file__).resolve().parents[1]
WIN=sys.platform=='win32'
PLATFORM='Windows' if WIN else 'Linux'
BIN='Win64' if WIN else 'Linux'
NAME='Niagara-UE-Lite-Standalone-UE5.8.1-'+PLATFORM+'-x86_64'

def stage(dest,engine,project,runtime,resume):
    if dest.exists() and not resume:raise ValueError('Stage exists; overwrite refused')
    version=json.loads((engine/'Build/Build.version').read_text())
    if [version[k] for k in ('MajorVersion','MinorVersion','PatchVersion')]!=[5,8,1]:raise ValueError('Expected UE 5.8.1')
    for p in sorted((engine/'Binaries'/BIN).rglob('*')):
        if not p.is_file() or p.suffix in SKIP:continue
        wanted=p.suffix.lower() in ('.dll','.modules','.version','.ini','.json') if WIN else ('.so' in p.name or p.suffix in ('.modules','.version','.ini','.json'))
        wanted|=p.name in (('UnrealEditor-Cmd.exe','ShaderCompileWorker.exe','UnrealPak.exe') if WIN else ('UnrealEditor-Cmd','ShaderCompileWorker','UnrealPak'))
        if wanted:copy(p,dest/'backend/Engine'/p.relative_to(engine))
    for folder in ('Config','Shaders'):
        tree(engine/folder,dest/'backend/Engine'/folder)
    for p in sorted((engine/'Content').rglob('*')):
        if not p.is_file() or p.suffix in SKIP:continue
        rel=p.relative_to(engine/'Content')
        if rel.parts[0]=='Localization' and not (p.suffix=='.locmeta' or p.suffix=='.locres' and 'en' in rel.parts):continue
        copy(p,dest/'backend/Engine/Content'/rel)
    for name in ('Build/Build.version','Build/Windows/Resources/Default.ico'):
        if (engine/name).is_file():copy(engine/name,dest/'backend/Engine'/name)
    names=('ICU','ShaderConductor','Python3','Vulkan','OpenSSL','Intel','FreeImage','nvTextureTools','libsndfile','FBX','OpenAL','DirectX','DbgHelp','Windows','WinPixEventRuntime','Ogg','Vorbis')
    for name in names:
        source=engine/'Binaries/ThirdParty'/name
        if not source.exists():continue
        if WIN:
            for p in source.rglob('*'):
                if not p.is_file() or p.suffix in SKIP or any(x in p.parts for x in ('Linux','Mac','include','__pycache__')):continue
                if p.suffix.lower() in ('.a','.lib','.h','.cpp','.c'):continue
                copy(p,dest/'backend/Engine'/p.relative_to(engine))
        else:
            for folder in source.rglob('Linux'):
                if folder.is_dir():tree(folder,dest/'backend/Engine'/folder.relative_to(engine))
    if WIN:
        # Native editor dependency; browser resources/helpers are not needed by the CLI.
        for p in (engine/'Binaries/ThirdParty/CEF3').rglob('*'):
            if p.is_file() and 'Win64' in p.parts and (p.suffix.lower()=='.dll' or 'license' in p.name.lower()):
                copy(p,dest/'backend/Engine'/p.relative_to(engine))
    else:
        linked=subprocess.check_output(['ldd',str(engine/'Binaries/Linux/UnrealEditor-Cmd')],text=True)
        cef=next(Path(x.split('=>')[1].split(' (')[0].strip()) for x in linked.splitlines() if 'libcef.so =>' in x)
        copy(cef,dest/'backend/Engine'/cef.relative_to(engine))
        for p in cef.parent.iterdir():
            if p.is_file() and 'license' in p.name.lower():copy(p,dest/'backend/Engine'/p.relative_to(engine))
        if shutil.which('strip'):subprocess.run(['strip','--strip-debug',str(dest/'backend/Engine'/cef.relative_to(engine))],check=True)
    for name in ('Niagara','PythonScriptPlugin','EditorScriptingUtilities','ContentBrowserFileDataSource'):
        descriptor=next(engine.glob('Plugins/**/'+name+'.uplugin'));plugin=descriptor.parent
        for folder in ('Binaries/'+BIN,'Config','Content','Resources','Shaders'):
            if (plugin/folder).is_dir():tree(plugin/folder,dest/'backend/Engine'/plugin.relative_to(engine)/folder)
        copy(descriptor,dest/'backend/Engine'/descriptor.relative_to(engine))
    config=engine/'Platforms'/PLATFORM/'Config'
    if config.is_dir():tree(config,dest/'backend/Engine'/config.relative_to(engine))
    copy(project/'NiagaraStandalone.uproject',dest/'Project/NiagaraStandalone.uproject')
    tree(project/'Config',dest/'Project/Config')
    for p in (project/'Binaries'/BIN).iterdir():
        if p.is_file() and (p.suffix=='.modules' or p.name.startswith(('UnrealEditor-NiagaraStandalone','libUnrealEditor-NiagaraStandalone')) and p.suffix in ('.dll','.so')):
            copy(p,dest/'Project/Binaries'/BIN/p.name)
    # Only the intentionally authored demo/map, never arbitrary workspace assets.
    for rel in ('NiagaraPreview/Preview.umap','NiagaraDemo/NS_Fountain.uasset'):
        if (project/'Content'/rel).is_file():copy(project/'Content'/rel,dest/'Project/Content'/rel)
    for p in runtime.rglob('*'):
        if p.is_file() and p.suffix not in SKIP and 'Manifest_' not in p.name and p.name not in ('Manifest_UFSFiles_Win64.txt','Manifest_NonUFSFiles_Win64.txt'):
            copy(p,dest/'runtime-template'/p.relative_to(runtime))
    for name in ('niagara_cli.py','assets_worker.py','author_preview.py','vulkan_probe.py'):
        copy(ROOT/'tools'/name,dest/'scripts'/name)
    tree(ROOT/'examples',dest/'examples');copy(ROOT/'README.md',dest/'README.md')
    tree(ROOT/'docs',dest/'docs')
    if WIN:
        launcher=os.environ.get('NIAGARA_PACKAGE_LAUNCHER')
        if launcher:copy(Path(launcher),dest/'niagara-cli.exe')
        (dest/'niagara-cli.cmd').write_text('@echo off\r\nsetlocal\r\nset "PYTHONNOUSERSITE=1"\r\nset "PYTHONHOME=%~dp0backend\\Engine\\Binaries\\ThirdParty\\Python3\\Win64"\r\n"%PYTHONHOME%\\python.exe" "%~dp0scripts\\niagara_cli.py" %*\r\nexit /b %errorlevel%\r\n')
    else:
        (dest/'niagara-cli').write_text('''#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export PYTHONNOUSERSITE=1
export PYTHONHOME="$ROOT/backend/Engine/Binaries/ThirdParty/Python3/Linux"
export LD_LIBRARY_PATH="$PYTHONHOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$PYTHONHOME/bin/python3" "$ROOT/scripts/niagara_cli.py" "$@"
''')
        (dest/'niagara-cli').chmod(0o755)
    if os.environ.get('NIAGARA_PACKAGE_SEED_DDC'):tree(Path(os.environ['NIAGARA_PACKAGE_SEED_DDC']),dest/'cache')
    files=[p.relative_to(dest).as_posix() for p in sorted(dest.rglob('*')) if p.is_file()]
    (dest.parent/(NAME+'-file-list.json')).write_text(json.dumps(files,indent=2))

def seal(dest,make_archive,private_roots):
    files=json.loads((dest.parent/(NAME+'-file-list.json')).read_text());records=[]
    needles=[s.encode(enc) for s in private_roots if len(s)>3 for enc in ('utf-8','utf-16le','utf-32le')]
    for rel in files:
        p=dest/rel;data=p.read_bytes()
        if any(n in data for n in needles):raise ValueError('Private build path remains in '+rel)
        records.append({'path':rel,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
    manifest={'schema':'ue-niagara-standalone/1','engine':'UE5.8.1','platform':PLATFORM,
              'editorInstallationRequired':False,'includesUnrealEd':True,'includesNiagaraEditor':True,
              'cppSdkRequired':False,'runtimeWithEditor':False,'payloadBytes':sum(r['bytes'] for r in records),'records':records}
    (dest/'package-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    summary={k:v for k,v in manifest.items() if k!='records'};summary['files']=len(files)+1
    if make_archive:
        archive=dest.parent/(NAME+('.zip' if WIN else '.tar.gz'))
        if archive.exists():raise ValueError('Archive exists')
        if WIN:
            with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
                for rel in files+['package-manifest.json']:z.write(dest/rel,rel)
        else:
            with tarfile.open(archive,'w:gz',compresslevel=6) as tar:
                for rel in files+['package-manifest.json']:
                    p=dest/rel;info=tar.gettarinfo(str(p),arcname=rel)
                    info.uid=info.gid=0;info.uname=info.gname='root';info.mode=0o755 if p.stat().st_mode&0o111 else 0o644
                    with p.open('rb') as stream:tar.addfile(info,stream)
        h=hashlib.sha256()
        with archive.open('rb') as stream:
            for chunk in iter(lambda:stream.read(8*1024*1024),b''):h.update(chunk)
        summary.update({'archive':archive.name,'archiveBytes':archive.stat().st_size,'sha256':h.hexdigest()})
        (archive.parent/(archive.name+'.json')).write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--stage-only',action='store_true')
    p.add_argument('--seal',action='store_true');p.add_argument('--resume-stage',action='store_true');a=p.parse_args()
    engine=Path(os.environ['NIAGARA_PACKAGE_ENGINE']).resolve();project=Path(os.environ['NIAGARA_PACKAGE_PROJECT']).resolve()
    runtime=Path(os.environ['NIAGARA_PACKAGE_RUNTIME']).resolve();output=Path(os.environ['NIAGARA_PACKAGE_DIST']).resolve()
    output.mkdir(parents=True,exist_ok=True);dest=output/NAME
    roots=[str(ROOT),str(project),str(engine)]
    roots.extend(json.loads(os.environ.get('NIAGARA_PACKAGE_PRIVATE_ROOTS','[]')))
    # Copies only: fixed-length redaction preserves PE/ELF section offsets.
    for root in roots:SOURCE_PREFIXES.extend([root,root.replace('\\','/'),root.replace('/','\\')])
    if not a.seal:stage(dest,engine,project,runtime,a.resume_stage)
    seal(dest,not a.stage_only,roots)

if __name__=='__main__':main()
