"""Real native process/save/reload checks. No image claims from this script."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
import uuid

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path)
    p.add_argument('--workspace',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    a=p.parse_args();root=a.root.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    script=root/('scripts' if (root/'scripts').is_dir() else 'tools')/'niagara_cli.py'
    python=sys.executable
    if (root/'backend').exists():
        python=str(root/('backend/Engine/Binaries/ThirdParty/Python3/Win64/python.exe' if os.name=='nt' else 'backend/Engine/Binaries/ThirdParty/Python3/Linux/bin/python3'))
    prefix=[python,str(script),'--workspace',str(a.workspace),'--timeout','1800']
    cases=[]
    def run(name,*args,success=True):
        proc=subprocess.run(prefix+list(args),capture_output=True,text=True,encoding='utf-8',errors='replace')
        (out/(name+'.stdout.json')).write_text(proc.stdout,encoding='utf-8')
        (out/(name+'.stderr.log')).write_text(proc.stderr,encoding='utf-8')
        try:result=json.loads(proc.stdout)
        except json.JSONDecodeError:
            if success:raise
            result={'ok':False,'argumentError':proc.stderr}
        passed=(proc.returncode==0 and result.get('ok') is True)==success
        cases.append({'name':name,'passed':passed,'expectedSuccess':success,'exitCode':proc.returncode})
        if not passed:raise AssertionError(name+': '+proc.stdout[-1500:])
        return result
    name='/Game/Acceptance/NS_'+uuid.uuid4().hex[:8]
    run('create','create','--asset',name,'--recipe',str(root/'examples/fountain.json'))
    first=run('read','read','--asset',name)
    def value(result,module,input_name):
        return next(i['value']['data'] for e in result['snapshot']['emitters'] for m in e['moduleInputs']
                    if m['moduleName']==module for i in m['inputs'] if i['name']==input_name)
    assert value(first,'SpawnRate','SpawnRate')['value']==90
    changed=run('edit','edit','--asset',name,'--recipe',str(root/'examples/fountain-orange.json'))
    assert changed['saved'] and changed['backup']
    second=run('reload','read','--asset',name)
    assert value(second,'SpawnRate','SpawnRate')['value']==240
    assert abs(value(second,'InitializeParticle','Color')['g']-0.12)<0.001
    run('save','save','--asset',name)
    run('compile','compile','--asset',name)
    run('reject-duplicate','create','--asset',name,success=False)
    invalid=out/'bad-edit.json';invalid.write_text(json.dumps({'schema':'ue-niagara-recipe/1','operations':[
        {'op':'input','emitter':'Fountain','script':'EmitterUpdateScript','module':'SpawnRate','input':'SpawnRate','type':'float','value':5},
        {'op':'remove-emitter','emitter':'DefinitelyMissingEmitter'}]}))
    project=Path(os.environ.get('NIAGARA_LITE_PROJECT',a.workspace/'NiagaraStandalone.uproject')).parent
    file=project/'Content'/Path(name.removeprefix('/Game/')).with_suffix('.uasset')
    before=hashlib.sha256(file.read_bytes()).hexdigest()
    run('reject-bad-edit','edit','--asset',name,'--recipe',str(invalid),success=False)
    assert hashlib.sha256(file.read_bytes()).hexdigest()==before
    assert value(run('reload-after-rejection','read','--asset',name),'SpawnRate','SpawnRate')['value']==240
    run('reject-path','create','--asset','/Game/../Escape',success=False)
    report={'ok':True,'cases':cases,'asset':name,'nativeSaveReload':True,'failedEditPreservedPackage':True,
            'visualValidation':False,'simulationValidation':False}
    (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

if __name__=='__main__':main()
