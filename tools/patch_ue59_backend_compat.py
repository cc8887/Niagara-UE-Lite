"""Keep UE 5.9's real legacy renderer configuration service without Cascade UI.

Apply only to an independent engine/project copy. RendererSettings still imports
two console variables now defined in CascadeVertexFactories. Keep that native
module and CascadeRuntime; omit CascadeEditor and its Takes toolkit dependency.
This does not add Cascade authoring to the public Niagara CLI.
"""
import argparse,json,os,stat
from pathlib import Path


def changes(engine,project):
    version=json.loads((engine/'Build/Build.version').read_text())
    if tuple(version[k] for k in ('MajorVersion','MinorVersion','PatchVersion'))!=(5,9,0):
        raise ValueError('UE 5.9.0 required')
    descriptor=engine/'Plugins/FX/Cascade/Cascade.uplugin'
    plugin=json.loads(descriptor.read_text())
    allowed={'CascadeVertexFactories','CascadeRuntime','CascadeEditor'}
    if {m['Name'] for m in plugin['Modules']} not in (allowed,allowed-{'CascadeEditor'}):
        raise ValueError('Cascade module layout changed')
    if any(p['Name']!='Takes' for p in plugin.get('Plugins',[])):
        raise ValueError('Unexpected Cascade plugin dependency')
    plugin['Modules']=[m for m in plugin['Modules'] if m['Name']!='CascadeEditor']
    plugin['Plugins']=[]
    data=json.loads(project.read_text())
    existing=[p for p in data['Plugins'] if p['Name']=='Cascade']
    reference={'Name':'Cascade','Enabled':True,'TargetAllowList':['Editor']}
    if existing and existing!=[reference]:raise ValueError('Conflicting Cascade project reference')
    if not existing:data['Plugins'].append(reference)
    return {descriptor:plugin,project:data}


def writable(path):
    if os.name=='nt':
        import ctypes
        get=ctypes.windll.kernel32.GetFileAttributesW;get.argtypes=[ctypes.c_wchar_p];get.restype=ctypes.c_ulong
        put=ctypes.windll.kernel32.SetFileAttributesW;put.argtypes=[ctypes.c_wchar_p,ctypes.c_ulong]
        flags=get(str(path))
        if flags==0xffffffff or not put(str(path),flags&~1):raise OSError('Cannot clear read-only attribute')
    else:path.chmod(path.stat().st_mode|stat.S_IWUSR)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine',required=True,type=Path);p.add_argument('--project',required=True,type=Path)
    p.add_argument('--apply',action='store_true');a=p.parse_args()
    content=changes(a.engine.resolve(),a.project.resolve())
    if a.apply:
        if any(f.stat().st_nlink>1 for f in content):raise ValueError('Independent source copies required')
        for file,value in content.items():
            writable(file);file.write_text(json.dumps(value,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'applied':a.apply,'engine':'5.9.0','nativeRendererConfigurationPreserved':True,
                      'cascadeEditorEnabled':False,'projectReferenceEditorOnly':True}))


if __name__=='__main__':main()
