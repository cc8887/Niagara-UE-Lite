"""Validate JSON overlays, structural rejection, collision rejection and rollback."""
import argparse,copy,hashlib,json,os,shutil,subprocess
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('kit','document','work-root','out'):p.add_argument('--'+key,type=Path,required=True)
    a=p.parse_args();out=a.out.resolve();work=a.work_root.resolve()
    if out.exists() or work.exists():p.error('New evidence and workspace roots required')
    out.mkdir(parents=True);work.mkdir(parents=True);launcher=a.kit.resolve()/('niagara-cli.exe' if os.name=='nt' else 'niagara-cli')
    source=json.loads(a.document.read_text(encoding='utf8'))
    if source['resources']:shutil.copytree(a.document.parent/source['resourceDirectory'],out/source['resourceDirectory'])
    report={'ok':False,'checks':[]}
    def call(folder,label,*args,success=True):
        r=subprocess.run([str(launcher),'--workspace',str(folder),'--timeout','1200',*map(str,args)],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=1800)
        (out/(label+'.response.json')).write_text(r.stdout,encoding='utf8');(out/(label+'.stderr.log')).write_text(r.stderr,encoding='utf8');d=json.loads(r.stdout)
        assert (r.returncode==0 and d.get('ok') is True)==success,label
        report['checks'].append({'name':label,'passed':True});print(label,flush=True);return d
    def files(folder):return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (folder/'Content').rglob('*') if p.is_file()}
    try:
        folder=work/'rejections';call(folder,'init','init');original=files(folder)
        mutations={
            'corrupt-native':lambda d:d['objects'][0].update(nativeData='AAAA'),
            'missing-outer':lambda d:d['objects'][0].update(outer='/Game/Missing.Missing'),
            'duplicate-id':lambda d:d['objects'].append(copy.deepcopy(d['objects'][0])),
            'wrong-pin-graph':lambda d:next(r for r in d['objects'] if 'graph' in r)['graph'].update(nodeGuid='0'*32),
        }
        if source['resources']:
            mutations['corrupt-resource-hash']=lambda d:d['resources'][0].update(sha256='0'*64)
            mutations['resource-path-escape']=lambda d:d['resources'][0].update(path='../escape.uasset')
        for label,change in mutations.items():
            d=copy.deepcopy(source);change(d);file=out/(label+'.json');file.write_text(json.dumps(d))
            call(folder,label,'import','--file',file,success=False);assert files(folder)==original,'Failed import changed Content'
        edited=copy.deepcopy(source);root=next(r for r in edited['objects'] if r['id']==edited['asset'])
        root['properties']['TemplateAssetDescription'].update(text='INVTEXT("Edited through the JSON document")',apply=True)
        node=next(r for r in edited['objects'] if 'graph' in r and 'NodeComment' in r['properties'])
        node['properties']['NodeComment'].update(text='"JSON round-trip note"',apply=True)
        node['properties']['NodePosX'].update(text='321',apply=True)
        edited['packages'][0]['rootMetadata']['DocumentAcceptance']='round-trip metadata'
        file=out/'edited.json';file.write_text(json.dumps(edited));folder=work/'edited'
        call(folder,'edited-import','import','--file',file)
        after=out/'edited-reexport.json';call(folder,'edited-reexport','export','--asset',edited['package'],'--out',after)
        loaded=json.loads(after.read_text());rows={r['id']:r for r in loaded['objects']}
        assert 'Edited through the JSON document' in rows[edited['asset']]['properties']['TemplateAssetDescription']['text']
        assert rows[node['id']]['properties']['NodePosX']['text']=='321'
        assert 'JSON round-trip note' in rows[node['id']]['properties']['NodeComment']['text']
        assert loaded['packages'][0]['rootMetadata']['DocumentAcceptance']=='round-trip metadata'
        original=files(folder);call(folder,'collision-rejected','import','--file',file,success=False);assert files(folder)==original
        report['ok']=True
    finally:(out/'report.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':main()
