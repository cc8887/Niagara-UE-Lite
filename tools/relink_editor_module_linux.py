"""Relink an existing matching UE module without explicitly unused module imports.

Uses original UBT objects. The final link must resolve all symbols without the
omitted libraries; runtime dynamic-load qualification remains mandatory.
"""
import argparse,json,re,subprocess,sys
from pathlib import Path
from build_editor_backend_linux import final_dependency_flags,sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine',type=Path,required=True);p.add_argument('--work',type=Path,required=True)
    p.add_argument('--module',required=True);p.add_argument('--omit',nargs='+',required=True)
    a=p.parse_args();engine=a.engine.resolve();work=a.work.resolve()
    if sys.platform!='linux':p.error('Linux only')
    if any(not re.fullmatch('[A-Za-z0-9_]+',n) for n in [a.module,*a.omit]):p.error('Invalid module name')
    if work.exists() or work.is_relative_to(engine) or engine.is_relative_to(work):p.error('New isolated output required')
    work.mkdir(parents=True)
    original=engine/'Intermediate/Build/Linux/x64/UnrealEditor/Development'/a.module
    reference=engine/'Binaries/Linux'/('libUnrealEditor-'+a.module+'.so')
    rsp=original/(reference.name+'.link.rsp');text=rsp.read_text()
    output=work/'overrides/backend/Engine/Binaries/Linux'/reference.name;output.parent.mkdir(parents=True)
    lines=text.splitlines();count=0
    for i,line in enumerate(lines):
        if line.startswith('-o '):lines[i]='-o "'+str(output)+'"';count+=1
    if count!=1:raise ValueError('Unknown original linker output form')
    omitted=['libUnrealEditor-'+n+'.so' for n in a.omit]
    lines+=final_dependency_flags(engine,reference,omitted)
    lines.append('-Wl,--no-undefined')
    dest=work/'link.rsp';dest.write_text('\n'.join(lines)+'\n')
    sysroot=re.search(r'^--sysroot="([^"]+)"$',text,re.M).group(1)
    with (work/'link.log').open('w') as log:
        result=subprocess.run([str(Path(sysroot)/'bin/clang++'),'@'+str(dest)],cwd=engine/'Source',stdout=log,stderr=subprocess.STDOUT,timeout=1200)
    if result.returncode:raise RuntimeError('Final link failed; inspect isolated log')
    dynamic=subprocess.check_output(['readelf','-dW',str(output)],text=True)
    needed=re.findall(r'\(NEEDED\).*?\[(.*?)\]',dynamic)
    if set(omitted)&set(needed):raise RuntimeError('Omitted module still required')
    report={'schema':'niagara-editor-module-relink/1','ok':True,'qualified':False,'module':a.module,
            'omitted':a.omit,'allSymbolsResolvedWithoutOmittedModules':True,
            'referenceSha256':sha(reference),'originalLinkResponseSha256':sha(rsp),
            'output':output.relative_to(work).as_posix(),'sha256':sha(output),'needed':needed}
    (work/'relink.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)


if __name__=='__main__':main()
