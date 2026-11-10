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

# The public protocol is UTF-8 JSON, including redirected Windows output.
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8')

ROOT=Path(__file__).resolve().parents[1]
WIN=sys.platform=='win32'
PLATFORM='Windows' if WIN else 'Linux'
BIN='Win64' if WIN else 'Linux'
EXT='.exe' if WIN else ''
DEMOS={'fountain':'fountain.json','gpu':'gpu-fountain.json',
       'ribbon':'ribbon-beam.json','mesh':'mesh-fountain.json'}
ENGINE=Path(os.environ.get('NIAGARA_LITE_ENGINE',ROOT/'backend/Engine'))
def engine_version():
    version=json.loads((ENGINE/'Build/Build.version').read_text(encoding='utf-8-sig'))
    return '.'.join(str(version[k]) for k in ('MajorVersion','MinorVersion','PatchVersion'))
ASSET=re.compile(r'/Game/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*')

class BackendFailure(RuntimeError):
    def __init__(self,result):
        self.result=result
        super().__init__('Native backend operation failed')

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

def copy_runtime_template(template,output):
    shutil.copytree(template,output,copy_function=copy_file)
    # The Windows kit stores shared DLLs once in the backend. Materialize every
    # runtime path so exported previews remain independent of the authoring kit.
    links=ROOT/'runtime-template-links.json'
    if template.resolve()!=(ROOT/'runtime-template').resolve() or not links.exists():return
    mapping=load_json(links)
    if mapping.get('schema')!='niagara-runtime-template-links/1':
        raise ValueError('Unsupported runtime template link manifest')
    for record in mapping['files']:
        source=(ROOT/record['source']).resolve();destination=(output/record['path']).resolve()
        if not source.is_relative_to(ROOT.resolve()) or not destination.is_relative_to(output.resolve()):
            raise ValueError('Runtime template link escapes package')
        if destination.exists():raise ValueError('Runtime template link duplicates an existing file')
        data=source.read_bytes()
        if len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256']:
            raise ValueError('Shared runtime library failed integrity verification')
        destination.parent.mkdir(parents=True,exist_ok=True)
        copy_file(source,destination)

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
    if WIN and len(str(path/'DerivedDataCache'))>119:
        raise ValueError('UE Windows filesystem DDC path exceeds 119 characters; use a shorter --workspace path')
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
            '-notraceserver','-NoZenAutoLaunch','-culture=en','-stdout','-FullStdOutLogOutput','-ddc=NiagaraStandaloneDDC',
            '-NiagaraLiteBackend']

def editor():return ENGINE/'Binaries'/BIN/('UnrealEditor-Cmd'+EXT)

def operation_contract():
    return {'add-emitter':['emitter'],'remove-emitter':['emitter'],
                  'add-set-parameters':['script','parameters'],'add-set-parameter':['script','module','parameters'],
                  'remove-set-parameter':['script','module','name'],
                  'add-stage':['name'],'remove-stage':['usageId'],
                  'stage-properties':['usageId','properties'],'stage-enabled':['usageId','value'],
                  'move-stage':['usageId','index'],'add-event-handler':[],
                  'event-properties':['usageId','properties'],'remove-event-handler':['usageId'],
                  'rename-emitter':['emitter','name'],'duplicate-emitter':['emitter','name'],
                  'add-module':['script','asset'],'remove-module':['script','module'],
                  'move-module':['script','module','index'],'reset-input':['script','module'],
                  'scratch-module':['script','module','name'],
                  'input':['script','module','type','value'],
                  'module-enabled':['script','module','value'],'emitter-enabled':['emitter','value'],
                  'asset-properties':['properties'],'system-properties':['properties'],'emitter-properties':['properties'],
                  'renderer-properties':['renderer','properties'],
                  'add-sprite-renderer':[],'add-ribbon-renderer':[],
                  'add-mesh-renderer':[],'add-renderer':['class'],'remove-renderer':['renderer'],
                  'set-user':['name','type','value'],'remove-user':['name']}


def operations(recipe):
    data=load_json(recipe)
    if not isinstance(data,dict) or data.get('schema')!='ue-niagara-recipe/1':
        raise ValueError('Expected ue-niagara-recipe/1')
    ops=data.get('operations',[])
    if not isinstance(ops,list):raise ValueError('operations must be an array')
    contract=operation_contract()
    for op in ops:
        if not isinstance(op,dict) or op.get('op') not in contract:raise ValueError('Unknown operation')
        action=op['op'];required=contract[action]
        if any(k not in op for k in required):raise ValueError('Missing field for '+action)
        if action.endswith('-enabled') and not isinstance(op['value'],bool):raise ValueError('enabled value must be boolean')
        if action.endswith('-properties') and not isinstance(op['properties'],dict):raise ValueError('properties must be an object')
        if action in ('input','reset-input') and not (isinstance(op.get('input'),str) or isinstance(op.get('inputs'),list)):
            raise ValueError('input requires input name or inputs path')
        if action in ('move-module','move-stage') and (type(op['index']) is not int or op['index']<0):raise ValueError('Invalid destination index')
        if 'renderer' in op and (type(op['renderer']) is not int or op['renderer']<0):raise ValueError('Invalid renderer index')
    return ops

