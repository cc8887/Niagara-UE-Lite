"""Native UE texture and compatible existing-asset import."""
import json
import os
from pathlib import Path
import shutil
import re
import unreal as ue

def import_native_assets(q):
    """Preserve /Game package paths and reject collisions before writing files."""
    source=Path(q['source']).resolve()
    content=Path(ue.Paths.convert_relative_path_to_full(ue.Paths.project_content_dir())).resolve()
    if not source.is_dir():raise ValueError('Expected a Content-root directory')
    if source==content or source.is_relative_to(content) or content.is_relative_to(source):
        raise ValueError('Source and destination Content roots must be separate')
    packages=sorted(p for p in source.rglob('*') if p.is_file() and p.suffix.lower() in ('.uasset','.umap'))
    if not packages:raise ValueError('No native packages found')
    files={};package_names=[]
    for package in packages:
        relative=package.relative_to(source)
        if package.is_symlink() or not package.resolve().is_relative_to(source):raise ValueError('Package escapes source root')
        package_names.append('/Game/'+relative.with_suffix('').as_posix())
        for candidate in [package,*[package.with_suffix(s) for s in ('.uexp','.ubulk','.uptnl','.m.ubulk')]]:
            if not candidate.is_file():continue
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(source):raise ValueError('Sidecar escapes source root')
            rel=candidate.relative_to(source);dest=(content/rel).resolve()
            if not dest.is_relative_to(content):raise ValueError('Destination escapes Content root')
            if dest.exists():raise ValueError('Existing package/sidecar; overwrite refused: '+rel.as_posix())
            files[rel]=candidate
    installed=[]
    try:
        for relative,src in files.items():
            dest=content/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('xb') as output:
                installed.append(dest)
                with src.open('rb') as data:shutil.copyfileobj(data,output)
        registry=ue.AssetRegistryHelpers.get_asset_registry()
        registry.scan_files_synchronous([str(content/p.relative_to(source)) for p in packages],True)
        rows=[]
        for name in package_names:
            obj=ue.load_asset(name)
            if obj is None:raise RuntimeError('Native loader could not load '+name+'; supply matching engine/plugins and package dependencies')
            rows.append({'asset':obj.get_path_name(),'class':obj.get_class().get_path_name()})
        return {'ok':True,'packages':rows,'files':len(installed),'packagePathsPreserved':True,
                'nativeLoadValidated':True,'dependencyClosureSuppliedByCaller':True}
    except Exception:
        for path in reversed(installed):path.unlink(missing_ok=True)
        raise


def execute(q):
    if q['operation']=='import-assets':return import_native_assets(q)
    if q['operation']!='import-texture':raise ValueError('Unknown asset operation')
    target=q['asset'];folder,name=target.rsplit('/',1)
    if not re.fullmatch(r'/Game/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*',target):raise ValueError('Invalid /Game asset path')
    relative_folder=folder[len('/Game'):].lstrip('/')
    registry=ue.AssetRegistryHelpers.get_asset_registry()
    package_file=Path(ue.Paths.project_content_dir())/relative_folder/(name+'.uasset')
    if package_file.exists() or registry.get_assets_by_package_name(target):raise ValueError('Asset exists; overwrite refused')
    tools=ue.AssetToolsHelpers.get_asset_tools()
    if q['operation']=='import-texture':
        source=Path(q['file']).resolve()
        if source.suffix.lower()=='.uasset':
            if source.stem!=name:raise ValueError('Native package basename must be preserved')
            target_file=Path(ue.Paths.project_content_dir())/relative_folder/(name+'.uasset')
            target_file.parent.mkdir(parents=True,exist_ok=True);copied=[]
            try:
                for suffix in ('.uasset','.uexp','.ubulk'):
                    src=source.with_suffix(suffix);dst=target_file.with_suffix(suffix)
                    if dst.exists():raise ValueError('Destination package exists')
                    if src.exists():shutil.copyfile(src,dst);copied.append(dst)
                ue.AssetRegistryHelpers.get_asset_registry().scan_files_synchronous([str(target_file)],True)
                obj=ue.load_asset(target)
                if not isinstance(obj,ue.Texture2D):raise ValueError('Expected compatible uncooked UE 5.8.1 Texture2D')
            except Exception:
                for copied_file in copied:copied_file.unlink()
                raise
            return {'ok':True,'asset':obj.get_path_name(),'class':'Texture2D','saved':True,'nativePackageImported':True}
        if source.suffix.lower() not in ('.png','.jpg','.jpeg','.tga','.bmp','.exr','.hdr'):raise ValueError('Unsupported image format')
        dest=Path(ue.Paths.project_dir())/'SourceArt'/relative_folder/name/source.name
        if dest.exists():raise ValueError('Source art destination exists')
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        task=ue.AssetImportTask();task.filename=str(dest);task.destination_path=folder;task.destination_name=name
        task.automated=True;task.replace_existing=False;task.save=True;tools.import_asset_tasks([task])
        obj=ue.load_asset(target)
        if not isinstance(obj,ue.Texture2D):raise RuntimeError('TextureFactory did not produce Texture2D')
        obj.set_editor_property('srgb',not q.get('linear',False))
        data=obj.get_editor_property('asset_import_data')
        relative=os.path.relpath(dest,Path(ue.Paths.project_content_dir())/relative_folder)
        data.scripted_add_filename(relative,0,source.name)
    if not ue.EditorLoadingAndSavingUtils.save_packages([obj.get_outermost()],False):raise RuntimeError('Native save failed')
    return {'ok':True,'asset':obj.get_path_name(),'class':obj.get_class().get_name(),'saved':True}

try:
    request=json.loads(Path(os.environ['NIAGARA_ASSET_REQUEST']).read_text(encoding='utf-8'))
    result=execute(request)
except Exception as exc:
    result={'ok':False,'error':str(exc)}
Path(os.environ['NIAGARA_ASSET_RESPONSE']).write_text(json.dumps(result,indent=2),encoding='utf-8')
if not result['ok']:raise RuntimeError(result['error'])
