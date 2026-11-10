"""Keep native Event/Simulation Stage identities in the external edit bridge.

No reflected layout changes. Script names may carry @usage-guid to distinguish
multiple native stacks of the same usage; legacy standard-stack names still work.
Apply only to a task-owned matching UE 5.8.1 source copy and rebuild NiagaraEditor.
"""
from pathlib import Path
import argparse,json,stat


def changes(engine):
    root='Plugins/FX/Niagara/Source/NiagaraEditor/'
    rel=root+'Public/ViewModels/Stack/NiagaraStackGraphUtilities.h'
    header=(engine/rel).read_text(encoding='utf-8-sig')
    before='\tUNiagaraNodeOutput* ResetGraphForOutput('
    if before in header:header=header.replace(before,'\tNIAGARAEDITOR_API UNiagaraNodeOutput* ResetGraphForOutput(',1)
    elif 'NIAGARAEDITOR_API UNiagaraNodeOutput* ResetGraphForOutput(' not in header:raise ValueError('ResetGraphForOutput declaration changed')
    result={rel:header}
    rel=root+'Private/NiagaraExternalSystemEditorUtilities.cpp'
    source=(engine/rel).read_text(encoding='utf-8-sig')
    if '// NIAGARA_CLI_STACK_IDENTITY' not in source:
        start=source.index('UNiagaraStackScriptItemGroup* FNiagaraExt_StackItemReference::GetScript(')
        end=source.index('UNiagaraStackModuleItem* FNiagaraExt_StackItemReference::GetModule(',start)
        block=source[start:end]
        before='\t\tENiagaraScriptUsage Usage;\n\t\tif (!ScriptUsageFromName(ScriptName, Usage))'
        after='''\t\t// NIAGARA_CLI_STACK_IDENTITY: no new fields in the reflected reference.
\t\tconst FString QualifiedName = ScriptName.ToString();
\t\tFString UsageName = QualifiedName, UsageIdText;
\t\tFGuid RequestedUsageId;
\t\tif (QualifiedName.Split(TEXT("@"), &UsageName, &UsageIdText) && !FGuid::Parse(UsageIdText, RequestedUsageId))
\t\t{
\t\t\tContext.Error(FText::FromString(TEXT("Invalid script usage GUID")));
\t\t\treturn nullptr;
\t\t}
\t\tENiagaraScriptUsage Usage;
\t\tif (!ScriptUsageFromName(FName(*UsageName), Usage))'''
        if block.count(before)==1 and block.count('FindScriptGroup(Usage, FGuid())')==2:
            block=block.replace(before,after).replace('FindScriptGroup(Usage, FGuid())','FindScriptGroup(Usage, RequestedUsageId)')
        else:
            # UE 5.9 also supports an explicit SimulationStage pointer. Preserve
            # that validation and add qualified-name identity for event stacks.
            before59='\t\tENiagaraScriptUsage Usage = ENiagaraScriptUsage::ParticleSimulationStageScript;\n\t\tif (ScriptName != NAME_None && !ScriptUsageFromName(ScriptName, Usage))'
            after59=after[:after.index('\t\tENiagaraScriptUsage Usage;')]+'''\t\tENiagaraScriptUsage Usage = ENiagaraScriptUsage::ParticleSimulationStageScript;
\t\tif (ScriptName != NAME_None && !ScriptUsageFromName(FName(*UsageName), Usage))'''
            if block.count(before59)!=1 or block.count('\t\tFGuid UsageId;')!=1 or block.count('FindScriptGroup(Usage, UsageId)')!=2:
                raise ValueError('External script resolver changed')
            block=block.replace(before59,after59).replace('\t\tFGuid UsageId;','\t\tFGuid UsageId = RequestedUsageId;')
            anchor='\t\t\tUsageId = SimulationStage->Script->GetUsageId();'
            if block.count(anchor)!=1:raise ValueError('Simulation stage identity assignment changed')
            block=block.replace(anchor,'''\t\t\tif (RequestedUsageId.IsValid() && RequestedUsageId != SimulationStage->Script->GetUsageId())
\t\t\t{
\t\t\t\tContext.Error(FText::FromString(TEXT("Conflicting simulation stage usage GUID")));
\t\t\t\treturn nullptr;
\t\t\t}
'''+anchor)
        source=source[:start]+block+source[end:]
        before='\tNameFromScriptUsage(Script->GetScriptUsage(), ScriptName);'
        if source.count(before)!=1:raise ValueError('Native script reference setter changed')
        source=source.replace(before,before+'''
\tif (Script->GetScriptUsageId().IsValid())
\t{
\t\tScriptName = FName(*(ScriptName.ToString() + TEXT("@") + Script->GetScriptUsageId().ToString(EGuidFormats::DigitsWithHyphens)));
\t}''',1)
    source=source.replace('FString UsageName = ScriptName.ToString(), UsageIdText;', 'const FString QualifiedName = ScriptName.ToString();\n\t\tFString UsageName = QualifiedName, UsageIdText;').replace('if (UsageName.Split(TEXT("@"), &UsageName, &UsageIdText)', 'if (QualifiedName.Split(TEXT("@"), &UsageName, &UsageIdText)')
    result[rel]=source
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',type=Path,required=True);p.add_argument('--apply',action='store_true');a=p.parse_args()
    engine=a.engine.resolve();v=json.loads((engine/'Build/Build.version').read_text())
    if tuple(v[k] for k in ('MajorVersion','MinorVersion','PatchVersion')) not in ((5,8,1),(5,9,0)):p.error('UE 5.8.1 or 5.9.0 required')
    content=changes(engine)
    if a.apply:
        for rel,text in content.items():
            f=engine/rel
            if f.stat().st_nlink>1:raise ValueError('Use independent source copies')
        for rel,text in content.items():
            f=engine/rel
            if f.read_text(encoding='utf-8-sig')!=text:
                f.chmod(f.stat().st_mode|stat.S_IWUSR);f.write_text(text,encoding='utf-8')
    print(json.dumps({'applied':a.apply,'files':list(content),'serializedLayoutsChanged':False,'needsRuntimeQualification':True},indent=2))


if __name__=='__main__':main()
