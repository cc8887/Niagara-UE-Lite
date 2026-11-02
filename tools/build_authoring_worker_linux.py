"""Build the native CLI worker using matching original UE 5.8.1 UBT responses.

Requires the NiagaraEditor library from build_general_authoring_linux.py, with
--stack-identity enabled for event/simulation-stage editing. Original outputs
remain untouched. This is a developer build tool, not an end-user dependency.
"""
import argparse,json,re,shlex,subprocess,sys
from pathlib import Path
from build_editor_backend_linux import final_dependency_flags,sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','reference-project','core-build','work'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();engine=a.engine.resolve();project=a.reference_project.resolve();core=a.core_build.resolve();work=a.work.resolve()
    if sys.platform!='linux':p.error('Linux only')
    if work.exists() or work.is_relative_to(engine) or work.is_relative_to(project):p.error('New independent build directory required')
    version=json.loads((engine/'Build/Build.version').read_text())
    if [version[k] for k in ('MajorVersion','MinorVersion','PatchVersion')]!=[5,8,1]:p.error('UE 5.8.1 required')
    library=core/'overrides/backend/Engine/Plugins/FX/Niagara/Binaries/Linux/libUnrealEditor-NiagaraEditor.so'
    if not library.is_file():p.error('Rebuilt native NiagaraEditor library missing')
    work.mkdir(parents=True)
    source=Path(__file__).resolve().parents[1]/'RuntimeProject/Source/NiagaraStandaloneEditor'
    records=[]
    for f in source.iterdir():
        if f.suffix not in ('.cpp','.h','.inl'):continue
        (work/f.name).write_bytes(f.read_bytes());records.append({'path':f.name,'sha256':sha(f)})
    original=project/'Intermediate/Build/Linux/x64/UnrealEditor/Development/NiagaraStandaloneEditor'
    original_rsp=original/'NiagaraStandaloneCommandlet.cpp.o.rsp'
    lines=['-I"'+str(core/'NiagaraEditor/Public')+'"'];counts={'o':0,'source':0,'dep':0}
    for line in original_rsp.read_text().splitlines():
        if line.startswith('-o '):line='-o "'+str(work/'worker.o')+'"';counts['o']+=1
        elif line.startswith('-MD -MF'):line='-MD -MF"'+str(work/'dependencies.d')+'"';counts['dep']+=1
        else:
            args=shlex.split(line)
            if len(args)==1 and not line.startswith(('-','@')) and (engine/'Source'/args[0]).resolve()==project/'Source/NiagaraStandaloneEditor/NiagaraStandaloneCommandlet.cpp':
                line='"'+str(work/'NiagaraStandaloneCommandlet.cpp')+'"';counts['source']+=1
        lines.append(line)
    if counts!={'o':1,'source':1,'dep':1}:raise ValueError('Original worker compiler response changed')
    rsp=work/'compile.rsp';rsp.write_text('\n'.join(lines)+'\n')
    compiler=Path(re.search(r'^--sysroot="([^"]+)"$',original_rsp.read_text(),re.M).group(1))/'bin/clang++'
    def run(command,log):
        with (work/log).open('w') as output:r=subprocess.run(command,cwd=engine/'Source',stdout=output,stderr=subprocess.STDOUT,timeout=1800)
        if r.returncode:raise RuntimeError('Native build failed; inspect '+log)
    run([str(compiler),'@'+str(rsp)],'compile.log')
    lines=[];count=0
    for line in (original/'libUnrealEditor-NiagaraStandaloneEditor.so.rsp').read_text().splitlines():
        args=shlex.split(line)
        if len(args)==1 and not line.startswith('-') and (engine/'Source'/args[0]).resolve()==original/'NiagaraStandaloneCommandlet.cpp.o':line='"'+str(work/'worker.o')+'"';count+=1
        lines.append(line)
    if count!=1:raise ValueError('Original worker object list changed')
    objects=work/'objects.rsp';objects.write_text('\n'.join(lines)+'\n')
    output=work/'overrides/Project/Binaries/Linux/libUnrealEditor-NiagaraStandaloneEditor.so';output.parent.mkdir(parents=True)
    lines=[];counts={'o':0,'objects':0}
    for line in (original/'libUnrealEditor-NiagaraStandaloneEditor.so.link.rsp').read_text().splitlines():
        if line.startswith('-o '):line='-o "'+str(output)+'"';counts['o']+=1
        elif line.startswith('-Wl,@'):line='-Wl,@"'+str(objects)+'"';counts['objects']+=1
        lines.append(line)
    if counts!={'o':1,'objects':1}:raise ValueError('Original worker linker response changed')
    lines+=final_dependency_flags(engine,project/'Binaries/Linux/libUnrealEditor-NiagaraStandaloneEditor.so')
    old=str(engine/'Plugins/FX/Niagara/Binaries/Linux/libUnrealEditor-NiagaraEditor.so')
    lines=[line.replace(old,str(library)).replace('-lUnrealEditor-NiagaraEditor','"'+str(library)+'"') for line in lines]
    link=work/'link.rsp';link.write_text('\n'.join(lines)+'\n');run([str(compiler),'@'+str(link)],'link.log')
    result={'ok':True,'qualified':False,'engine':'5.8.1','sources':records,'coreSha256':sha(library),'sha256':sha(output),'output':output.relative_to(work).as_posix()}
    (work/'build.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)


if __name__=='__main__':main()
