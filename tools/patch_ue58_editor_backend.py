"""Apply the commandlet service profile to an explicitly isolated UE 5.8.1 tree.

This first source profile removes the default editor module sweep and viewport
UI startup from the standalone commandlet path. Graph/compile services remain.
Persona's mesh toolbar integration is compile-time excluded. Rebuild UnrealEd,
LevelEditor, MeshUtilities and Blutility; do not delete libraries before qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat

MARKER='NIAGARA_LITE_BACKEND_PROFILE_V1'
SERVICES=('Documentation','OutputLog','SourceControl','UncontrolledChangelists',
          'TextureCompressor','MeshUtilities','ClassViewer','StructViewer',
          'ContentBrowser','AssetTools','GraphEditor','KismetCompiler','Kismet',
          'PropertyEditor','EditorFramework','EditorConfig','ToolWidgets')


def body_span(text,signature):
    if text.count(signature)!=1:raise ValueError('Source signature changed: '+signature)
    start=text.index('{',text.index(signature))
    # Mask comments and quoted literals before counting braces.
    masked=re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m:' '*len(m.group()),text,flags=re.S)
    depth=0
    for i in range(start,len(text)):
        if masked[i]=='{':depth+=1
        elif masked[i]=='}':
            depth-=1
            if depth==0:return start+1,i
    raise ValueError('Unbalanced function')


def transform(engine):
    changes={}
    paths={
        'UnrealEd':'Source/Editor/UnrealEd/Private/EditorEngine.cpp',
        'LevelEditor':'Source/Editor/LevelEditor/Private/LevelEditor.cpp',
        'MeshUtilities':'Source/Developer/MeshUtilities/Private/MeshUtilities.cpp',
        'Blutility':'Source/Editor/Blutility/Private/EditorUtilitySubsystem.cpp',
    }
    for module,relative in paths.items():
        path=engine/relative;text=path.read_text(encoding='utf-8-sig')
        if MARKER in text:raise ValueError('Profile already applied: '+relative)
        if module=='UnrealEd':
            start,end=body_span(text,'void UEditorEngine::LoadDefaultEditorModules()')
            array=',\n'.join('            TEXT("'+s+'")' for s in SERVICES)
            block='''
    // NIAGARA_LITE_BACKEND_PROFILE_V1: explicit commandlet services only.
    if (IsRunningCommandlet() && FParse::Param(FCommandLine::Get(), TEXT("NiagaraLiteBackend")))
    {
        static const TCHAR* Services[] = {
'''+array+'''
        };
        for (const TCHAR* Service : Services)
            FModuleManager::Get().LoadModuleChecked(Service);
        return;
    }
'''
            text=text[:start]+block+text[start:]
        elif module=='LevelEditor':
            for sig in ('void FLevelEditorModule::StartupModule()',
                        'void FLevelEditorModule::ShutdownModule()'):
                start,end=body_span(text,sig)
                block='''
    // NIAGARA_LITE_BACKEND_PROFILE_V1: no level window, viewport or toolbar.
    if (IsRunningCommandlet() && FParse::Param(FCommandLine::Get(), TEXT("NiagaraLiteBackend"))) return;
'''
                if 'StartupModule' in sig:
                    block=block.replace('))) return;', ''')))
    {
        // Niagara's post-engine registration still queries these non-visual services.
        MenuExtensibilityManager = MakeShared<FExtensibilityManager>();
        ToolBarExtensibilityManager = MakeShared<FExtensibilityManager>();
        ModeBarExtensibilityManager = MakeShared<FExtensibilityManager>();
        NotificationBarExtensibilityManager = MakeShared<FExtensibilityManager>();
        GlobalLevelEditorActions = MakeShared<FUICommandList>();
        OutlinerSettings = MakeShared<FLevelEditorOutlinerSettings>();
        OutlinerSettings->Initialize();
        OutlinerSettings->SetupBuiltInCategories();
        return;
    }''')
                text=text[:start]+block+text[start:]
        elif module=='Blutility':
            for sig in ('void UEditorUtilitySubsystem::Initialize(FSubsystemCollectionBase& Collection)',
                        'void UEditorUtilitySubsystem::Deinitialize()'):
                start,end=body_span(text,sig)
                text=text[:start]+'''
    // NIAGARA_LITE_BACKEND_PROFILE_V1: no editor utility UI or startup scripts.
    if (IsRunningCommandlet() && FParse::Param(FCommandLine::Get(), TEXT("NiagaraLiteBackend"))) return;
'''+text[start:]
        else:
            start,end=body_span(text,'void FMeshUtilities::AddMakeStaticMeshEntryToToolMenu(FName InToolMenuName)')
            text=text[:start]+'''
// NIAGARA_LITE_BACKEND_PROFILE_V1: Persona toolbar is not part of this backend.
#if !NIAGARA_LITE_NO_PERSONA_TOOLBAR
'''+text[start:end]+'''\n#endif
'''+text[end:]
        changes[relative]=text
        rules=next((engine/'Source').glob('**/'+module+'.Build.cs'))
        rel=rules.relative_to(engine).as_posix();rule=rules.read_text(encoding='utf-8-sig')
        sig='public '+module+'(ReadOnlyTargetRules Target) : base(Target)'
        start,end=body_span(rule,sig)
        insertion='\n        // '+MARKER+'\n        bUsePrecompiled = false;\n'
        if module=='MeshUtilities':insertion+='        PrivateDefinitions.Add("NIAGARA_LITE_NO_PERSONA_TOOLBAR=1");\n'
        changes[rel]=rule[:start]+insertion+rule[start:]
    return changes


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--engine',required=True,type=Path)
    p.add_argument('--apply',action='store_true')
    p.add_argument('--report',type=Path)
    a=p.parse_args();engine=a.engine.resolve()
    version=json.loads((engine/'Build/Build.version').read_text())
    if tuple(version[k] for k in ('MajorVersion','MinorVersion','PatchVersion')) not in ((5,8,1),(5,9,0)):
        raise ValueError('Matching UE 5.8.1 or 5.9.0 required')
    changes=transform(engine);rows=[]
    for relative,text in changes.items():
        path=engine/relative;original=path.read_bytes();data=text.encode('utf-8')
        rows.append({'path':relative,'beforeSha256':hashlib.sha256(original).hexdigest(),
                     'afterSha256':hashlib.sha256(data).hexdigest()})
        if a.apply:
            if path.stat().st_nlink>1:raise ValueError('Use independent source copies, not shared hardlinks')
            # Replace the named file; do not overwrite a source hardlink in place.
            temp=path.with_name(path.name+'.niagara-profile-new')
            if temp.exists():
                if temp.read_bytes()!=data:raise ValueError('Unexpected previous patch temporary file')
            else:
                with temp.open('xb') as stream:stream.write(data)
            path.chmod(path.stat().st_mode|stat.S_IWUSR)
            temp.replace(path)
    report={'schema':'niagara-editor-backend-source-profile/1','applied':a.apply,
            'services':SERVICES,'changes':rows,'rebuildModules':list(('UnrealEd','LevelEditor','MeshUtilities','Blutility')),
            'requiresRuntimeArgument':'-NiagaraLiteBackend','qualified':False}
    if a.report:a.report.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
