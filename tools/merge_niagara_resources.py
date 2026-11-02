"""Restore omitted uncooked Niagara resources from a matching UE distribution.

Developer-only staging operation. Existing content must be byte-identical; never
overwrites a package or alters the reference engine. Reports contain relative paths.
"""
import argparse,hashlib,json,shutil
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference-engine',type=Path,required=True);p.add_argument('--kit',type=Path,required=True)
    p.add_argument('--apply',action='store_true');p.add_argument('--report',type=Path);a=p.parse_args()
    engine=a.reference_engine.resolve();kit=a.kit.resolve();target=kit/'backend/Engine'
    versions=[json.loads((r/'Build/Build.version').read_text()) for r in (engine,target)]
    for key in ('MajorVersion','MinorVersion','PatchVersion','Changelist'):
        if versions[0][key]!=versions[1][key]:p.error('Reference and kit UE versions must match exactly')
    if [versions[0][k] for k in ('MajorVersion','MinorVersion','PatchVersion')]!=[5,8,1]:p.error('UE 5.8.1 required')
    source=(engine/'Plugins/FX/Niagara/Content').resolve();dest=(target/'Plugins/FX/Niagara/Content').resolve()
    if not dest.is_relative_to(kit):p.error('Destination content must stay within the kit')
    if source==dest or source.is_relative_to(dest) or dest.is_relative_to(source):p.error('Separate reference engine and kit required')
    records=[];identical=0
    for file in sorted(source.rglob('*')):
        if not file.is_file() or file.suffix.lower() not in ('.uasset','.umap','.uexp','.ubulk','.uptnl'):continue
        relative=file.relative_to(source);output=dest/relative
        if file.is_symlink() or not file.resolve().is_relative_to(source.resolve()):raise ValueError('Reference escapes content root')
        if not output.resolve().is_relative_to(dest.resolve()):raise ValueError('Destination escapes content root')
        digest=hashlib.sha256(file.read_bytes()).hexdigest()
        if output.exists():
            if output.is_symlink() or hashlib.sha256(output.read_bytes()).hexdigest()!=digest:raise ValueError('Existing resource differs: '+relative.as_posix())
            identical+=1;continue
        records.append({'path':relative.as_posix(),'bytes':file.stat().st_size,'sha256':digest})
    installed=[]
    try:
        if a.apply:
            for row in records:
                output=dest/row['path'];output.parent.mkdir(parents=True,exist_ok=True)
                with output.open('xb') as stream:
                    installed.append(output)
                    with (source/row['path']).open('rb') as data:shutil.copyfileobj(data,stream)
                if hashlib.sha256(output.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Reference changed during copy')
    except Exception:
        for file in reversed(installed):file.unlink(missing_ok=True)
        raise
    report={'schema':'niagara-resource-supplement/1','applied':a.apply,'identicalExistingPackages':identical,
            'additionalBytes':sum(r['bytes'] for r in records),'packages':records}
    if a.report:a.report.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
