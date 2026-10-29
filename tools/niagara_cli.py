"""Portable native UE Niagara authoring, Cook and preview frontend."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
WIN=sys.platform=='win32'
PLATFORM='Windows' if WIN else 'Linux'
BIN='Win64' if WIN else 'Linux'
EXT='.exe' if WIN else ''
ENGINE=Path(os.environ.get('NIAGARA_LITE_ENGINE',ROOT/'backend/Engine'))
ASSET=re.compile(r'/Game/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*')

def asset(value):
    if not ASSET.fullmatch(value):raise ValueError('Expected a /Game package path without suffix or traversal')
    return value

def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write_json(path,data):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def copy_file(source,destination):
    # Preserve executable bits without attempting to copy source timestamps
    # across filesystems (DrvFS/NTFS may reject those timestamp operations).
    result=shutil.copyfile(source,destination)
    shutil.copymode(source,destination)
    return result

def workspace(path):
    explicit=os.environ.get('NIAGARA_LITE_PROJECT')
    if explicit:
        project=Path(explicit).resolve()
        return project.parent,project
    path=path.resolve()
    project=path/'NiagaraStandalone.uproject'
    if not project.exists():
        if path.exists() and any(path.iterdir()):raise ValueError('Workspace must be new or already initialized')
        shutil.copytree(ROOT/'Project',path,dirs_exist_ok=True,copy_function=copy_file)
        if (ROOT/'cache').is_dir():shutil.copytree(ROOT/'cache',path/'DerivedDataCache',dirs_exist_ok=True,copy_function=copy_file)
    return path,project

def env_for(path):
    env=os.environ.copy()
    env.update({'UE-LocalDataCachePath':str(path/'DerivedDataCache'),'UE-SharedDataCachePath':'None',
                'UE_SKIP_UBT_SDK_SETUP':'1','PYTHONNOUSERSITE':'1'})
    for key in ('LINUX_MULTIARCH_ROOT','UE_SDKS_ROOT','NIAGARA_LITE_ENGINE','NIAGARA_LITE_PROJECT'):
        env.pop(key,None)
    return env

def run(command,cwd,env,log,timeout):
    log.parent.mkdir(parents=True,exist_ok=True)
    print('niagara-cli: '+log.stem,file=sys.stderr,flush=True)
    started=time.monotonic()
    with log.open('w',encoding='utf-8') as stream:
        proc=subprocess.Popen([str(x) for x in command],cwd=cwd,env=env,stdout=stream,stderr=subprocess.STDOUT,
                              start_new_session=not WIN,creationflags=subprocess.CREATE_NO_WINDOW if WIN else 0)
        try:code=proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if WIN:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            else:
                import signal
                os.killpg(proc.pid,signal.SIGKILL)
            proc.wait();raise RuntimeError('Native backend timed out: '+str(log))
    return code,time.monotonic()-started

def common():
    return ['-unattended','-nosplash','-nosound','-nop4','-NoCrashDialog','-NoCrashReportClient',
            '-notraceserver','-NoZenAutoLaunch','-culture=en','-stdout','-FullStdOutLogOutput','-ddc=NiagaraStandaloneDDC']

def editor():return ENGINE/'Binaries'/BIN/('UnrealEditor-Cmd'+EXT)

def operations(recipe):
    data=load_json(recipe)
    if not isinstance(data,dict) or data.get('schema')!='ue-niagara-recipe/1':
        raise ValueError('Expected ue-niagara-recipe/1')
    ops=data.get('operations',[])
    if not isinstance(ops,list):raise ValueError('operations must be an array')
    supported={'add-emitter','remove-emitter','add-module','remove-module','module-enabled','input',
               'emitter-enabled','system-properties','emitter-properties','renderer-properties',
               'add-sprite-renderer','remove-renderer'}
    for op in ops:
        if not isinstance(op,dict) or op.get('op') not in supported:raise ValueError('Unknown operation')
        action=op['op']
        required={'add-emitter':['emitter','template'],'remove-emitter':['emitter'],
                  'add-module':['emitter','script','asset'],'remove-module':['emitter','script','module'],
                  'input':['emitter','script','module','type','value'],
                  'module-enabled':['emitter','script','module','value'],'emitter-enabled':['emitter','value'],
                  'system-properties':['properties'],'emitter-properties':['emitter','properties'],
                  'renderer-properties':['emitter','renderer','properties'],
                  'add-sprite-renderer':['emitter'],'remove-renderer':['emitter','renderer']}[action]
        if any(k not in op for k in required):raise ValueError('Missing field for '+action)
        if action.endswith('-enabled') and not isinstance(op['value'],bool):raise ValueError('enabled value must be boolean')
        if action.endswith('-properties') and not isinstance(op['properties'],dict):raise ValueError('properties must be an object')
        if action=='input' and not (isinstance(op.get('input'),str) or isinstance(op.get('inputs'),list)):
            raise ValueError('input requires input name or inputs path')
        if 'renderer' in op and (type(op['renderer']) is not int or op['renderer']<0):raise ValueError('Invalid renderer index')
    return ops

def edit(path,project,operation,asset_name,timeout,**fields):
    state=path/'Saved/NiagaraStandalone';token=uuid.uuid4().hex
    request=state/(token+'.request.json');response=state/(token+'.response.json');log=state/(token+'-'+operation+'.log')
    write_json(request,{'operation':operation,'asset':asset(asset_name),**fields})
    code,elapsed=run([editor(),project,'-run=NiagaraStandalone','-Request='+str(request),'-Response='+str(response),
                      '-NullRHI',*common()],path,env_for(path),log,timeout)
    result=load_json(response) if response.exists() else {'ok':False,'errors':['Backend did not write a response']}
    result.update({'backendExitCode':code,'wallSeconds':elapsed,'log':str(log)})
    if code or not result.get('ok'):raise RuntimeError(json.dumps(result,ensure_ascii=False))
    return result

def python_worker(path,project,script,timeout,request=None):
    token=uuid.uuid4().hex;state=path/'Saved/NiagaraStandalone';log=state/(token+'-assets.log')
    env=env_for(path);response=state/(token+'.response.json')
    if request:
        req=state/(token+'.request.json');write_json(req,request)
        env.update({'NIAGARA_ASSET_REQUEST':str(req),'NIAGARA_ASSET_RESPONSE':str(response)})
    tools=ROOT/'scripts' if (ROOT/'scripts').is_dir() else ROOT/'tools'
    code,_=run([editor(),project,'-run=pythonscript','-script='+str(tools/script),'-NullRHI',*common()],path,env,log,timeout)
    result=load_json(response) if response.exists() else {'ok':not code}
    if code or not result.get('ok'):raise RuntimeError(f'Asset worker failed ({code}): {result}; {log}')
    return result

def cook(path,project,system,output,timeout):
    edit(path,project,'read',system,timeout)
    if output.exists():raise ValueError('Cook output exists; use a new directory')
    python_worker(path,project,'author_preview.py',timeout)
    state=path/'Saved/NiagaraStandalone';token=uuid.uuid4().hex
    log=state/(token+'-cook.log')
    code,_=run([editor(),project,'-run=Cook','-TargetPlatform='+PLATFORM,'-CookDir='+str(path/'Content'),
                '-Map=/Game/NiagaraPreview/Preview','-unversioned','-compressed','-SkipCookingEditorContent','-NullRHI',*common()],
               path,env_for(path),log,timeout)
    if code:raise RuntimeError('Native Cook failed: '+str(log))
    cooked=path/'Saved/Cooked'/PLATFORM
    shader='PCD3D_SM6' if WIN else 'VULKAN_SM6'
    if not (cooked/'Engine'/('GlobalShaderCache-'+shader+'.bin')).is_file():raise RuntimeError('Cook did not produce the expected SM6 shader cache')
    template=Path(os.environ.get('NIAGARA_LITE_RUNTIME_TEMPLATE',ROOT/'runtime-template'))
    shutil.copytree(template,output,copy_function=copy_file)
    paks=list(template.glob('**/Content/Paks/*.pak'))
    if len(paks)!=1:raise RuntimeError('Expected exactly one template Pak')
    pak=paks[0];digest=hashlib.sha256(pak.read_bytes()).hexdigest()
    cache=state/'RuntimeBase'/digest;unrealpak=ENGINE/'Binaries'/BIN/('UnrealPak'+EXT)
    if not (cache/'complete').exists():
        cache.mkdir(parents=True,exist_ok=True)
        code,_=run([unrealpak,project,pak,'-Extract',cache/'files',*common()],path,env_for(path),state/(token+'-extract.log'),timeout)
        if code:raise RuntimeError('Template extraction failed')
        (cache/'complete').write_text(digest)
    merged={p.relative_to(cache/'files').as_posix():p for p in (cache/'files').rglob('*') if p.is_file()}
    for p in cooked.rglob('*'):
        if p.is_file() and 'Metadata' not in p.relative_to(cooked).parts:merged[p.relative_to(cooked).as_posix()]=p
    response=state/(token+'-pak.txt')
    response.write_text('\n'.join(f'"{p}" "../../../{rel}"' for rel,p in sorted(merged.items()))+'\n',encoding='utf-8')
    target=output/pak.relative_to(template);new=target.with_suffix('.new.pak')
    code,_=run([unrealpak,project,new,'-Create='+str(response),'-compress',*common()],path,env_for(path),state/(token+'-pak.log'),timeout)
    if code:raise RuntimeError('Native Pak creation failed')
    os.replace(new,target)
    manifest={'schema':'niagara-runtime-package/1','engine':'5.8.1','platform':PLATFORM,'system':system,
              'withEditor':False,'runtimeCompilation':False,'files':[]}
    for p in sorted(output.rglob('*')):
        if p.is_file() and p.name!='package-manifest.json':
            manifest['files'].append({'path':p.relative_to(output).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    manifest['payloadBytes']=sum(x['bytes'] for x in manifest['files'])
    write_json(output/'package-manifest.json',manifest)
    return {'ok':True,'package':str(output),'payloadBytes':manifest['payloadBytes'],'system':system}

def render(package,system,out,frames,warmup,width,height,cpu,timeout):
    if out.exists() or Path(str(out)+'.json').exists():raise ValueError('Output exists; choose a new filename')
    candidates=list(package.glob('**/Binaries/'+BIN+'/NiagaraStandalone*Shipping'+EXT))
    if len(candidates)!=1:raise RuntimeError('Expected one native Shipping runtime in package')
    cmd=[candidates[0],'-NiagaraSystem='+asset(system),'-NiagaraOutput='+str(out),'-SimFrames='+str(frames),
         '-WarmupFrames='+str(warmup),'-ResX='+str(width),'-ResY='+str(height),'-windowed','-RenderOffscreen',
         '-d3d12' if WIN else '-vulkan','-sm6','-unattended','-nosplash','-nosound','-NoCrashDialog','-NoCrashReportClient','-notraceserver']
    env=os.environ.copy()
    selected=None
    if cpu:
        if WIN:raise ValueError('CPU Vulkan is supported only on Linux')
        from vulkan_probe import cpu_adapter
        selected=cpu_adapter(package)
        cmd+=['-AllowCPUDevices','-UseLocalVulkanLoader','-CpuVulkan','-MaterialRenderCpuVulkan','-graphicsadapter='+str(selected['index'])]
        env.pop('DISPLAY',None);env.pop('WAYLAND_DISPLAY',None)
    code,elapsed=run(cmd,candidates[0].parent,env,Path(str(out)+'.runtime.log'),timeout)
    meta=Path(str(out)+'.json');result=load_json(meta) if meta.exists() else {'ok':False,'error':'Runtime produced no metadata'}
    result.update({'runtimeExitCode':code,'wallSeconds':elapsed})
    if selected:
        result['selectedCpuAdapter']=selected
        if result.get('adapter')!=selected['name']:raise RuntimeError('Runtime did not use the selected CPU Vulkan adapter: '+json.dumps(result))
    if code or not result.get('ok') or not out.exists():raise RuntimeError(json.dumps(result,ensure_ascii=False))
    write_json(meta,result);return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace',type=Path,default=ROOT/'workspace');p.add_argument('--timeout',type=int,default=1800)
    sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('capabilities');sub.add_parser('init')
    for name in ('create','read','edit','save','compile'):
        q=sub.add_parser(name);q.add_argument('--asset',required=True,type=asset);q.add_argument('--out',type=Path)
        if name in ('create','edit'):q.add_argument('--recipe',type=Path,required=name=='edit')
        if name=='create':q.add_argument('--template')
    q=sub.add_parser('import-texture');q.add_argument('--file',required=True,type=Path);q.add_argument('--asset',required=True,type=asset)
    q.add_argument('--linear',action='store_true')
    q=sub.add_parser('create-material');q.add_argument('--asset',required=True,type=asset);q.add_argument('--texture',required=True,type=asset)
    for name in ('cook','render','build','demo'):
        q=sub.add_parser(name)
        if name!='demo':q.add_argument('--asset',required=True,type=asset)
        if name in ('cook','render'):q.add_argument('--package',required=True,type=Path)
        if name!='cook':
            q.add_argument('--out',required=True,type=Path);q.add_argument('--cpu-vulkan',action='store_true')
            q.add_argument('--frames',type=int,default=60);q.add_argument('--warmup',type=int,default=16)
            q.add_argument('--width',type=int,default=512);q.add_argument('--height',type=int,default=512)
    args=p.parse_args()
    if not 1<=args.timeout<=7200:raise ValueError('timeout must be 1..7200')
    if args.command=='capabilities':return {'ok':True,'engine':'5.8.1','platform':PLATFORM,'nativeNiagara':True,
        'headlessEditorBundled':True,'withUnrealEd':True,'previewWithEditor':False,'create':'template/recipe',
        'serialization':['native uasset','ue-niagara-snapshot/1','ue-niagara-recipe/1'],
        'limitations':['Snapshots describe native graphs; they are not a cross-engine particle format.',
                       'Plugin-specific assets require matching plugins. Scene-dependent interfaces need a supplied scene.',
                       'Initial validation targets a CPU-sim sprite emitter; GPU simulations are separately qualified.']}
    if args.command=='render':path=project=None
    else:path,project=workspace(args.workspace)
    if args.command=='init':return {'ok':True,'workspace':str(path)}
    if args.command in ('create','read','edit','save','compile'):
        fields={}
        if getattr(args,'recipe',None):fields['operations']=operations(args.recipe)
        if getattr(args,'template',None):fields['template']=args.template
        result=edit(path,project,args.command,args.asset,args.timeout,**fields)
        if args.out:write_json(args.out,result)
        return result
    if args.command in ('import-texture','create-material'):
        req={'operation':args.command,'asset':args.asset}
        if args.command=='import-texture':req.update({'file':str(args.file.resolve()),'linear':args.linear})
        else:req['texture']=args.texture
        return python_worker(path,project,'assets_worker.py',args.timeout,req)
    if args.command=='cook':return cook(path,project,args.asset,args.package.resolve(),args.timeout)
    if not (1<=args.frames<=36000 and 1<=args.warmup<=4096 and 64<=args.width<=4096 and 64<=args.height<=4096):
        raise ValueError('Invalid simulation frame count or render size')
    out=args.out.resolve()
    if args.command=='demo':
        args.asset='/Game/NiagaraDemo/NS_Fountain_'+uuid.uuid4().hex[:8]
        result=edit(path,project,'create',args.asset,args.timeout,operations=operations(ROOT/'examples/fountain.json'))
        write_json(out.with_suffix('.asset.json'),result)
    if args.command in ('build','demo'):
        package=out.parent/(out.stem+'-runtime');cook(path,project,args.asset,package,args.timeout)
    else:package=args.package.resolve()
    return render(package,args.asset,out,args.frames,args.warmup,args.width,args.height,args.cpu_vulkan,args.timeout)

if __name__=='__main__':
    try:print(json.dumps(main(),ensure_ascii=False,indent=2))
    except (RuntimeError,ValueError,OSError,KeyError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False,indent=2));sys.exit(1)
