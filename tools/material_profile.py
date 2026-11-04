"""Plan removals for the no-material-authoring profile from native import evidence.

Keep material compilation and shared services. Only module candidates without
surviving static/delay-import users can leave; native execution is still required.
ICU data versions are discovered from the actual packaged Core binaries.
"""
from pathlib import Path
from prune_editor_modules import pe_imports,elf_imports,module

UI_CANDIDATES={'TextureEditor','MeshMergeUtilities'}
SHARED={'MaterialEditor','MaterialUtilities','MaterialBaking'}


def plan(source,manifest):
    platform=manifest['platform'];records=manifest['records'];imports={};libraries={};cores=[]
    for row in records:
        rel=row['path'];file=source/rel
        binary=file.suffix.lower() in ('.dll','.exe','.pyd') if platform=='Windows' else '.so' in file.name
        if not binary:continue
        deps=pe_imports(file) if platform=='Windows' else elf_imports(file)
        if deps is not None:imports[rel]=[n.lower() for n in deps];libraries.setdefault(file.name.lower(),[]).append(rel)
        if module(rel)=='Core':cores.append(file)
    candidates={r['path'] for r in records if module(r['path']) in UI_CANDIDATES};removed=set(candidates);blocked={}
    while True:
        denied={}
        for rel,deps in imports.items():
            if rel in removed:continue
            for dep in deps:
                for target in libraries.get(dep,[]):
                    if target in removed:denied.setdefault(target,[]).append(rel)
        if not denied:break
        blocked.update(denied);removed-=denied.keys()
    versions=set();core_evidence=[]
    for file in cores:
        data=file.read_bytes();found=[v for v in ('icudt53l','icudt64l','icudt78l') if any(v.encode(e) in data for e in ('utf-8','utf-16le','utf-32le'))]
        versions.update(found);core_evidence.append({'path':file.relative_to(source).as_posix(),'dataVersions':found})
    if not versions:raise ValueError('Native ICU data version not identified; refuse trimming')
    intl='backend/Engine/Content/Internationalization/'
    for version in versions:
        if not (source/intl/version).is_dir():raise ValueError('Required ICU data root missing: '+version)
    reasons={rel:'unused_material_or_texture_ui_module' for rel in removed}
    for row in records:
        rel=row['path']
        if not rel.startswith(intl):continue
        parts=rel[len(intl):].split('/')
        if len(parts)>1 and parts[0] not in versions:reasons[rel]='inactive_icu_version_or_packaging_preset'
    shared={}
    for row in records:
        if module(row['path']) not in SHARED:continue
        name=Path(row['path']).name.lower();shared[row['path']]=[p for p,deps in imports.items() if name in deps and p not in removed]
    return {'reasons':reasons,'removedModuleNames':sorted({module(r) for r in removed}),
            'blockedUiModules':blocked,'retainedSharedMaterialModules':shared,'nativeIcuDataVersions':sorted(versions),
            'icuCoreEvidence':core_evidence,'removedBytes':sum(r['bytes'] for r in records if r['path'] in reasons)}
