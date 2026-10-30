"""Native UE texture import and Niagara sprite-material authoring."""
import json
import os
from pathlib import Path
import shutil
import re
import unreal as ue

def execute(q):
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
    elif q['operation']=='create-material':
        tex=ue.load_asset(q['texture'])
        if not isinstance(tex,ue.Texture2D):raise ValueError('Expected native Texture2D asset')
        obj=tools.create_asset(name,folder,ue.Material,ue.MaterialFactoryNew())
        obj.set_editor_property('blend_mode',ue.BlendMode.BLEND_TRANSLUCENT)
        obj.set_editor_property('shading_model',ue.MaterialShadingModel.MSM_UNLIT)
        obj.set_editor_property('two_sided',True)
        obj.set_editor_property('used_with_niagara_sprites',True)
        m=ue.MaterialEditingLibrary
        sample=m.create_material_expression(obj,ue.MaterialExpressionTextureSample,-600,0)
        sample.set_editor_property('texture',tex)
        particle=m.create_material_expression(obj,ue.MaterialExpressionParticleColor,-600,220)
        color=m.create_material_expression(obj,ue.MaterialExpressionMultiply,-300,0)
        alpha=m.create_material_expression(obj,ue.MaterialExpressionMultiply,-300,220)
        assert m.connect_material_expressions(sample,'RGB',color,'A')
        assert m.connect_material_expressions(particle,'RGB',color,'B')
        assert m.connect_material_expressions(sample,'A',alpha,'A')
        assert m.connect_material_expressions(particle,'A',alpha,'B')
        assert m.connect_material_property(color,'',ue.MaterialProperty.MP_EMISSIVE_COLOR)
        assert m.connect_material_property(alpha,'',ue.MaterialProperty.MP_OPACITY)
        m.recompile_material(obj)
    else:raise ValueError('Unknown asset operation')
    if not ue.EditorLoadingAndSavingUtils.save_packages([obj.get_outermost()],False):raise RuntimeError('Native save failed')
    return {'ok':True,'asset':obj.get_path_name(),'class':obj.get_class().get_name(),'saved':True}

try:
    request=json.loads(Path(os.environ['NIAGARA_ASSET_REQUEST']).read_text(encoding='utf-8'))
    result=execute(request)
except Exception as exc:
    result={'ok':False,'error':str(exc)}
Path(os.environ['NIAGARA_ASSET_RESPONSE']).write_text(json.dumps(result,indent=2),encoding='utf-8')
if not result['ok']:raise RuntimeError(result['error'])
