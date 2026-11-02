"""Remove old cooked example effects from a staged kit's runtime scaffold.

Preserves the original Pak in a new work directory; replaces the staged copy only
after the native UnrealPak rebuild and list checks pass. Run before sealing.
"""
import argparse,json,os,shutil,subprocess
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kit',type=Path,required=True);p.add_argument('--work',type=Path,required=True);a=p.parse_args()
    kit=a.kit.resolve();work=a.work.resolve();win=os.name=='nt'
    if work.exists() or work.is_relative_to(kit) or kit.is_relative_to(work):p.error('New independent work directory required')
    paks=list((kit/'runtime-template').glob('**/Content/Paks/*.pak'))
    if len(paks)!=1:p.error('Expected one runtime scaffold Pak')
    pak=paks[0]
    if not pak.resolve().is_relative_to(kit):p.error('Pak escapes kit')
    executable=kit/'backend/Engine/Binaries'/('Win64/UnrealPak.exe' if win else 'Linux/UnrealPak')
    project=kit/'Project/NiagaraStandalone.uproject';work.mkdir(parents=True)
    shutil.copyfile(pak,work/'original.pak');files=work/'files';files.mkdir()
    def run(args,log):
        with (work/log).open('w') as output:r=subprocess.run([str(executable),str(project),*map(str,args),'-unattended','-NoZenAutoLaunch','-culture=en'],cwd=kit/'Project',stdout=output,stderr=subprocess.STDOUT,timeout=1800)
        if r.returncode:raise RuntimeError('Native Pak operation failed: '+log)
    run([pak,'-Extract',files],'extract.log')
    excluded=('NiagaraStandalone/Content/NiagaraDemo/','Engine/Plugins/FX/Niagara/Content/DefaultAssets/Templates/')
    kept=[];removed=[]
    for file in sorted(files.rglob('*')):
        if not file.is_file():continue
        relative=file.relative_to(files).as_posix()
        if relative.startswith(excluded):removed.append(relative)
        else:kept.append((relative,file))
    response=work/'pak-files.txt';response.write_text('\n'.join('"'+str(file)+'" "../../../'+relative+'"' for relative,file in kept)+'\n')
    output=work/'clean.pak';run([output,'-Create='+str(response),'-compress'],'create.log');run([output,'-List'],'list.log')
    text=(work/'list.log').read_text(errors='replace')
    if any('"'+prefix in text for prefix in excluded):raise RuntimeError('Cooked effect fixtures remain in rebuilt Pak')
    temporary=pak.with_name(pak.name+'.clean-new');shutil.copyfile(output,temporary);os.replace(temporary,pak)
    report={'schema':'niagara-runtime-scaffold-pruning/1','ok':True,'removed':removed,'retainedFiles':len(kept),'originalBytes':(work/'original.pak').stat().st_size,'bytes':pak.stat().st_size}
    (work/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)


if __name__=='__main__':main()
