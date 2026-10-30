"""Recompile modified UE commandlet-profile unity objects into isolated Linux libraries.

Requires matching UE 5.8.1 sources and complete original UBT objects/responses.
Does not modify reference sources, objects, libraries or module manifests.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from functools import lru_cache
from patch_ue58_editor_backend import transform


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


@lru_cache(maxsize=4)
def dependency_index(engine):
    result={}
    for root in (engine/'Binaries',engine/'Plugins'):
        for path in root.rglob('*.so*'):
            if path.is_file():result.setdefault(path.name,[]).append(path)
    return result


def final_dependency_flags(engine,reference,omit=()):
    dynamic=subprocess.check_output(['readelf','-dW',str(reference)],text=True)
    names=re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic)
    flags=['-Wl,--allow-shlib-undefined','-Wl,--no-as-needed']
    system={'libpthread.so.0','libstdc++.so.6','librt.so.1','libm.so.6',
            'libc.so.6','ld-linux-x86-64.so.2','libgcc_s.so.1','libdl.so.2'}
    for name in names:
        if name in system or name in omit:continue
        paths=dependency_index(engine).get(name,[])
        if not paths:paths=list((engine/'Source/ThirdParty').rglob(name))
        paths=[p for p in paths if p.is_file()]
        if not paths:raise ValueError('Cannot resolve original final dependency '+name)
        # Prefer the actual engine binary directory over copied staging files.
        paths.sort(key=lambda p:(p.parent!=engine/'Binaries/Linux',len(str(p))))
        flags.append('"'+str(paths[0])+'"')
    flags.append('-Wl,--as-needed')
    return flags


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine',required=True,type=Path)
    p.add_argument('--work',required=True,type=Path)
    p.add_argument('--timeout',type=int,default=1800)
    p.add_argument('--modules',nargs='+',choices=['UnrealEd','LevelEditor','MeshUtilities','Blutility'],
                   default=['UnrealEd','LevelEditor','MeshUtilities','Blutility'])
    a=p.parse_args();engine=a.engine.resolve();work=a.work.resolve()
    if sys.platform!='linux':p.error('Linux only')
    if work.exists() or work.is_relative_to(engine) or engine.is_relative_to(work):
        p.error('New output directory outside Engine required')
    v=json.loads((engine/'Build/Build.version').read_text())
    if [v[k] for k in ('MajorVersion','MinorVersion','PatchVersion')]!=[5,8,1]:p.error('UE 5.8.1 required')
    changes=transform(engine)
    work.mkdir(parents=True);report={'schema':'niagara-editor-backend-linux-rebuild/1','ok':False,'modules':[]}
    module_id=sha(engine/'Binaries/Linux/UnrealEditor.modules')
    for relative,text in changes.items():
        path=work/'source'/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
    targets={'UnrealEd':'Source/Editor/UnrealEd/Private/EditorEngine.cpp',
             'LevelEditor':'Source/Editor/LevelEditor/Private/LevelEditor.cpp',
             'MeshUtilities':'Source/Developer/MeshUtilities/Private/MeshUtilities.cpp',
             'Blutility':'Source/Editor/Blutility/Private/EditorUtilitySubsystem.cpp'}
    for module,relative in targets.items():
        if module not in a.modules:continue
        start=time.monotonic();original=engine/'Intermediate/Build/Linux/x64/UnrealEditor/Development'/module
        include='#include "'+str(Path(relative).relative_to('Source'))+'"'
        units=[u for u in original.glob('Module.*.cpp') if include in u.read_text()]
        if len(units)!=1:raise ValueError('Expected exactly one original unity unit: '+module)
        unit=units[0];dest=work/module;dest.mkdir()
        unity=dest/unit.name;unity.write_text(unit.read_text().replace(include,'#include "'+str(work/'source'/relative)+'"'))
        obj=dest/(unit.name+'.o');rsp=Path(str(unit)+'.o.rsp');lines=rsp.read_text().splitlines()
        counts={'source':0,'output':0,'dependency':0}
        result=[]
        for line in lines:
            if line.startswith('-o '):line='-o "'+str(obj)+'"';counts['output']+=1
            elif line.startswith('-MD -MF'):
                line='-MD -MF"'+str(dest/'dependencies.d')+'"';counts['dependency']+=1
            elif len(shlex.split(line))==1 and not line.startswith(('-','@')) and (engine/'Source'/shlex.split(line)[0]).resolve()==unit:
                line='"'+str(unity)+'"';counts['source']+=1
            result.append(line)
        if counts!={'source':1,'output':1,'dependency':1}:raise ValueError('Unknown compile response layout')
        if module=='MeshUtilities':result.insert(0,'-DNIAGARA_LITE_NO_PERSONA_TOOLBAR=1')
        compile_rsp=dest/'compile.rsp';compile_rsp.write_text('\n'.join(result)+'\n')
        sysroot=re.search(r'^--sysroot="([^"]+)"$',rsp.read_text(),re.M).group(1)
        compiler=Path(sysroot)/'bin/clang++'
        def run(cmd,log):
            with (dest/log).open('w') as f:
                r=subprocess.run(cmd,cwd=engine/'Source',stdout=f,stderr=subprocess.STDOUT,timeout=a.timeout)
            if r.returncode:raise RuntimeError(module+' '+log+' failed; inspect isolated log')
        print(module+': compile',flush=True);run([str(compiler),'@'+str(compile_rsp)],'compile.log')
        objects=original/('libUnrealEditor-'+module+'.so.rsp')
        original_obj=Path(str(unit)+'.o')
        object_lines=[];replaced=0
        for line in objects.read_text().splitlines():
            tokens=shlex.split(line)
            if len(tokens)==1 and not tokens[0].startswith('-') and (engine/'Source'/tokens[0]).resolve()==original_obj:
                line='"'+str(obj)+'"';replaced+=1
            object_lines.append(line)
        if replaced!=1:raise ValueError('Original object reference changed')
        object_rsp=dest/'objects.rsp';object_rsp.write_text('\n'.join(object_lines)+'\n')
        link_original=original/('libUnrealEditor-'+module+'.so.link.rsp')
        output=work/'overrides/backend/Engine/Binaries/Linux'/('libUnrealEditor-'+module+'.so')
        output.parent.mkdir(parents=True,exist_ok=True);links=[];nc={'o':0,'objects':0}
        for line in link_original.read_text().splitlines():
            if line.startswith('-o '):line='-o "'+str(output)+'"';nc['o']+=1
            elif line.startswith('-Wl,@'):
                if (engine/'Source'/shlex.split(line)[0][5:]).resolve()!=objects:raise ValueError('Unexpected nested link response')
                line='-Wl,@"'+str(object_rsp)+'"';nc['objects']+=1
            links.append(line)
        if nc!={'o':1,'objects':1}:raise ValueError('Unknown linker response layout')
        # UBT's later FixDependencies step supplies engine-library imports that
        # are absent from the first-pass .link.rsp. Preserve that final linkage
        # rather than distributing an intermediate library with unresolved UE
        # symbols and missing DT_NEEDED entries.
        reference=engine/'Binaries/Linux'/output.name
        omitted=['libUnrealEditor-Persona.so'] if module=='MeshUtilities' else []
        links.extend(final_dependency_flags(engine,reference,omitted))
        link_rsp=dest/'link.rsp';link_rsp.write_text('\n'.join(links)+'\n')
        print(module+': link',flush=True);run([str(compiler),'@'+str(link_rsp)],'link.log')
        dynamic=subprocess.check_output(['readelf','-dW',str(output)],text=True)
        needed=re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic)
        symbols=subprocess.check_output(['readelf','--dyn-syms','-W',str(output)],text=True)
        if module=='MeshUtilities' and (any('Persona' in n for n in needed) or
                any(' UND ' in row and 'Persona' in row for row in symbols.splitlines())):
            raise RuntimeError('Persona dependency survived')
        report['modules'].append({'module':module,'output':output.relative_to(work).as_posix(),
            'sha256':sha(output),'bytes':output.stat().st_size,'needed':needed,
            'seconds':round(time.monotonic()-start,3),'unitySource':unit.relative_to(engine).as_posix(),
            'originalResponseSha256':sha(rsp),'patchedSourceSha256':sha(work/'source'/relative)})
        (work/'rebuild-progress.json').write_text(json.dumps(report,indent=2))
    if sha(engine/'Binaries/Linux/UnrealEditor.modules')!=module_id:raise RuntimeError('Reference metadata changed')
    report.update(ok=True,referenceEngineOutputsModified=False,referenceModulesSha256=module_id,qualified=False)
    (work/'rebuild.json').write_text(json.dumps(report,indent=2));print('Native rebuild complete; qualification pending',flush=True)


if __name__=='__main__':main()
