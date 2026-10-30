"""Create a smaller standalone kit from a verified manifest; never modify its source."""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from package_support import copy, SOURCE_PREFIXES

REPO=Path(__file__).resolve().parents[1]
SYMBOL_SUFFIXES={'.pdb','.debug','.sym','.a','.lib','.obj','.o','.exp','.pyc'}
GENERATED={'Saved','Intermediate','DerivedDataCache','__pycache__'}

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def library(path):
    return bool(re.search(r'(?:\.dll|\.pyd|\.so(?:\.\d+)*)$',path,re.I))

def exclusion(rel,platform):
    parts=Path(rel).parts;name=parts[-1].lower()
    if any(p in GENERATED for p in parts[:-1]):return 'generated'
    if 'CEF3' in parts:return 'cef'
    if Path(rel).suffix.lower() in SYMBOL_SUFFIXES:return 'external_symbols_or_static_library'
    if name=='d3d12sdklayers.dll':return 'd3d12_debug_layer'
    if platform=='Windows' and any(p.lower() in ('arm64','winarm64') for p in parts):return 'other_architecture'
    if '/Binaries/ThirdParty/Vulkan/' in rel:
        if platform=='Windows':return 'unused_windows_vulkan_tools'
        if name.startswith(('vklayer','libvklayer')):return 'vulkan_optional_layer'
    return None

def elf_sections(path):
    with path.open('rb') as stream:
        head=stream.read(64)
        if not head.startswith(b'\x7fELF'):return None
        if head[4:6]!=b'\x02\x01':raise ValueError('Expected little-endian ELF64')
        fields=struct.unpack('<16sHHIQQQIHHHHHH',head)
        offset,entry_size,count,string_index=fields[6],fields[11],fields[12],fields[13]
        stream.seek(offset);raw=stream.read(entry_size*count)
        sections=[struct.unpack('<IIQQQQIIQQ',raw[i*entry_size:i*entry_size+64]) for i in range(count)]
        strings=sections[string_index];stream.seek(strings[4]);names=stream.read(strings[5])
        result=[]
        for s in sections:
            name=names[s[0]:].split(b'\0',1)[0].decode('utf-8','replace')
            if s[2]&2: # SHF_ALLOC: loader-visible state must be byte-identical.
                digest=None
                if s[1]!=8: # SHT_NOBITS occupies memory, not file bytes.
                    stream.seek(s[4]);digest=hashlib.sha256(stream.read(s[5])).hexdigest()
                result.append((name,s[1],s[2],s[3],s[5],s[8],s[9],digest))
        return result

