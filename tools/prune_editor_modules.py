"""Create an explicitly scoped editor-module/target-platform package candidate.

Static incoming dependencies fail closed. Dynamic loading and asset operations
must still be qualified on each final extracted archive before publishing.
"""
import argparse
from pathlib import Path
import hashlib,json,os,re,struct
from package_support import copy

UI_CANDIDATES={'MainFrame','Persona','AnimationBlueprintEditor','AnimationEditor',
 'PhysicsAssetEditor','SkeletonEditor','SkeletalMeshEditor','MirrorDataTableEditor',
 'TraceInsights','SettingsEditor','DeviceProfileEditor','EditorSettingsViewer',
 'InputBindingSettingsViewer','ProjectSettingsViewer','InputBindingEditor',
 'AutomationWindow','DeviceManager','SessionFrontend','LegacyProjectLauncher',
 'LocalizationDashboard','MergeActors','UndoHistory','UndoHistoryEditor','PackagesDialog','CSVtoSVG',
 'RenderResourceViewer','DerivedDataEditor','ZenEditor','GameplayDebuggerEditor'}


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def elf_imports(path):
    with path.open('rb') as f:
        header=f.read(64)
        if not header.startswith(b'\x7fELF'):return None
        if header[4:6]!=b'\x02\x01':raise ValueError('Expected ELF64 little endian')
        h=struct.unpack('<16sHHIQQQIHHHHHH',header)
        f.seek(h[6]);data=f.read(h[11]*h[12])
        sections=[struct.unpack('<IIQQQQIIQQ',data[i*h[11]:i*h[11]+64]) for i in range(h[12])]
        dynamic=[s for s in sections if s[1]==6]
        if not dynamic:return []
        if len(dynamic)!=1:raise ValueError('Ambiguous ELF dynamic section')
        d=dynamic[0];strings=sections[d[6]];f.seek(strings[4]);names=f.read(strings[5])
        f.seek(d[4]);raw=f.read(d[5]);result=[]
        for i in range(0,len(raw),16):
            tag,value=struct.unpack('<qQ',raw[i:i+16])
            if tag==1:result.append(names[value:].split(b'\0',1)[0].decode())
        return result


def pe_imports(path):
    if path.suffix.lower() not in {'.dll','.exe','.pyd'}:return None
    import pefile
    pe=pefile.PE(str(path),fast_load=True)
    try:
        pe.parse_data_directories(directories=[1,13])
        return [d.dll.decode().lower() for attr in ('DIRECTORY_ENTRY_IMPORT','DIRECTORY_ENTRY_DELAY_IMPORT') for d in getattr(pe,attr,[])]
    finally:pe.close()


def module(path):
    m=re.search(r'(?:lib)?(?:UnrealEditor|ShaderCompileWorker)-([^.\/]+)\.(?:dll|so)$',path)
    return m.group(1) if m else None


def reason(path,platform):
    if path=='scripts/author_preview.py':return 'replaced_by_native_preview_commandlet'
    if path.startswith('backend/Engine/Plugins/Editor/EditorScriptingUtilities/'):
        return 'asset_services_replaced_plugin_disabled'
    n=module(path)
    if n in UI_CANDIDATES:return 'unused_editor_ui_candidate'
    if n:
        other=('Android','IOS','TVOS','VisionOS','Mac', 'Linux' if platform=='Windows' else 'Windows')
        if any(n.startswith(p+suffix) for p in other for suffix in ('TargetPlatform','PlatformEditor')):return 'other_target_platform'
        formats={'MetalShaderFormat','ShaderFormatOpenGL', 'VulkanShaderFormat' if platform=='Windows' else 'ShaderFormatD3D'}
        if n in formats:return 'other_target_shader_format'
    if Path(path).name.lower() in {'metalirconverter.dll','libmetalirconverter.so'}:
        return 'metal_only_converter_candidate'
    return None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--out',type=Path)
    p.add_argument('--report',required=True,type=Path)
    a=p.parse_args();source=a.source.resolve()
    if a.out:
        dest=a.out.resolve()
        if dest.exists() or dest.is_relative_to(source) or source.is_relative_to(dest):raise ValueError('New separate destination required')
    original=json.loads((source/'package-manifest.json').read_text());platform=original['platform']
    records=original['records'];candidates={r['path']:reason(r['path'],platform) for r in records if reason(r['path'],platform)}
    imports={};libraries={}
    for r in records:
        rel=r['path'];path=(source/rel).resolve()
        if not path.is_relative_to(source) or sha(path)!=r['sha256']:raise ValueError('Source integrity/path failure '+rel)
        library=(path.suffix.lower() in {'.dll','.exe','.pyd'}) if platform=='Windows' else ('.so' in path.name or bool(path.stat().st_mode&0o111))
        if not library:continue
        values=pe_imports(path) if platform=='Windows' else elf_imports(path)
        if values is not None:
            imports[rel]=[v.lower() if platform=='Windows' else v for v in values]
            basename=path.name.lower() if platform=='Windows' else path.name
            libraries.setdefault(basename,[]).append(rel)
    removable=set(candidates);blocked={}
    while True:
        denied={}
        for rel,values in imports.items():
            if rel in removable:continue
            for value in values:
                for dependency in libraries.get(value,[]):
                    if dependency in removable:denied.setdefault(dependency,[]).append(rel)
        if not denied:break
        for rel,users in denied.items():blocked[rel]=users
        removable-=denied.keys()
    report={'schema':'niagara-editor-module-pruning/1','platform':platform,'qualified':False,
            'sourceManifestSha256':sha(source/'package-manifest.json'),
            'removed':[{'path':r['path'],'bytes':r['bytes'],'reason':candidates[r['path']]} for r in records if r['path'] in removable],
            'blockedByStaticImports':blocked,'nativeLibrariesScanned':len(imports),
            'importEvidence':'PE imports plus delay imports' if platform=='Windows' else 'ELF DT_NEEDED',
            'retainedNamedModules':[n for n in ('MainFrame','Persona','Sequencer','GraphEditor') if any(module(r['path'])==n and r['path'] not in removable for r in records)]}
    report['removedBytes']=sum(r['bytes'] for r in report['removed'])
    if a.out:
        dest.mkdir(parents=True);kept=[]
        for r in records:
            rel=r['path']
            if rel in removable:continue
            target=dest/rel
            if not target.resolve().is_relative_to(dest):raise ValueError('Output path escapes kit')
            if r.get('hardlinkTo'):
                canonical=(dest/r['hardlinkTo']).resolve()
                if not canonical.is_relative_to(dest) or not canonical.is_file():raise ValueError('Removed hardlink canonical requires explicit migration')
                target.parent.mkdir(parents=True,exist_ok=True);os.link(canonical,target)
            else:copy(source/rel,target)
            if target.suffix=='.modules':
                metadata=json.loads(target.read_text());mapping=metadata.get('Modules',{})
                removed_names={Path(x).name.lower() if platform=='Windows' else Path(x).name for x in removable}
                metadata['Modules']={name:file for name,file in mapping.items() if (Path(file).name.lower() if platform=='Windows' else Path(file).name) not in removed_names}
                target.write_text(json.dumps(metadata,indent=2)+'\n')
            kept.append(rel)
        name='Niagara-UE-Lite-Standalone-UE5.8.1-'+platform+'-x86_64'
        (dest.parent/(name+'-file-list.json')).write_text(json.dumps(kept,indent=2)+'\n')
    a.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in {'removed','blockedByStaticImports'}}),flush=True)


if __name__=='__main__':main()