def backend_request(path,project,payload,timeout):
    operation=payload['operation']
    state=path/'Saved/NiagaraStandalone';token=uuid.uuid4().hex
    request=state/(token+'.request.json');response=state/(token+'.response.json');log=state/(token+'-'+operation+'.log')
    write_json(request,payload)
    code,elapsed=run([editor(),project,'-run=NiagaraStandalone','-Request='+str(request),'-Response='+str(response),
                      '-NullRHI',*common()],path,env_for(path),log,timeout)
    result=load_json(response) if response.exists() else {'ok':False,'errors':['Backend did not write a response']}
    result.update({'backendExitCode':code,'wallSeconds':elapsed,'log':str(log)})
    if code:result['ok']=False
    if code or not result.get('ok'):raise BackendFailure(result)
    return result

def edit(path,project,operation,asset_name,timeout,**fields):
    return backend_request(path,project,{'operation':operation,'asset':asset(asset_name),**fields},timeout)

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

def cook(path,project,system,output,timeout,include=()):
    edit(path,project,'read',system,timeout)
    if output.exists():raise ValueError('Cook output exists; use a new directory')
    edit(path,project,'prepare-preview','/Game/NiagaraPreview/Preview',timeout)
    state=path/'Saved/NiagaraStandalone';token=uuid.uuid4().hex
    log=state/(token+'-cook.log')
    roots=list(dict.fromkeys([system,*include]))
    code,_=run([editor(),project,'-run=Cook','-TargetPlatform='+PLATFORM,*['-Package='+asset(p) for p in roots],
                '-Map=/Game/NiagaraPreview/Preview','-unversioned','-compressed','-SkipCookingEditorContent','-NullRHI',*common()],
               path,env_for(path),log,timeout)
    if code:raise RuntimeError('Native Cook failed: '+str(log))
    cooked=path/'Saved/Cooked'/PLATFORM
    shader='PCD3D_SM6' if WIN else 'VULKAN_SM6'
    if not (cooked/'Engine'/('GlobalShaderCache-'+shader+'.bin')).is_file():raise RuntimeError('Cook did not produce the expected SM6 shader cache')
    template=Path(os.environ.get('NIAGARA_LITE_RUNTIME_TEMPLATE',ROOT/'runtime-template'))
    copy_runtime_template(template,output)
    paks=list(template.glob('**/Content/Paks/*.pak'))
    if len(paks)!=1:raise RuntimeError('Expected exactly one template Pak')
    pak=paks[0];digest=hashlib.sha256(pak.read_bytes()).hexdigest()
    cache=state/'RuntimeBase'/digest;unrealpak=ENGINE/'Binaries'/BIN/('UnrealPak'+EXT)
    if not (cache/'complete').exists():
        cache.mkdir(parents=True,exist_ok=True)
        code,_=run([unrealpak,project,pak,'-Extract',cache/'files',*common()],path,env_for(path),state/(token+'-extract.log'),timeout)
        if code:raise RuntimeError('Template extraction failed')
        (cache/'complete').write_text(digest)
    omitted=('NiagaraStandalone/Content/NiagaraDemo/','Engine/Plugins/FX/Niagara/Content/DefaultAssets/Templates/')
    merged={p.relative_to(cache/'files').as_posix():p for p in (cache/'files').rglob('*') if p.is_file() and not p.relative_to(cache/'files').as_posix().startswith(omitted)}
    for p in cooked.rglob('*'):
        if p.is_file() and 'Metadata' not in p.relative_to(cooked).parts:merged[p.relative_to(cooked).as_posix()]=p
    response=state/(token+'-pak.txt')
    response.write_text('\n'.join(f'"{p}" "../../../{rel}"' for rel,p in sorted(merged.items()))+'\n',encoding='utf-8')
    target=output/pak.relative_to(template);new=target.with_suffix('.new.pak')
    code,_=run([unrealpak,project,new,'-Create='+str(response),'-compress',*common()],path,env_for(path),state/(token+'-pak.log'),timeout)
    if code:raise RuntimeError('Native Pak creation failed')
    os.replace(new,target)
    manifest={'schema':'niagara-runtime-package/1','engine':engine_version(),'platform':PLATFORM,'system':system,
              'requestedPackages':roots,'cookScope':'requested packages and native dependency closure',
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
    sub.add_parser('api')
    q=sub.add_parser('export');q.add_argument('--asset',required=True,type=asset);q.add_argument('--out',required=True,type=Path)
    q=sub.add_parser('import');q.add_argument('--file',required=True,type=Path)
    q=sub.add_parser('native-python');q.add_argument('--file',required=True,type=Path);q.add_argument('--params',type=Path)
    q=sub.add_parser('catalog');q.add_argument('--kind',required=True,choices=['systems','emitters','modules','dynamic-inputs','renderers','data-interfaces','stage-classes','materials','textures','meshes','assets'])
    q.add_argument('--class',dest='class')
    q.add_argument('--search',default='');q.add_argument('--root',default='/');q.add_argument('--offset',type=int,default=0);q.add_argument('--limit',type=int,default=200);q.add_argument('--out',type=Path)
    q=sub.add_parser('schema');q.add_argument('--kind',required=True,choices=['asset','system','emitter','module','dynamic-input','renderer','data-interface','stage','instance','input','stacks'])
    q.add_argument('--asset');q.add_argument('--emitter');q.add_argument('--script');q.add_argument('--module');q.add_argument('--inputs',nargs='+');q.add_argument('--out',type=Path)
    q.add_argument('--usage-id',dest='usageId')
    q=sub.add_parser('import-assets');q.add_argument('--source',required=True,type=Path)
    for name in ('create','read','edit','save','compile'):
        q=sub.add_parser(name);q.add_argument('--asset',required=True,type=asset);q.add_argument('--out',type=Path)
        if name in ('create','edit'):q.add_argument('--recipe',type=Path,required=name=='edit')
        if name=='create':q.add_argument('--template');q.add_argument('--asset-kind',dest='assetKind',choices=['system','emitter'],default='system')
        q.add_argument('--compile-policy',dest='compilePolicy',choices=['require-valid','allow-errors','defer'],default='require-valid')
    q=sub.add_parser('import-texture');q.add_argument('--file',required=True,type=Path);q.add_argument('--asset',required=True,type=asset)
    q.add_argument('--linear',action='store_true')
    for name in ('cook','render','build','demo'):
        q=sub.add_parser(name)
        if name=='demo':q.add_argument('--effect',choices=sorted(DEMOS),default='fountain')
        if name!='demo':q.add_argument('--asset',required=True,type=asset)
        if name in ('cook','render'):q.add_argument('--package',required=True,type=Path)
        if name=='cook':q.add_argument('--include',action='append',type=asset,default=[])
        if name!='cook':
            q.add_argument('--out',required=True,type=Path);q.add_argument('--cpu-vulkan',action='store_true')
            q.add_argument('--frames',type=int,default=60);q.add_argument('--warmup',type=int,default=16)
            q.add_argument('--width',type=int,default=512);q.add_argument('--height',type=int,default=512)
    args=p.parse_args()
    if not 1<=args.timeout<=7200:raise ValueError('timeout must be 1..7200')
    if args.command=='api':return {'ok':True,'schema':'ue-niagara-authoring-api/1',
        'operations':{name:{'required':['op',*fields]} for name,fields in operation_contract().items()},
        'inputModes':['float','int','bool','vec2','vec3','position','color','enum','struct','linked','dynamic-input','data-interface','object','expression'],
        'variableDefaults':['float','int','bool','vec2','vec3','position','color','enum','struct','data-interface','object'],
        'nativeSchemaQueries':['asset','system','emitter','renderer','data-interface','stage','module','dynamic-input','instance','input','stacks'],
        'scriptReferences':{'standard':'script enum name','eventAndSimulation':'script enum name + usageId GUID'},
        'assets':{'newEmitter':'add-emitter without asset/template','standaloneEmitter':'create --asset-kind emitter; read/edit auto-detect native class','reuseEmitter':'add-emitter with asset path','modules':'existing native Module Script assets, discovered by catalog'},
        'documents':{'schema':'ue-niagara-document/1','export':'export --asset /Game/... --out document.json',
                     'import':'import --file document.json','identity':'original package paths; import refuses collisions',
                     'preserves':['object graph','pins and links','scratch scripts','project Niagara dependencies','inheritance','package and editor metadata'],
                     'nativeData':'per-object current-build archive; properties are explicit text overlays; resource assets are checked attachments'},
        'execution':'UE native compiler and runtime; no standalone replacement VM',
        'nativePython':'Explicit script file using bundled unreal API; script owns save/transaction boundaries'}
    if args.command=='capabilities':return {'ok':True,'engine':engine_version(),'platform':PLATFORM,'nativeNiagara':True,
        'headlessEditorBundled':True,'withUnrealEd':True,'previewWithEditor':False,'create':'empty assets with optional existing-asset reuse',
        'emptyEmitterCreation':True,'emitterTemplatesRequired':False,'assignmentModules':True,
        'materialAuthoring':False,'existingMaterialBinding':True,'textureImport':True,
        'scriptStackIdentity':'usage + usageId','compilePolicies':['require-valid','allow-errors','defer'],
        'nativePythonAuthoring':True,'legacyDemos':list(DEMOS),'templateAssetsBundled':(ENGINE/'Plugins/FX/Niagara/Content/DefaultAssets/Templates').is_dir(),
        'demoSimTargets':{'gpu':'GPUComputeSim','ribbon':'CPUSim','mesh':'CPUSim','fountain':'CPUSim'},
        'serialization':['native uasset','ue-niagara-snapshot/1','ue-niagara-recipe/1','ue-niagara-document/1'],
        'limitations':['Snapshots describe native graphs; they are not a cross-engine particle format.',
                       'Plugin-specific assets require matching plugins. Scene-dependent interfaces need a supplied scene.',
                       'Renderer demos cover GPU Sprite and CPU Ribbon/Mesh; GPU Ribbon/Mesh and Fluids require separate qualification.']}
    if args.command=='render':path=project=None
    else:path,project=workspace(args.workspace)
    if args.command=='init':return {'ok':True,'workspace':str(path)}
    if args.command=='export':
        from document_io import export_document
        return export_document(backend_request,path,project,args.asset,args.out,args.timeout)
    if args.command=='import':
        from document_io import import_document
        return import_document(backend_request,path,project,args.file,args.timeout)
    if args.command=='native-python':
        return python_worker(path,project,'native_python_worker.py',args.timeout,{'file':str(args.file.resolve()),'params':load_json(args.params) if args.params else {}})
    if args.command=='import-assets':
        return python_worker(path,project,'assets_worker.py',args.timeout,{'operation':'import-assets','source':str(args.source.resolve())})
    if args.command in ('catalog','schema'):
        payload={k:v for k,v in vars(args).items() if k not in ('command','workspace','timeout','out') and v is not None}
        payload['operation']=args.command
        if args.command=='catalog' and (args.offset<0 or not 1<=args.limit<=5000):raise ValueError('Invalid catalog page')
        result=backend_request(path,project,payload,args.timeout)
        if args.out:write_json(args.out,result)
        return result
    if args.command in ('create','read','edit','save','compile'):
        fields={'compilePolicy':args.compilePolicy}
        if getattr(args,'recipe',None):fields['operations']=operations(args.recipe)
        if getattr(args,'template',None):fields['template']=args.template
        if getattr(args,'assetKind',None):fields['assetKind']=args.assetKind
        result=edit(path,project,args.command,args.asset,args.timeout,**fields)
        if args.out:write_json(args.out,result)
        return result
    if args.command=='import-texture':
        req={'operation':args.command,'asset':args.asset}
        req.update({'file':str(args.file.resolve()),'linear':args.linear})
        return python_worker(path,project,'assets_worker.py',args.timeout,req)
    if args.command=='cook':return cook(path,project,args.asset,args.package.resolve(),args.timeout,args.include)
    if not (1<=args.frames<=36000 and 1<=args.warmup<=4096 and 64<=args.width<=4096 and 64<=args.height<=4096):
        raise ValueError('Invalid simulation frame count or render size')
    out=args.out.resolve()
    if args.command=='demo':
        if not (ROOT/'examples'/DEMOS[args.effect]).is_file():
            raise ValueError('Legacy preset demos are not shipped in the template-free kit. Use catalog/schema and create/edit, or run the developer acceptance tool.')
        args.asset='/Game/NiagaraDemo/NS_'+args.effect.title()+'_'+uuid.uuid4().hex[:8]
        result=edit(path,project,'create',args.asset,args.timeout,operations=operations(ROOT/'examples'/DEMOS[args.effect]))
        write_json(out.with_suffix('.asset.json'),result)
    if args.command in ('build','demo'):
        package=out.parent/(out.stem+'-runtime');cook(path,project,args.asset,package,args.timeout)
    else:package=args.package.resolve()
    return render(package,args.asset,out,args.frames,args.warmup,args.width,args.height,args.cpu_vulkan,args.timeout)

if __name__=='__main__':
    try:print(json.dumps(main(),ensure_ascii=False,indent=2))
    except BackendFailure as exc:
        print(json.dumps(exc.result,ensure_ascii=False,indent=2));sys.exit(1)
    except (RuntimeError,ValueError,OSError,KeyError) as exc:
        print(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False,indent=2));sys.exit(1)
