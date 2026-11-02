"""Exercise general native Niagara composition through an extracted kit's CLI.

Uses new workspaces; keeps detailed native responses outside the source tree.
Does not claim qualification of every discoverable module or plugin.
"""
import argparse,hashlib,json,os,shutil,subprocess,time
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True,type=Path);p.add_argument('--workspace',required=True,type=Path)
    p.add_argument('--out',required=True,type=Path);p.add_argument('--cpu-vulkan',action='store_true')
    a=p.parse_args();kit=a.root.resolve();work=a.workspace.resolve();out=a.out.resolve()
    if work.exists() or out.exists():p.error('New workspace and evidence directories required')
    out.mkdir(parents=True);win=os.name=='nt';launcher=kit/('niagara-cli.exe' if win else 'niagara-cli')
    env=os.environ.copy()
    for name in ('NIAGARA_LITE_ENGINE','NIAGARA_LITE_PROJECT','NIAGARA_LITE_RUNTIME_TEMPLATE','PYTHONPATH','PYTHONHOME'):env.pop(name,None)
    env['PYTHONNOUSERSITE']='1';env['PYTHONDONTWRITEBYTECODE']='1'
    system='/Game/General/Composition';steps=[];started=time.monotonic()
    report={'schema':'niagara-general-acceptance/1','ok':False,'completed':False,'platform':'Windows' if win else 'Linux',
            'newWorkspace':True,'publicLauncherUsed':True,'steps':steps,'visualInspection':False}
    def save():
        report['wallSeconds']=round(time.monotonic()-started,3)
        (out/'report.json').write_text(json.dumps(report,indent=2))
    def run(name,*args,workspace=work,expected=True):
        r=subprocess.run([str(launcher),'--workspace',str(workspace),'--timeout','1800',*map(str,args)],env=env,
                         capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=7200)
        (out/(name+'.json')).write_text(r.stdout,encoding='utf-8');(out/(name+'.stderr.log')).write_text(r.stderr,encoding='utf-8')
        d=json.loads(r.stdout);passed=(r.returncode==0 and d.get('ok') is True)
        steps.append({'name':name,'processExitCode':r.returncode,'expectedSuccess':expected,'passed':passed==expected});save()
        if passed!=expected:raise RuntimeError(name+' did not satisfy expected result; inspect evidence')
        print(name,flush=True);return d
    def edit(name,ops):
        f=out/(name+'.recipe.json');f.write_text(json.dumps({'schema':'ue-niagara-recipe/1','operations':ops}))
        return run(name,'edit','--asset',system,'--recipe',f)
    def schema(name,module,input_path=None,script='ParticleUpdateScript',emitter='Dust'):
        args=['schema','--kind','input' if input_path else 'instance','--asset',system,'--emitter',emitter,'--script',script,'--module',module]
        if input_path:args+=['--inputs',*input_path]
        return run(name,*args)
    def inp(module,path,kind,value,script='ParticleUpdateScript',**extra):
        return dict(op='input',emitter='Dust',script=script,module=module,inputs=path,type=kind,value=value,**extra)
    try:
        for kind,search in [('emitters','Confetti'),('modules','Gravity'),('dynamic-inputs','FixedSeed'),('renderers',''),('data-interfaces','Texture')]:
            d=run('catalog-'+kind,'catalog','--kind',kind,'--search',search);assert d['total']>0
        recipe=out/'create.recipe.json'
        recipe.write_text(json.dumps({'schema':'ue-niagara-recipe/1','operations':[
            {'op':'add-emitter','emitter':'Confetti','template':'/Niagara/DefaultAssets/Templates/Emitters/ConfettiBurst.ConfettiBurst'},
            {'op':'add-emitter','emitter':'Dust','template':'/Niagara/DefaultAssets/Templates/Emitters/Minimal.Minimal'},
            {'op':'emitter-properties','emitter':'Confetti','properties':{'bDeterminism':True,'RandomSeed':1337}},
            {'op':'set-user','name':'User.Gravity','type':'vec3','value':[0,0,-120]}]}))
        created=run('create','create','--asset',system,'--recipe',recipe)
        dust=next(e['topology'] for e in created['snapshot']['emitters'] if e['topology']['emitterName']=='Dust')
        if not any(m['moduleName']=='SpawnRate' for m in dust['emitterUpdateScript']['modules']):
            edit('add-spawn-rate',[{'op':'add-module','emitter':'Dust','script':'EmitterUpdateScript','asset':'/Niagara/Modules/Emitter/SpawnRate.SpawnRate'}])
        edit('add-gravity',[{'op':'add-module','emitter':'Dust','script':'ParticleUpdateScript','asset':'/Niagara/Modules/Update/Forces/GravityForce.GravityForce','after':'ParticleState'},
                           {'op':'add-module','emitter':'Dust','script':'ParticleUpdateScript','asset':'/Niagara/Modules/Solvers/SolveForcesAndVelocity.SolveForcesAndVelocity'},
                           inp('GravityForce',['Gravity'],'linked','User.Gravity')])
        before=schema('before-move','GravityForce');original=before['moduleIndex'];destination=0 if original else 1
        edit('move',[{'op':'move-module','emitter':'Dust','script':'ParticleUpdateScript','module':'GravityForce','index':destination}])
        after=schema('after-move','GravityForce');assert before['nodeGuid']==after['nodeGuid'] and after['moduleIndex']==destination
        assert before['values']==after['values'];report['moduleIdentityAndInputsPreserved']=True
        edit('restore-order',[{'op':'move-module','emitter':'Dust','script':'ParticleUpdateScript','module':'GravityForce','index':original}])
        edit('duplicate-rename-remove',[{'op':'duplicate-emitter','emitter':'Dust','name':'Temporary'},
              {'op':'rename-emitter','emitter':'Temporary','name':'Renamed'}, {'op':'remove-emitter','emitter':'Renamed'}])
        edit('dynamic',[inp('SpawnRate',['SpawnRate'],'dynamic-input','/Niagara/DynamicInputs/Random/FixedSeedRandomFloat.FixedSeedRandomFloat','EmitterUpdateScript'),
              inp('SpawnRate',['SpawnRate','Seed'],'float',7,'EmitterUpdateScript'),inp('SpawnRate',['SpawnRate','Range'],'vec2',[40,60],'EmitterUpdateScript')])
        d=schema('dynamic-range','SpawnRate',['SpawnRate','Range'],'EmitterUpdateScript');assert d['value']['data']=={'x':40,'y':60}
        edit('curve',[inp('SpawnRate',['SpawnRate'],'dynamic-input','/Niagara/DynamicInputs/ValueFromCurve/FloatFromCurve.FloatFromCurve','EmitterUpdateScript'),
              inp('SpawnRate',['SpawnRate','FloatCurve'],'data-interface',{'curve':{'defaultValue':50,'keys':[]},'bUseLUT':True},'EmitterUpdateScript')])
        d=schema('curve-reload','SpawnRate',['SpawnRate','FloatCurve'],'EmitterUpdateScript')
        assert json.loads(d['value']['data']['propertyValues'])['Curve']['defaultValue']==50
        d=schema('enum-schema','InitializeParticle',['Lifetime Mode'],'ParticleSpawnScript','Confetti')
        value=d['value']['data']['enumName']
        edit('enum',[dict(op='input',emitter='Confetti',script='ParticleSpawnScript',module='InitializeParticle',inputs=['Lifetime Mode'],type='enum',value=value)])
        d=schema('enum-reload','InitializeParticle',['Lifetime Mode'],'ParticleSpawnScript','Confetti');assert d['value']['data']['enumName']==value
        file=work/'Content/General/Composition.uasset';digest=hashlib.sha256(file.read_bytes()).hexdigest()
        bad=out/'bad.recipe.json';bad.write_text(json.dumps({'schema':'ue-niagara-recipe/1','operations':[{'op':'move-module','emitter':'Dust','script':'ParticleUpdateScript','module':'GravityForce','index':99999}]}))
        run('reject-invalid-index','edit','--asset',system,'--recipe',bad,expected=False);assert hashlib.sha256(file.read_bytes()).hexdigest()==digest
        incoming=out/'incoming/Content/General';incoming.mkdir(parents=True)
        for f in file.parent.glob('Composition.*'):shutil.copyfile(f,incoming/f.name)
        # Windows UE filesystem DDC requires a root <=119 characters. Keep this
        # auxiliary workspace beside the main workspace, outside deep evidence paths.
        imported=work.with_name(work.name+'-import')
        run('import','import-assets','--source',incoming.parent,workspace=imported)
        d=run('import-reload','read','--asset',system,workspace=imported);assert d['snapshot']['valid']
        run('compile','compile','--asset',system);run('reload','read','--asset',system)
        package=out/'runtime';run('cook','cook','--asset',system,'--package',package)
        args=['render','--asset',system,'--package',package,'--frames','60','--warmup','16','--out',out/'composition.png']
        if a.cpu_vulkan:args+=['--cpu-vulkan']
        d=run('render',*args)
        assert d['runtimeExitCode']==0 and d['imageSaved'] and d['nonZeroPixels']>0 and d['particleCount']>0
        assert not d['withEditor'] and not d['niagaraEditorLoaded'] and not d['unrealEdLoaded']
        report.update(ok=True,completed=True,render={'rhi':d['rhi'],'adapter':d.get('adapter'),'maxRGB':d['maxRGB'],
                        'particles':d['particleCount'],'image':'composition.png'},nativeAssetImportReload=True)
    except Exception as exc:
        report.update(completed=True,error=type(exc).__name__+': '+str(exc));raise
    finally:save()


if __name__=='__main__':main()
