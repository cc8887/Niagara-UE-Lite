"""Validate the generic native authoring API with no effect-template resources.

The examples below are acceptance fixtures built through public operations, not
shipped emitter presets or an effect-name dispatch table in the product.
"""
import argparse,hashlib,json,os,subprocess,time
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('root','workspace','out'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--cpu-vulkan',action='store_true');parser.add_argument('--authoring-only',action='store_true')
    a=parser.parse_args();kit=a.root.resolve();work=a.workspace.resolve();out=a.out.resolve()
    if work.exists() or out.exists():parser.error('New workspace/evidence directories required')
    if (kit/'backend/Engine/Plugins/FX/Niagara/Content/DefaultAssets/Templates').exists():parser.error('Effect templates must be absent')
    out.mkdir(parents=True);win=os.name=='nt';launcher=kit/('niagara-cli.exe' if win else 'niagara-cli');started=time.monotonic()
    report={'schema':'niagara-template-free-acceptance/1','ok':False,'completed':False,'templatesAbsent':True,'steps':[],'renders':[],'visualInspection':False}
    env=os.environ.copy()
    for key in ('NIAGARA_LITE_ENGINE','NIAGARA_LITE_PROJECT','NIAGARA_LITE_RUNTIME_TEMPLATE','PYTHONPATH','PYTHONHOME'):env.pop(key,None)
    env['PYTHONNOUSERSITE']='1';env['PYTHONDONTWRITEBYTECODE']='1'
    def save():
        report['seconds']=round(time.monotonic()-started,3);(out/'report.json').write_text(json.dumps(report,indent=2))
    def call(label,*args):
        p=subprocess.run([str(launcher),'--workspace',str(work),'--timeout','3600',*map(str,args)],env=env,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=7200)
        (out/(label+'.json')).write_text(p.stdout,encoding='utf8');(out/(label+'.stderr.log')).write_text(p.stderr,encoding='utf8');d=json.loads(p.stdout)
        passed=p.returncode==0 and d.get('ok') is True;report['steps'].append({'name':label,'exitCode':p.returncode,'passed':passed});save()
        if not passed:raise RuntimeError(label+' failed; inspect evidence')
        print(label,flush=True);return d
    def recipe(label,operation,asset,ops,**kw):
        f=out/(label+'.recipe.json');f.write_text(json.dumps({'schema':'ue-niagara-recipe/1','operations':ops}))
        args=[operation,'--asset',asset,'--recipe',f]
        for k,v in kw.items():args.extend(['--'+k.replace('_','-'),v])
        return call(label,*args)
    cache={}
    def find(kind,search,name=None):
        key=(kind,search,name)
        if key not in cache:
            d=call('catalog-'+kind+'-'+search,'catalog','--kind',kind,'--search',search,'--limit','200')
            rows=[r for r in d['items'] if name is None or r['name'].casefold()==name.casefold()]
            if not rows:raise RuntimeError('Required native resource absent: '+search)
            cache[key]=rows[0]['asset']
        return cache[key]
    try:
        api=call('api','api');assert 'add-set-parameters' in api['operations']
        cap=call('capabilities','capabilities');assert cap['emitterTemplatesRequired'] is False and cap['templateAssetsBundled'] is False
        empty=recipe('empty','create','/Game/AIAcceptance/Empty',[{'op':'add-emitter','emitter':'Blank'}])
        e=empty['snapshot']['emitters'][0];assert not e['stacks']['hasParent'] and not e['renderers']
        for key in ('emitterSpawnScript','emitterUpdateScript','particleSpawnScript','particleUpdateScript'):assert not e['topology'][key]['modules']
        root='/Game/AIAcceptance/Independent'
        d=call('emitter-asset-create','create','--asset-kind','emitter','--asset',root);assert d['assetKind']=='emitter'
        recipe('emitter-asset-edit','edit',root,[{'op':'add-set-parameters','script':'ParticleSpawnScript','parameters':[{'name':'Particles.Color','type':'color','value':[0.2,0.5,1,1]}]}])
        call('emitter-asset-reload','read','--asset',root)
        modules={n:find('modules',n,n) for n in ('EmitterState','SpawnRate','ParticleState','SolveForcesAndVelocity')}
        systems=[]
        for kind in ('Sprite','Ribbon','Mesh'):
            asset='/Game/AIAcceptance/'+kind;systems.append(asset);em='Authored'
            params=[{'name':'Particles.Position','type':'position','value':[0,0,0]},{'name':'Particles.Color','type':'color','value':[0.1,0.6,1,1]},
                    {'name':'Particles.Age','type':'float','value':0},{'name':'Particles.NormalizedAge','type':'float','value':0},
                    {'name':'Particles.Lifetime','type':'float','value':4},{'name':'Particles.Mass','type':'float','value':1},
                    {'name':'Particles.Velocity','type':'vec3','value':[0,0,150]}]
            properties={}
            if kind=='Sprite':
                params += [{'name':'Particles.SpriteSize','type':'vec2','value':[15,15]}];properties['Material']=find('materials','DefaultSpriteMaterial')
            elif kind=='Ribbon':
                params += [{'name':'Particles.RibbonWidth','type':'float','value':12},{'name':'Particles.RibbonLinkOrder','type':'float','value':0}];properties['Material']=find('materials','DefaultRibbonMaterial')
            else:
                params += [{'name':'Particles.Scale','type':'vec3','value':[0.15,0.15,0.15]},{'name':'Particles.MeshOrientation','type':'struct','struct':'/Script/CoreUObject.Quat4f','value':{'x':0,'y':0,'z':0,'w':1}}]
                properties={'Meshes':[{'mesh':find('meshes','S_Gnomon','S_Gnomon'),'scale':{'x':2,'y':2,'z':2}}],
                            'bOverrideMaterials':True,'OverrideMaterials':[{'explicitMat':find('materials','M_Gnomon_Alpha','M_Gnomon_Alpha')}]}
            ops=[{'op':'add-emitter','emitter':em},{'op':'emitter-properties','emitter':em,'properties':{'bDeterminism':True,'RandomSeed':2026}},
                 {'op':'add-renderer','emitter':em,'class':'/Script/Niagara.Niagara'+kind+'RendererProperties'},
                 {'op':'renderer-properties','emitter':em,'renderer':0,'properties':properties}]
            if kind=='Sprite':ops[1]['properties'].update(SimTarget='GPUComputeSim',CalculateBoundsMode='Fixed',FixedBounds={'min':{'x':-200,'y':-200,'z':-100},'max':{'x':200,'y':200,'z':350},'isValid':True})
            for script,n in [('EmitterUpdateScript','EmitterState'),('EmitterUpdateScript','SpawnRate'),('ParticleUpdateScript','ParticleState'),('ParticleUpdateScript','SolveForcesAndVelocity')]:ops.append({'op':'add-module','emitter':em,'script':script,'asset':modules[n]})
            ops += [{'op':'input','emitter':em,'script':'EmitterUpdateScript','module':'SpawnRate','input':'SpawnRate','type':'float','value':32 if kind=='Mesh' else 100},
                    {'op':'add-set-parameters','emitter':em,'script':'ParticleSpawnScript','parameters':params}]
            assert all(not o.get('template') and not (o['op']=='add-emitter' and o.get('asset')) for o in ops)
            d=recipe('create-'+kind,'create',asset,ops);assert not d['snapshot']['emitters'][0]['stacks']['hasParent']
            module=d['snapshot']['emitters'][0]['topology']['particleSpawnScript']['modules'][0]['moduleName']
            expression='float(Particles.UniqueID)' if kind=='Ribbon' else 'float3(55*cos(Particles.UniqueID*2.399963),55*sin(Particles.UniqueID*2.399963),0.0)'
            recipe('expression-'+kind,'edit',asset,[{'op':'input','emitter':em,'script':'ParticleSpawnScript','module':module,'input':'Particles.RibbonLinkOrder' if kind=='Ribbon' else 'Particles.Position','type':'expression','value':expression}])
            loaded=call('reload-'+kind,'read','--asset',asset)
            assert '/DefaultAssets/Templates/' not in json.dumps(loaded['snapshot']['staticDependencies'])
        if not a.authoring_only:
            package=out/'runtime';args=['cook','--asset',systems[0],'--package',package]
            for asset in systems[1:]:args += ['--include',asset]
            call('cook',*args)
            for asset in systems:
                name=asset.rsplit('/',1)[1];image=out/(name+'.png');args=['render','--asset',asset,'--package',package,'--frames','60','--out',image]
                if a.cpu_vulkan:args+=['--cpu-vulkan']
                d=call('render-'+name,*args)
                assert d['runtimeExitCode']==0 and d['imageSaved'] and d['nonZeroPixels']>0 and d['particleCountExact'] and d['particleCount']>0
                assert not d['withEditor'] and not d['niagaraEditorLoaded'] and not d['unrealEdLoaded']
                report['renders'].append({'name':name,'rhi':d['rhi'],'adapter':d.get('adapter'),'particles':d['particleCount'],'maxRGB':d['maxRGB'],'image':image.name,'sha256':hashlib.sha256(image.read_bytes()).hexdigest()})
        report.update(ok=True,completed=True)
    except Exception as exc:report.update(completed=True,error=type(exc).__name__+': '+str(exc));raise
    finally:save()


if __name__=='__main__':main()
