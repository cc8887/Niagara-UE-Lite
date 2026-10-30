"""Build the UE 5.8.1 commandlet service profile in an independent Windows copy.

Developer helper: requires an installed matching engine, MSVC and Windows SDK.
The original engine and project are read-only inputs. Outputs are unqualified
build products; sanitize and validate them before putting them in a package.
"""
import argparse,hashlib,json,os,re,shutil,stat,subprocess,time
from pathlib import Path
from patch_ue58_editor_backend import transform

MODULES=('UnrealEd','LevelEditor','MeshUtilities','Blutility')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine',required=True,type=Path);p.add_argument('--project',required=True,type=Path)
    p.add_argument('--work',required=True,type=Path);p.add_argument('--jobs',type=int,default=2)
    a=p.parse_args();source=a.engine.resolve();project=a.project.resolve();work=a.work.resolve()
    if os.name!='nt':p.error('Windows only')
    if work.exists() or work.is_relative_to(source) or source.is_relative_to(work):p.error('New independent output directory required')
    if work.is_relative_to(project.parent) or project.parent.is_relative_to(work):p.error('Project and work must be separate')
    if len(str(work))>40:p.error('Use a short Windows build root to avoid path limits')
    if not 1<=a.jobs<=16:p.error('jobs must be 1..16')
    v=json.loads((source/'Build/Build.version').read_text())
    if [v[k] for k in ('MajorVersion','MinorVersion','PatchVersion')]!=[5,8,1]:p.error('Matching UE 5.8.1 required')
    if project.name!='NiagaraStandalone.uproject':p.error('Expected the standalone project')
    if shutil.disk_usage(work.parent).free<40*1024**3:p.error('At least 40 GiB free build space required')
    work.mkdir(parents=True);engine=work/'Engine';start=time.monotonic()
    def tree(relative):
        src=source/relative
        if src.is_dir():
            print('copy '+relative,flush=True)
            shutil.copytree(src,engine/relative,ignore=shutil.ignore_patterns('*.pdb','*.sym','*.debug'))
    for relative in ('Source','Intermediate','Build','Config','Programs','Shaders','Platforms',
                     'Binaries/DotNET','Binaries/ThirdParty','Binaries/Win64'):tree(relative)
    excluded={'Content','Resources','Saved','Documentation','Samples','Tests','Linux','Mac','Android','IOS'}
    for current,dirs,files in os.walk(source/'Plugins'):
        dirs[:]=[d for d in dirs if d not in excluded]
        for name in files:
            src=Path(current)/name
            if src.suffix.lower() in {'.pdb','.sym','.debug','.png','.jpg','.uasset','.umap','.obj','.o'}:continue
            dest=engine/src.relative_to(source);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
    clone=work/'Project';clone.mkdir()
    shutil.copy2(project,clone/project.name)
    for folder in ('Source','Config'):shutil.copytree(project.parent/folder,clone/folder)
    changes=transform(source);rows=[]
    for relative,text in changes.items():
        dest=engine/relative;dest.chmod(dest.stat().st_mode|stat.S_IWUSR);dest.write_text(text,encoding='utf-8')
        rows.append({'path':relative,'sha256':hashlib.sha256(text.encode()).hexdigest()})
    # Match the installed assembly's default for all unmodified modules while
    # allowing just the selected editor modules to compile from source.
    ctor=re.compile(r'(public\s+\w+\s*\([^)]*ReadOnlyTargetRules[^)]*\)\s*:\s*base\s*\([^)]*\)\s*\{)')
    for root in (engine/'Source',engine/'Plugins'):
        for path in root.rglob('*.Build.cs'):
            if path.name.removesuffix('.Build.cs') in MODULES:continue
            text=path.read_text(encoding='utf-8-sig')
            text,count=ctor.subn(r'\1\n        bUsePrecompiled = true; /* NIAGARA_SELECTIVE_UBT */',text,count=1)
            if count:path.chmod(path.stat().st_mode|stat.S_IWUSR);path.write_text(text,encoding='utf-8')
    backup=work/'reference-installed-build';backup.mkdir()
    flag=engine/'Build/InstalledBuild.txt'
    if flag.exists():flag.rename(backup/flag.name)
    for path in (engine/'Intermediate/Build/BuildRules').iterdir():
        if path.name.startswith(('UE5Rules','UE5ProgramRules')):path.rename(backup/path.name)
    for module in (*MODULES,'NiagaraStandaloneEditor'):
        with (work/('build-'+module+'.log')).open('w',encoding='utf-8') as output:
            result=subprocess.run([str(engine/'Build/BatchFiles/Build.bat'),'NiagaraStandaloneEditor','Win64','Development',
                '-Project='+str(clone/project.name),'-Module='+module,'-NoUBA','-MaxParallelActions='+str(a.jobs)],
                stdout=output,stderr=subprocess.STDOUT,timeout=7200)
        if result.returncode:raise RuntimeError('Native build failed: '+module)
    outputs=[]
    for module in MODULES:
        relative='backend/Engine/Binaries/Win64/UnrealEditor-'+module+'.dll'
        src=engine/'Binaries/Win64'/('UnrealEditor-'+module+'.dll');dest=work/'overrides'/relative
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        outputs.append({'path':relative,'bytes':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
    relative='Project/Binaries/Win64/UnrealEditor-NiagaraStandaloneEditor.dll'
    dest=work/'overrides'/relative;dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(clone/'Binaries/Win64/UnrealEditor-NiagaraStandaloneEditor.dll',dest)
    outputs.append({'path':relative,'bytes':dest.stat().st_size,'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
    report={'schema':'niagara-editor-backend-windows-rebuild/1','ok':True,'qualified':False,
            'originalEngineOutputsModified':False,'profileSource':rows,'outputs':outputs,
            'wallSeconds':round(time.monotonic()-start,3)}
    (work/'rebuild.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)


if __name__=='__main__':main()