def stripped_copy(source,dest,strip_tool):
    copy(source,dest)
    before=elf_sections(dest)
    if before is None:return 0,False
    old_size=dest.stat().st_size
    subprocess.run([strip_tool,'--strip-unneeded',str(dest)],check=True,capture_output=True)
    if elf_sections(dest)!=before:raise RuntimeError('strip changed loader-visible ELF sections: '+dest.name)
    return old_size-dest.stat().st_size,True

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--overrides',type=Path,help='Replacement binaries at kit-relative paths')
    p.add_argument('--private-root',action='append',default=[])
    p.add_argument('--strip-tool',default='strip',help='Matching llvm-objcopy/llvm-strip or compatible strip executable')
    a=p.parse_args();source=a.source.resolve();dest=a.out.resolve()
    if source==dest or dest.is_relative_to(source) or source.is_relative_to(dest):
        raise ValueError('Source and destination must be separate trees')
    if dest.exists():raise ValueError('Destination exists; overwrite refused')
    original=json.loads((source/'package-manifest.json').read_text(encoding='utf-8'))
    platform=original['platform']
    if platform=='Linux' and not a.overrides:raise ValueError('Linux requires rebuilt no-CEF overrides')
    if platform=='Linux' and not shutil.which(a.strip_tool):raise ValueError('ELF strip tool not found')
    roots=[str(source),str(dest),str(REPO),*a.private_root]
    if a.overrides:roots.append(str(a.overrides.resolve()))
    for root in roots:SOURCE_PREFIXES.extend([root,root.replace('\\','/'),root.replace('/','\\')])
    dest.mkdir(parents=True)
    removed=[];strip_records=[];files=[];input_cache={};output_cache={};hardlinks={}
    windows_links=[];replacements=[];elf_count=0
    for index,record in enumerate(sorted(original['records'],key=lambda r:r['path'])):
        rel=record['path'];src=(source/rel).resolve();target=dest/rel
        if not src.is_relative_to(source) or not target.resolve().is_relative_to(dest):raise ValueError('Manifest path escapes kit')
        reason=exclusion(rel,platform)
        if reason:
            removed.append({'path':rel,'bytes':record['bytes'],'reason':reason});continue
        replacement=a.overrides/rel if a.overrides else None
        if replacement and replacement.is_file():
            src=replacement;replacements.append(rel)
        input_digest=sha(src)
        if src==(source/rel).resolve() and input_digest!=record['sha256']:raise ValueError('Source integrity mismatch: '+rel)
        mode=0o755 if src.stat().st_mode&0o111 else 0o644
        cache_key=(input_digest,mode)
        # Windows duplicate DLLs in the internal runtime template can share a
        # backend source. Cook materializes them into each exported preview.
        if platform=='Windows' and rel.startswith('runtime-template/') and library(rel) and cache_key in input_cache:
            canonical=input_cache[cache_key]
            if canonical.startswith('backend/'):
                existing=dest/canonical
                windows_links.append({'path':rel.removeprefix('runtime-template/'),'source':canonical,
                                      'bytes':existing.stat().st_size,'sha256':sha(existing)})
                continue
        target.parent.mkdir(parents=True,exist_ok=True)
        if platform=='Linux' and library(rel) and cache_key in input_cache:
            canonical=input_cache[cache_key];os.link(dest/canonical,target);hardlinks[rel]=canonical
        else:
            if platform=='Linux':
                saved,is_elf=stripped_copy(src,target,a.strip_tool)
                elf_count+=int(is_elf)
                if is_elf:
                    needed=subprocess.check_output(['readelf','-d',str(target)],text=True)
                    if re.search(r'\(NEEDED\).*\[libcef',needed):raise RuntimeError('CEF hard dependency remains: '+rel)
                if saved:strip_records.append({'path':rel,'beforeBytes':src.stat().st_size,'afterBytes':target.stat().st_size,'savedBytes':saved})
            else:copy(src,target)
            if library(rel):
                output_key=(sha(target),mode)
                if platform=='Linux' and output_key in output_cache:
                    canonical=output_cache[output_key]
                    target.unlink() # A single newly generated file inside dest only.
                    os.link(dest/canonical,target);hardlinks[rel]=canonical
                else:output_cache[output_key]=rel
                input_cache[cache_key]=rel
        files.append(rel)
        if index and index%10000==0:print(json.dumps({'phase':'copying','processed':index}),flush=True)
    if platform=='Linux':
        required={'backend/Engine/Binaries/Linux/libUnrealEditor-WebBrowser.so',
                  'backend/Engine/Binaries/Linux/libUnrealEditor-CEF3Utils.so'}
        if not required.issubset(replacements):raise RuntimeError('Both rebuilt no-CEF modules are required')
    if windows_links:
        rel='runtime-template-links.json'
        (dest/rel).write_text(json.dumps({'schema':'niagara-runtime-template-links/1','files':windows_links},indent=2)+'\n')
        files.append(rel)
    # Publish current portable scripts/docs, never a developer helper or local log.
    for name in ('niagara_cli.py','assets_worker.py','vulkan_probe.py'):
        rel='scripts/'+name;copy(REPO/'tools'/name,dest/rel)
        if rel not in files:files.append(rel)
    for folder in ('examples','docs'):
        for src in sorted((REPO/folder).rglob('*')):
            if not src.is_file():continue
            rel=src.relative_to(REPO).as_posix();copy(src,dest/rel)
            if rel not in files:files.append(rel)
    copy(REPO/'README.md',dest/'README.md')
    # Preserve legacy package sealing's explicit, immutable selection boundary.
    name='Niagara-UE-Lite-Standalone-UE5.8.1-'+platform+'-x86_64'
    (dest.parent/(name+'-file-list.json')).write_text(json.dumps(sorted(files),indent=2)+'\n')
    summary={'schema':'niagara-slim-audit/1','platform':platform,'baselinePayloadBytes':original['payloadBytes'],
             'removed':removed,'removedBytes':sum(r['bytes'] for r in removed),
             'stripSamples':strip_records,'stripSavedBytes':sum(r['savedBytes'] for r in strip_records),
             'stripAllocatedSectionsUnchanged':True,'elfFilesChecked':elf_count,'rebuiltModules':replacements,
             'libraryHardlinks':hardlinks,'runtimeTemplateLinks':windows_links,
             'hardlinkSavedBytes':sum((dest/rel).stat().st_size for rel in hardlinks),
             'windowsTemplateSavedBytes':sum(r['bytes'] for r in windows_links)}
    (dest.parent/(platform.lower()+'-slim-audit.json')).write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('removed','stripSamples','libraryHardlinks','runtimeTemplateLinks')}),flush=True)

if __name__=='__main__':main()
