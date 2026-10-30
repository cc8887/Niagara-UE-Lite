"""Developer build; consumer kits do not execute UBT, UAT or a C++ compiler."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--jobs',type=int,default=6)
    p.add_argument('--archive',required=True,type=Path);a=p.parse_args()
    if not 1<=a.jobs<=64:raise ValueError('jobs must be 1..64')
    engine=Path(os.environ['NIAGARA_BUILD_ENGINE']).resolve()
    project=Path(os.environ.get('NIAGARA_BUILD_PROJECT',ROOT/'RuntimeProject/NiagaraStandalone.uproject')).resolve()
    win=os.name=='nt';platform='Win64' if win else 'Linux';ext='.bat' if win else '.sh'
    build=engine/'Build/BatchFiles'/('Build.bat' if win else 'Linux/Build.sh')
    def call(args):subprocess.run([str(x) for x in args],check=True,cwd=ROOT)
    if not win:
        call([sys.executable,ROOT/'tools/patch_ue58_cpu_vulkan.py'])
        call([sys.executable,ROOT/'tools/patch_ue58_standalone.py'])
    for target,config in [('NiagaraStandaloneEditor','Development'),('NiagaraStandalone','Shipping')]:
        call([build,target,platform,config,'-Project='+str(project),'-NoUBA','-MaxParallelActions='+str(a.jobs)])
    os.environ.update({'NIAGARA_LITE_ENGINE':str(engine),'NIAGARA_LITE_PROJECT':str(project)})
    import niagara_cli as cli
    path=project.parent
    if not (path/'Content/NiagaraDemo/NS_Fountain.uasset').exists():
        cli.edit(path,project,'create','/Game/NiagaraDemo/NS_Fountain',1800,operations=cli.operations(ROOT/'examples/fountain.json'))
    cli.edit(path,project,'prepare-preview','/Game/NiagaraPreview/Preview',1800)
    code,_=cli.run([cli.editor(),project,'-run=Cook','-TargetPlatform='+('Windows' if win else 'Linux'),
                    '-CookDir='+str(path/'Content'),'-Map=/Game/NiagaraPreview/Preview','-unversioned','-compressed',
                    '-SkipCookingEditorContent','-NullRHI',*cli.common()],path,cli.env_for(path),path/'Saved/niagara-build-cook.log',7200)
    if code:raise RuntimeError('Initial native Cook failed')
    call([engine/'Build/BatchFiles'/('RunUAT'+ext),'BuildCookRun','-project='+str(project),'-noP4',
          '-platform='+platform,'-clientconfig=Shipping','-skipbuild','-skipcook','-stage','-pak','-compressed',
          '-archive','-archivedirectory='+str(a.archive.resolve()),'-unattended','-nocompileeditor','-skipbuildeditor'])
    if win:
        a.archive.mkdir(parents=True,exist_ok=True)
        call(['cl.exe','/nologo','/std:c++17','/O2','/MT','/EHsc',ROOT/'NativeClient/main_windows.cpp',
              '/Fe:'+str(a.archive/'niagara-cli.exe'),'/Fo:'+str(a.archive/'niagara-cli.obj'),'/link','/INCREMENTAL:NO'])

if __name__=='__main__':main()
