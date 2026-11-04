"""Freeze an updated, previously qualified standalone profile into a new stage.

This preserves the curated module/resource selection instead of expanding it
back to a complete installed engine. Source kits are never modified. Rebuilt
modules must already be qualified in that source kit before invoking this tool.
"""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
from package_support import copy,SOURCE_PREFIXES
from slim_package import exclusion,library,stripped_copy,sha
from package_standalone import NAME,generated_path

REPO=Path(__file__).resolve().parents[1]
TOP={'backend','Project','runtime-template','scripts','docs'}
ROOT_FILES={'niagara-cli.exe','niagara-cli.cmd','niagara-cli','runtime-template-links.json','README.md'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path);p.add_argument('--out',required=True,type=Path)
    p.add_argument('--private-root',action='append',default=[]);p.add_argument('--strip-tool',default='llvm-objcopy')
    p.add_argument('--trim-material-authoring',action='store_true',help='Trim unreferenced material/texture UI modules and inactive ICU data copies')
    a=p.parse_args();source=a.source.resolve();dest=a.out.resolve()
    if dest.exists() or source==dest or source.is_relative_to(dest) or dest.is_relative_to(source):p.error('New independent stage required')
    platform='Windows' if os.name=='nt' else 'Linux'
    original=json.loads((source/'package-manifest.json').read_text(encoding='utf8'))
    if original['platform']!=platform:p.error('Build on the target platform')
    material_plan=None
    if a.trim_material_authoring:
        from material_profile import plan
        material_plan=plan(source,original)
    roots=[str(source),str(dest),str(REPO),*a.private_root]
    for root in roots:SOURCE_PREFIXES.extend([root,root.replace('\\','/'),root.replace('/','\\')])
    dest.mkdir(parents=True);removed=[];included=[];dedup={};hardlinks=0;stripped=0
    for file in sorted(source.rglob('*')):
        if not file.is_file():continue
        rel=file.relative_to(source);name=rel.as_posix()
        if rel.parts[0] not in TOP and name not in ROOT_FILES:continue
        if not file.resolve().is_relative_to(source):raise ValueError('Source symlink escapes profile: '+name)
        reason=exclusion(name,platform)
        if material_plan and name in material_plan['reasons']:reason=material_plan['reasons'][name]
        if name.startswith(('examples/','Project/Content/NiagaraDemo/')) or '/Content/DefaultAssets/Templates/' in name:reason='effect_presets'
        if 'Source' in rel.parts:reason='developer_source'
        if reason:removed.append({'path':name,'reason':reason});continue
        target=dest/rel
        if platform=='Linux':
            saved,is_elf=stripped_copy(file,target,a.strip_tool);stripped+=saved
            if is_elf:
                dynamic=subprocess.check_output(['readelf','-d',str(target)],text=True)
                if '(NEEDED)' in dynamic and 'libcef.so' in dynamic:raise ValueError('CEF dependency remains: '+name)
            if library(name):
                key=(sha(target),target.stat().st_mode&0o111)
                if key in dedup:
                    target.unlink();os.link(dest/dedup[key],target);hardlinks+=1
                else:dedup[key]=name
        else:copy(file,target)
        included.append(name)
    # Current portable frontend and documents are part of the frozen payload.
    for name in ('niagara_cli.py','assets_worker.py','vulkan_probe.py','native_python_worker.py','document_io.py'):
        copy(REPO/'tools'/name,dest/'scripts'/name)
    for file in sorted((REPO/'docs').rglob('*.md')):copy(file,dest/'docs'/file.relative_to(REPO/'docs'))
    copy(REPO/'README.md',dest/'README.md')
    if material_plan:
        for file in dest.rglob('*.modules'):
            data=json.loads(file.read_text())
            for name in material_plan['removedModuleNames']:data.get('Modules',{}).pop(name,None)
            file.write_text(json.dumps(data,indent=2)+'\n')
    with tempfile.TemporaryDirectory(prefix='niagara-profile-') as scratch:
        subprocess.run([sys.executable,str(REPO/'tools/prune_runtime_fixtures.py'),'--kit',str(dest),'--work',str(Path(scratch)/'prune')],check=True)
    links=dest/'runtime-template-links.json'
    if links.is_file():
        mapping=json.loads(links.read_text())
        for row in mapping['files']:
            canonical=dest/row['source']
            if not canonical.resolve().is_relative_to(dest) or not canonical.is_file():raise ValueError('Invalid runtime link')
            row.update(bytes=canonical.stat().st_size,sha256=sha(canonical))
        links.write_text(json.dumps(mapping,indent=2)+'\n')
    # Native UnrealPak can create Saved/config/log files during scaffold pruning.
    # Keep those new scratch files outside the immutable archive selection too.
    actual=[f.relative_to(dest).as_posix() for f in sorted(dest.rglob('*')) if f.is_file() and not generated_path(f,dest)]
    (dest.parent/(NAME+'-file-list.json')).write_text(json.dumps(actual,indent=2)+'\n')
    audit={'platform':platform,'files':len(actual),'removed':removed,'stripSavedBytes':stripped,'libraryHardlinks':hardlinks,
           'profile':'curated native editor/cook + shipping runtime; no effect presets; optional DDC excluded'}
    (dest.parent/(platform.lower()+'-profile-audit.json')).write_text(json.dumps(audit,indent=2)+'\n')
    if material_plan:(dest.parent/(platform.lower()+'-material-profile.json')).write_text(json.dumps(material_plan,indent=2)+'\n')
    print(json.dumps({k:v for k,v in audit.items() if k!='removed'}),flush=True)


if __name__=='__main__':main()
