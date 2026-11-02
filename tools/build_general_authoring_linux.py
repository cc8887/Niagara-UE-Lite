"""Rebuild NiagaraEditor exports for generic stack editing using matching UBT objects."""
import argparse,json,re,shlex,shutil,subprocess,sys,time
from pathlib import Path
from patch_ue58_general_authoring import changes
from build_editor_backend_linux import final_dependency_flags,sha


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',required=True,type=Path)
    p.add_argument('--work',required=True,type=Path);p.add_argument('--stack-identity',action='store_true');a=p.parse_args();engine=a.engine.resolve();work=a.work.resolve()
    if sys.platform!='linux':p.error('Linux only')
    if work.exists() or work.is_relative_to(engine) or engine.is_relative_to(work):p.error('New independent work directory required')
    version=json.loads((engine/'Build/Build.version').read_text())
    if [version[k] for k in ['MajorVersion','MinorVersion','PatchVersion']]!=[5,8,1]:p.error('Matching UE 5.8.1 required')
    work.mkdir(parents=True);start=time.monotonic();headers=changes(engine)
    prefix='Plugins/FX/Niagara/Source/NiagaraEditor/'
    source=engine/'Plugins/FX/Niagara/Source/NiagaraEditor'
    overlay=work/'NiagaraEditor'
    shutil.copytree(source,overlay)
    public=overlay/'Public'
    if a.stack_identity:
        from patch_ue58_stack_identity import changes as stack_changes
        for relative,text in stack_changes(engine).items():
            if relative in headers:
                text=text.replace('\tvoid MoveModule(UNiagaraScript& SourceScript,','\tNIAGARAEDITOR_API void MoveModule(UNiagaraScript& SourceScript,')
            headers[relative]=text
    for relative,text in headers.items():
        dest=overlay/Path(relative).relative_to(prefix);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(text)
    original=engine/'Plugins/FX/Niagara/Intermediate/Build/Linux/x64/UnrealEditor/Development/NiagaraEditor'
    wanted=['NiagaraExternalSystemEditorUtilities.cpp','NiagaraEditorUtilities.cpp','NiagaraStackGraphUtilities.cpp']
    units=[u for u in original.glob('Module.*.cpp') if any(n in u.read_text() for n in wanted)]
    if len(units)!=2:raise ValueError('Original unity partition changed')
    replacements={};rows=[]
    for unit in units:
        rsp=Path(str(unit)+'.o.rsp');lines=rsp.read_text().splitlines();dest=work/unit.stem;dest.mkdir()
        obj=dest/(unit.name+'.o');local_unit=dest/unit.name
        new=['-I"'+str(public)+'"'];counts={'output':0,'dependency':0,'source':0}
        for line in lines:
            line=line.replace(str(source),str(overlay)).replace('../Plugins/FX/Niagara/Source/NiagaraEditor/',str(overlay)+'/')
            if line.startswith('-o '):line='-o "'+str(obj)+'"';counts['output']+=1
            elif line.startswith('-MD -MF'):line='-MD -MF"'+str(dest/'dependencies.d')+'"';counts['dependency']+=1
            else:
                tokens=shlex.split(line)
                if len(tokens)==1 and not line.startswith(('-','@')) and (engine/'Source'/tokens[0]).resolve()==unit.resolve():
                    line='"'+str(local_unit)+'"';counts['source']+=1
            new.append(line)
        if counts!={'output':1,'dependency':1,'source':1}:raise ValueError('Unknown original compile output/source form')
        local_unit.write_text(unit.read_text().replace(str(source),str(overlay)).replace('../Plugins/FX/Niagara/Source/NiagaraEditor/',str(overlay)+'/'))
        new=[line.replace(str(unit),str(local_unit)) for line in new]
        compiler=Path(re.search(r'^--sysroot="([^"]+)"$',rsp.read_text(),re.M).group(1))/'bin/clang++'
        compile_rsp=dest/'compile.rsp';compile_rsp.write_text('\n'.join(new)+'\n')
        print('compile '+unit.name,flush=True)
        with (dest/'compile.log').open('w') as log:r=subprocess.run([str(compiler),'@'+str(compile_rsp)],cwd=engine/'Source',stdout=log,stderr=subprocess.STDOUT,timeout=1800)
        if r.returncode:raise RuntimeError('NiagaraEditor compile failed; inspect isolated log')
        replacements[Path(str(unit)+'.o')]=obj;rows.append({'originalUnity':unit.name,'compileResponseSha256':sha(rsp)})
    objects=original/'libUnrealEditor-NiagaraEditor.so.rsp';lines=[];count=0
    for line in objects.read_text().splitlines():
        tokens=shlex.split(line)
        if len(tokens)==1 and not tokens[0].startswith('-'):
            candidate=(engine/'Source'/tokens[0]).resolve()
            if candidate in replacements:line='"'+str(replacements[candidate])+'"';count+=1
        lines.append(line)
    if count!=len(replacements):raise ValueError('Original linker object references changed')
    objects_rsp=work/'objects.rsp';objects_rsp.write_text('\n'.join(lines)+'\n')
    reference=engine/'Plugins/FX/Niagara/Binaries/Linux/libUnrealEditor-NiagaraEditor.so'
    output=work/'overrides/backend/Engine/Plugins/FX/Niagara/Binaries/Linux'/reference.name;output.parent.mkdir(parents=True)
    links=[];counts={'output':0,'objects':0}
    for line in (original/'libUnrealEditor-NiagaraEditor.so.link.rsp').read_text().splitlines():
        if line.startswith('-o '):line='-o "'+str(output)+'"';counts['output']+=1
        elif line.startswith('-Wl,@'):line='-Wl,@"'+str(objects_rsp)+'"';counts['objects']+=1
        links.append(line)
    if counts!={'output':1,'objects':1}:raise ValueError('Unknown original linker output form')
    links+=final_dependency_flags(engine,reference)
    link=work/'link.rsp';link.write_text('\n'.join(links)+'\n')
    with (work/'link.log').open('w') as log:r=subprocess.run([str(compiler),'@'+str(link)],cwd=engine/'Source',stdout=log,stderr=subprocess.STDOUT,timeout=1800)
    if r.returncode:raise RuntimeError('NiagaraEditor final link failed')
    if a.stack_identity and not any('Invalid script usage GUID'.encode(enc) in output.read_bytes() for enc in ('utf-8','utf-16le','utf-32le')):
        raise RuntimeError('Rebuilt library does not contain the patched script identity resolver')
    symbols=subprocess.check_output(['nm','-D','--defined-only',str(output)],text=True)
    for expected in ['GetInput','GetModule','GetScriptFromSystem','MoveModule']:
        if expected not in symbols:raise RuntimeError('Required export missing: '+expected)
    report={'schema':'niagara-general-authoring-linux-rebuild/1','ok':True,'qualified':False,'sourceEngineOutputsModified':False,
            'recompiledUnits':rows,'output':output.relative_to(work).as_posix(),'sha256':sha(output),'seconds':round(time.monotonic()-start,3)}
    (work/'rebuild.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)


if __name__=='__main__':main()
