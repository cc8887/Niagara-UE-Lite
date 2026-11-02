"""Editable Niagara object documents with integrity-checked resource attachments.

Native object bodies are per-object UE archives, not encoded .uasset files.
Property text overlays are explicit; no unsupported field is silently omitted.
"""
import base64,hashlib,json,re,shutil,uuid
from pathlib import Path,PurePosixPath


PACKAGE=re.compile(r'/Game/(?:[A-Za-z_][A-Za-z0-9_]*/)*[A-Za-z_][A-Za-z0-9_]*')


def digest(data):return hashlib.sha256(data).hexdigest()


def validate(document):
    if document.get('schema')!='ue-niagara-document/1':raise ValueError('Unsupported Niagara document')
    packages=document.get('packages',[]);names=[p['package'] for p in packages]
    if not names or len(set(names))!=len(names) or any(not PACKAGE.fullmatch(n) for n in names):raise ValueError('Invalid package table')
    if document['package'] not in names:raise ValueError('Root package absent')
    records=document['objects']
    if not isinstance(records,list) or not 1<=len(records)<=100000:raise ValueError('Invalid object table')
    ids={r['id'] for r in records}
    if len(ids)!=len(records):raise ValueError('Duplicate object identity')
    for r in records:
        if not isinstance(r['name'],str) or not r['name'] or any(c in r['name'] for c in '\\/.::\r\n\t'):
            raise ValueError('Invalid object name')
        if not isinstance(r['class'],str) or not r['class'].startswith('/Script/') or not isinstance(r['archetype'],str):raise ValueError('Invalid native class/archetype')
        if r['outer'] not in ids and r['outer'] not in names:raise ValueError('Missing object outer')
        if r['id']!=r['outer']+('.' if r['outer'] in names or ':' in r['outer'] else ':')+r['name']:
            raise ValueError('Invalid object identity')
        flags=r['flags']
        if not isinstance(flags,int) or flags<0 or flags & ~((1<<0)|(1<<1)|(1<<3)|(1<<5)|(1<<18)):raise ValueError('Unsupported object flags')
        data=base64.b64decode(r['nativeData'],validate=True)
        if digest(data)!=r['nativeSha256']:raise ValueError('Native data digest mismatch: '+r['id'])
        if not isinstance(r['properties'],dict):raise ValueError('Invalid properties')
        for p in r['properties'].values():
            if not isinstance(p['text'],str) or not isinstance(p['type'],str) or not isinstance(p['apply'],bool):raise ValueError('Invalid property overlay')
        for v in r['customVersions']:
            if not isinstance(v['version'],int) or not re.fullmatch(r'[0-9A-Fa-f]{32}',v['id']):raise ValueError('Invalid custom version')
    for p in packages:
        if p['asset'] not in ids:raise ValueError('Missing package root')
        if not re.fullmatch(r'[0-9A-Fa-f]{32}',p['persistentGuid']):raise ValueError('Invalid package GUID')
        for key in ('rootMetadata','objectMetadata'):
            if not isinstance(p[key],dict):raise ValueError('Invalid package metadata')


def export_document(backend,workspace,project,asset,destination,timeout):
    destination=destination.resolve();attachments=destination.with_name(destination.name+'.assets')
    if destination.exists() or attachments.exists():raise ValueError('Export destination already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
    copied=False
    try:
        result=backend(workspace,project,{'operation':'export-document','asset':asset,'file':str(temporary)},timeout)
        document=json.loads(temporary.read_text(encoding='utf-8-sig'))
        for r in document['objects']:r['nativeSha256']=digest(base64.b64decode(r['nativeData'],validate=True))
        resources=[]
        for row in result.pop('attachments',[]):
            package=row['package'];source=Path(row['source'])
            if not PACKAGE.fullmatch(package) or not source.is_file():raise ValueError('Missing resource dependency: '+package)
            for suffix in ('.uasset','.uexp','.ubulk','.uptnl','.m.ubulk'):
                src=source.with_suffix(suffix)
                if not src.is_file():continue
                relative=package[len('/Game/'):]+suffix;target=attachments/relative
                target.parent.mkdir(parents=True,exist_ok=True);copied=True;data=src.read_bytes();target.write_bytes(data)
                resources.append({'path':relative,'bytes':len(data),'sha256':digest(data)})
        document['resourceDirectory']=attachments.name
        document['resources']=resources
        document['formatNotes']={'identity':'original /Game package paths','nativeData':'per-object current-build UE archive; preserve verbatim',
            'properties':'Set apply=true to apply a native text property overlay after restoring the object graph'}
        validate(document)
        temporary.write_text(json.dumps(document,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');temporary.replace(destination)
        result.update(file=str(destination),resourceFiles=len(resources));return result
    except BaseException:
        temporary.unlink(missing_ok=True)
        if copied:shutil.rmtree(attachments)
        raise


def import_document(backend,workspace,project,file,timeout):
    file=file.resolve();document=json.loads(file.read_text(encoding='utf-8-sig'));validate(document)
    content=(workspace/'Content').resolve();files=[];seen=set();outputs=[]
    directory=document.get('resourceDirectory','')
    if directory!=Path(directory).name or not directory or directory in ('.','..'):raise ValueError('Invalid resource directory')
    root=(file.parent/directory).resolve()
    for resource in document.get('resources',[]):
        rel=PurePosixPath(resource['path'])
        if rel.is_absolute() or '..' in rel.parts or '\\' in str(rel) or ':' in str(rel):raise ValueError('Invalid resource path')
        src=(root/str(rel)).resolve();dest=(content/str(rel)).resolve()
        if not src.is_relative_to(root) or not dest.is_relative_to(content) or dest in seen:raise ValueError('Resource path escapes root or repeats')
        if dest.exists():raise ValueError('Resource destination exists: '+str(rel))
        if dest.suffix not in ('.uasset','.uexp','.ubulk','.uptnl') and not dest.name.endswith('.m.ubulk'):raise ValueError('Unsupported resource extension')
        data=src.read_bytes()
        if len(data)!=resource['bytes'] or digest(data)!=resource['sha256']:raise ValueError('Resource integrity mismatch: '+str(rel))
        seen.add(dest);files.append((dest,data))
    for row in document['packages']:
        base=content/row['package'][len('/Game/'):]
        for suffix in ('.uasset','.uexp','.ubulk','.uptnl','.m.ubulk'):
            dest=base.with_suffix(suffix)
            if dest.exists() or dest in seen:raise ValueError('Package destination exists or overlaps resource: '+row['package'])
            outputs.append(dest)
    installed=[]
    try:
        for dest,data in files:
            dest.parent.mkdir(parents=True,exist_ok=True)
            with dest.open('xb') as stream:installed.append(dest);stream.write(data)
        result=backend(workspace,project,{'operation':'import-document','file':str(file)},timeout)
        result.update(resourceFiles=len(files),packagePathsPreserved=True);return result
    except BaseException:
        for dest in installed+outputs:dest.unlink(missing_ok=True)
        raise
