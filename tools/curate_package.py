"""Apply program/resource allowlists and split optional DDC into a new kit."""
from pathlib import Path
import argparse,hashlib,json,os,re,tarfile,zipfile
from package_support import copy

ROOT=Path(__file__).resolve().parents[1]
PROGRAMS={'UnrealEditor','ShaderCompileWorker','UnrealPak'}
RESOURCE_CANDIDATES={'VREditor','Tutorial','FbxEditorAutomation','MapTemplates','StarterContent'}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def program_family(rel):
    if not rel.startswith('backend/Engine/Binaries/'):return None
    if '/ThirdParty/' in rel:return None
    name=Path(rel).name
    match=re.match(r'(?:lib)?(Unreal[^-.]+|ShaderCompileWorker)(?:[-.]|$)',name)
    return match.group(1) if match else None

def package_path(rel):
    prefix='backend/Engine/Content/'
    if rel.startswith(prefix) and Path(rel).suffix in ('.uasset','.umap'):
        return '/Engine/'+str(Path(rel.removeprefix(prefix)).with_suffix('')).replace('\\','/')
    return None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--dependencies',type=Path,required=True,help='Native AssetRegistry dependency inventory')
    a=p.parse_args();source=a.source.resolve();dest=a.out.resolve()
    if dest.exists() or dest==source or dest.is_relative_to(source) or source.is_relative_to(dest):
        raise ValueError('Use a new, separate output tree')
    manifest=json.loads((source/'package-manifest.json').read_text())
    inventory=json.loads(a.dependencies.read_text())
    if not inventory.get('ok'):raise ValueError('Dependency collection did not succeed')
    if inventory.get('sourceManifestSha256')!=digest(source/'package-manifest.json'):
        raise ValueError('Dependency inventory belongs to a different source kit')
    if inventory.get('nativeRootPolicyVersion',0)<1 or not inventory.get('mandatoryNativeRootCoverageComplete'):
        raise ValueError('Dependency inventory does not cover qualified native startup roots')
    # Inventory format is intentionally explicit: never infer removability from
    # a missing field or an empty/broken scan.
    packages=set(inventory['packages'])
    if not packages or not any(x.startswith('/Niagara/')for x in packages):
        raise ValueError('Expected complete Niagara dependency roots')
    if '/Engine/VREditor/ViewportInteractionAssetContainerData' not in packages:
        raise ValueError('Inventory must include the native editor startup asset closure')
    platform=manifest['platform'];dest.mkdir(parents=True)
    kept=[];removed=[];ddc=[]
    for record in sorted(manifest['records'],key=lambda r:r['path']):
        rel=record['path'];src=(source/rel).resolve();target=dest/rel
        if not src.is_relative_to(source)or not target.resolve().is_relative_to(dest):raise ValueError('Path escapes kit')
        if digest(src)!=record['sha256']:raise ValueError('Source integrity failure: '+rel)
        reason=None;family=program_family(rel)
        if rel.startswith('cache/'):ddc.append(record);continue
        if family and family not in PROGRAMS:reason='program_not_allowlisted'
        prefix='backend/Engine/Content/'
        if rel.startswith(prefix):
            folder=rel.removeprefix(prefix).split('/')[0]
            pkg=package_path(rel)
            if folder in RESOURCE_CANDIDATES and pkg and pkg not in packages:
                reason='unreferenced_optional_engine_asset'
        if reason:removed.append({'path':rel,'bytes':record['bytes'],'reason':reason});continue
        target.parent.mkdir(parents=True,exist_ok=True)
        if platform=='Linux' and record.get('hardlinkTo'):
            canonical=(dest/record['hardlinkTo']).resolve()
            if not canonical.is_relative_to(dest) or not canonical.is_file():
                raise ValueError('Invalid retained hardlink target')
            if canonical.stat().st_size!=record['bytes'] or digest(canonical)!=record['sha256']:
                raise ValueError('Retained hardlink target integrity mismatch')
            os.link(canonical,target)
        else:copy(src,target)
        kept.append(rel)
    for name in ('README.md',):copy(ROOT/name,dest/name)
    for folder in ('docs','examples'):
        for src in (ROOT/folder).rglob('*'):
            if src.is_file():
                rel=src.relative_to(ROOT).as_posix();copy(src,dest/rel)
                if rel not in kept:kept.append(rel)
    for name in ('niagara_cli.py','assets_worker.py','author_preview.py','vulkan_probe.py'):
        copy(ROOT/'tools'/name,dest/'scripts'/name)
    inventory_name='resource-inventory.json'
    copy(a.dependencies,dest/inventory_name)
    kept.append(inventory_name)
    name='Niagara-UE-Lite-Standalone-UE5.8.1-'+platform+'-x86_64'
    (dest.parent/(name+'-file-list.json')).write_text(json.dumps(sorted(kept),indent=2)+'\n')
    # Cache is a separate, platform-specific optional download. Extracting it at
    # kit root restores the existing cache/ discovery on new workspace init.
    cache_name='Niagara-UE-Lite-DDC-UE5.8.1-'+platform+'-x86_64'
    archive=dest.parent/(cache_name+('.zip'if platform=='Windows'else'.tar.gz'))
    if archive.exists():raise ValueError('Optional DDC archive exists')
    if platform=='Windows':
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6)as z:
            for r in ddc:z.write(source/r['path'],r['path'])
    else:
        with tarfile.open(archive,'w:gz',compresslevel=6)as t:
            for r in ddc:
                src=source/r['path'];info=t.gettarinfo(str(src),arcname=r['path'])
                info.uid=info.gid=0;info.uname=info.gname='root'
                with src.open('rb')as stream:t.addfile(info,stream)
    cache_meta={'schema':'niagara-optional-ddc/1','engine':'UE5.8.1','platform':platform,
                'sourceKitManifestSha256':digest(source/'package-manifest.json'),
                'archive':archive.name,'archiveBytes':archive.stat().st_size,'sha256':digest(archive),
                'files':len(ddc),'payloadBytes':sum(r['bytes']for r in ddc),'records':ddc}
    (archive.parent/(archive.name+'.json')).write_text(json.dumps(cache_meta,indent=2)+'\n')
    report={'schema':'niagara-curated-package/1','platform':platform,'removed':removed,
            'removedBytes':sum(r['bytes']for r in removed),'optionalDdcBytes':sum(r['bytes']for r in ddc),
            'optionalDdcArchive':archive.name,'optionalDdcArchiveBytes':archive.stat().st_size,
            'optionalDdcSha256':digest(archive),'dependencyPackages':len(packages),
            'sourceKitManifestSha256':digest(source/'package-manifest.json'),
            'inventorySha256':digest(a.dependencies),'baselineMissingDependencies':inventory.get('missingDependencies',[]),
            'retainedEngineAssetPolicy':'All except unreferenced optional candidate directories',
            'programAllowlist':sorted(PROGRAMS)}
    (dest.parent/(platform.lower()+'-curation.json')).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items()if k!='removed'}),flush=True)

if __name__=='__main__':main()
