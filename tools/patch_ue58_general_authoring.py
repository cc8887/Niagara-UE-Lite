"""Expose existing UE 5.8.1 Niagara stack operations to the external CLI bridge.

Apply only to an isolated source copy, then rebuild NiagaraEditor. This changes
DLL symbol visibility, not struct layouts, graph algorithms or serialized types.
"""
import argparse,json,stat,hashlib
from pathlib import Path


def changes(engine):
    root='Plugins/FX/Niagara/Source/NiagaraEditor/Public/'
    edits={
        root+'NiagaraExternalSystemEditorUtilities.h':[
            ('\tFNiagaraEmitterHandle* GetEmitter(', '\tUE_API FNiagaraEmitterHandle* GetEmitter('),
            ('\tUNiagaraStackScriptItemGroup* GetScript(', '\tUE_API UNiagaraStackScriptItemGroup* GetScript('),
            ('\tUNiagaraStackModuleItem* GetModule(', '\tUE_API UNiagaraStackModuleItem* GetModule('),
            ('\tUNiagaraStackFunctionInput* GetInput(', '\tUE_API UNiagaraStackFunctionInput* GetInput('),
            ('\tUNiagaraRendererProperties* GetRenderer(', '\tUE_API UNiagaraRendererProperties* GetRenderer(')],
        root+'ViewModels/Stack/NiagaraStackGraphUtilities.h':[
            ('\tvoid MoveModule(UNiagaraScript& SourceScript,', '\tNIAGARAEDITOR_API void MoveModule(UNiagaraScript& SourceScript,')],
        root+'NiagaraEditorUtilities.h':[
            ('\tUNiagaraScript* GetScriptFromSystem(UNiagaraSystem& System,', '\tNIAGARAEDITOR_API UNiagaraScript* GetScriptFromSystem(UNiagaraSystem& System,')],
    }
    result={}
    for relative,replacements in edits.items():
        text=(engine/relative).read_text(encoding='utf-8-sig')
        for before,after in replacements:
            if text.count(before)!=1:raise ValueError('Source export declaration changed: '+before.strip())
            text=text.replace(before,after,1)
        result[relative]=text
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',required=True,type=Path)
    p.add_argument('--apply',action='store_true');p.add_argument('--report',type=Path);a=p.parse_args()
    engine=a.engine.resolve();v=json.loads((engine/'Build/Build.version').read_text())
    if [v[k] for k in ('MajorVersion','MinorVersion','PatchVersion')]!=[5,8,1]:raise ValueError('Matching UE 5.8.1 required')
    content=changes(engine);rows=[]
    if a.apply and any((engine/r).stat().st_nlink>1 for r in content):raise ValueError('Use independent source copies')
    for relative,text in content.items():
        path=engine/relative;data=text.encode('utf-8')
        rows.append({'path':relative,'beforeSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'afterSha256':hashlib.sha256(data).hexdigest()})
        if a.apply:
            temporary=path.with_name(path.name+'.niagara-export-new')
            with temporary.open('xb') as stream:stream.write(data)
            path.chmod(path.stat().st_mode|stat.S_IWUSR);temporary.replace(path)
    report={'schema':'niagara-general-authoring-exports/1','applied':a.apply,'changes':rows,
            'rebuildModule':'NiagaraEditor','serializedLayoutsChanged':False,'qualified':False}
    if a.report:a.report.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
