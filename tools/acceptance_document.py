"""Native JSON export/import acceptance in independent workspaces.

Compares authored object properties, internal pin graphs and native extension
bytes, excluding only explicitly identified compilation-derived records/fields.
Optional paired Cook/render checks PNG bytes and exact particle counts.
"""
import argparse,hashlib,json,os,shutil,subprocess,time
from pathlib import Path

DERIVED={
    '/Script/Niagara.NiagaraSystem':{'ScriptRuntimeCompiledDataForEditor'},
    '/Script/NiagaraEditor.NiagaraGraph':{'ChangeId','LastBuiltTraversalDataChangeId'},
    '/Script/NiagaraEditor.NiagaraNodeFunctionCall':{'CachedChangeId'},
}
RUNTIME_REFERENCE='/Script/Niagara.NiagaraScriptRuntimeCompiledDataEditorReference'
DERIVED_NATIVE={'/Script/Niagara.NiagaraScript':'Native compiled/shader data regenerated; all nontransient reflected script properties still compared'}


def compare(before,after):
    if {r['package']:r for r in before['packages']}!={r['package']:r for r in after['packages']}:raise AssertionError('Package identity/metadata differs')
    def records(document):return {r['id']:r for r in document['objects'] if r['class']!=RUNTIME_REFERENCE}
    a,b=records(before),records(after)
    if a.keys()!=b.keys():raise AssertionError('Authored object identities differ: '+str(a.keys()^b.keys()))
    graphs=0;native_equal=0;properties=0
    for key,x in a.items():
        y=b[key]
        for field in ('class','outer','name','flags','archetype','graph'):
            if x.get(field)!=y.get(field):raise AssertionError('Object field mismatch: '+key+' '+field)
        if 'graph' in x:graphs+=1
        ignored=DERIVED.get(x['class'],set())
        xp={k:v for k,v in x['properties'].items() if k not in ignored};yp={k:v for k,v in y['properties'].items() if k not in ignored}
        if xp!=yp:raise AssertionError('Property mismatch: '+key+' '+str([k for k in xp if xp[k]!=yp.get(k)]))
        properties+=len(xp)
        if x['nativeSha256']==y['nativeSha256']:native_equal+=1
        elif x['class'] not in DERIVED and x['class'] not in DERIVED_NATIVE:raise AssertionError('Native extension mismatch: '+key)
    return {'authoredObjects':len(a),'pinGraphs':graphs,'properties':properties,'nativeBodiesIdentical':native_equal,
            'derivedFieldExclusions':{k:sorted(v) for k,v in DERIVED.items()},'derivedObjectExclusion':RUNTIME_REFERENCE,'derivedNativeBodies':DERIVED_NATIVE}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('kit','source-workspace','work-root','out'):p.add_argument('--'+key,required=True,type=Path)
    p.add_argument('--asset',action='append',required=True);p.add_argument('--render',action='store_true');p.add_argument('--cpu-vulkan',action='store_true');p.add_argument('--seed-ddc',type=Path)
    p.add_argument('--render-asset',action='append',default=[]);p.add_argument('--resume',action='store_true')
    a=p.parse_args();out=a.out.resolve();workroot=a.work_root.resolve()
    if not a.resume and (out.exists() or workroot.exists()):p.error('New evidence and workspace roots required; use --resume for retained step evidence')
    out.mkdir(parents=True,exist_ok=a.resume);workroot.mkdir(parents=True,exist_ok=a.resume);launcher=a.kit.resolve()/('niagara-cli.exe' if os.name=='nt' else 'niagara-cli')
    report={'schema':'niagara-document-acceptance/1','ok':False,'completed':False,'cases':[]};started=time.monotonic()
    def save():report['seconds']=round(time.monotonic()-started,3);(out/'report.json').write_text(json.dumps(report,indent=2))
    def call(work,label,*args):
        retained=out/(label+'.response.json')
        if a.resume and retained.is_file():
            prior=json.loads(retained.read_text(encoding='utf8'))
            if prior.get('ok'):print(label+' (retained)',flush=True);return prior
        result=subprocess.run([str(launcher),'--workspace',str(work),'--timeout','3600',*map(str,args)],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=7200)
        (out/(label+'.response.json')).write_text(result.stdout,encoding='utf8');(out/(label+'.stderr.log')).write_text(result.stderr,encoding='utf8')
        d=json.loads(result.stdout)
        if result.returncode or not d.get('ok'):raise RuntimeError(label+' failed; inspect evidence')
        print(label,flush=True);return d
    try:
        for i,asset in enumerate(a.asset):
            case={'asset':asset,'ok':False};report['cases'].append(case);dest=workroot/str(i);prefix=str(i)+'-'
            before=out/(prefix+'before.json');after=out/(prefix+'after.json')
            call(a.source_workspace,prefix+'export','export','--asset',asset,'--out',before)
            call(dest,prefix+'import','import','--file',before)
            call(dest,prefix+'reload','read','--asset',asset)
            call(dest,prefix+'reexport','export','--asset',asset,'--out',after)
            case['comparison']=compare(json.loads(before.read_text()),json.loads(after.read_text()));save()
            if a.render and (not a.render_asset or asset in a.render_asset):
                images=[];counts=[];paths=[];packages=[]
                for side,work in [('source',a.source_workspace),('restored',dest)]:
                    if a.seed_ddc and a.seed_ddc.resolve()!=(work/'DerivedDataCache').resolve():shutil.copytree(a.seed_ddc,work/'DerivedDataCache',dirs_exist_ok=True)
                    package=out/(prefix+side+'-runtime');image=out/(prefix+side+'.png')
                    call(work,prefix+side+'-cook','cook','--asset',asset,'--package',package)
                    args=['render','--asset',asset,'--package',package,'--frames','60','--warmup','16','--out',image]
                    if a.cpu_vulkan:args.append('--cpu-vulkan')
                    d=call(work,prefix+side+'-render',*args)
                    assert d['runtimeExitCode']==0 and d['particleCountExact'] and d['particleCount']>0 and d['nonZeroPixels']>0
                    images.append(image.read_bytes());counts.append(d['particleCount'])
                    paths.append(image);packages.append(package)
                if counts[0]!=counts[1]:raise AssertionError('Paired particle counts differ')
                from png_compare import difference
                delta=difference(*paths);controls=[]
                if not delta['decodedPixelsIdentical']:
                    for index,side in enumerate(('source','restored')):
                        for repeat in range(2):
                            image=out/(prefix+side+'-control-'+str(repeat)+'.png')
                            args=['render','--asset',asset,'--package',packages[index],'--frames','60','--warmup','16','--out',image]
                            if a.cpu_vulkan:args.append('--cpu-vulkan')
                            d=call(a.source_workspace if index==0 else dest,prefix+side+'-control-'+str(repeat),*args)
                            if d['particleCount']!=counts[index]:raise AssertionError('Repeated particle count differs')
                            controls.append(difference(paths[index],image))
                    max_limit=2*max(d['maxChannelDifference'] for d in controls)+1
                    mean_limit=max(2*max(d['meanAbsoluteChannelDifference'] for d in controls),1/delta['channels'])
                    if delta['maxChannelDifference']>max_limit or delta['meanAbsoluteChannelDifference']>mean_limit:raise AssertionError('Paired pixels exceed repeated-render baseline')
                case['render']={'pngIdentical':images[0]==images[1],'particles':counts[0],'pixelDifference':delta,'repeatControls':controls,
                                'sourceSha256':hashlib.sha256(images[0]).hexdigest(),'restoredSha256':hashlib.sha256(images[1]).hexdigest()}
            case['ok']=True;save()
        report.update(ok=True,completed=True)
    except BaseException as exc:report.update(completed=True,error=type(exc).__name__+': '+str(exc));raise
    finally:save()


if __name__=='__main__':main()
