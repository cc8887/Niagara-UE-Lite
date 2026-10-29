using UnrealBuildTool;
public class NiagaraStandaloneEditorTarget : TargetRules
{
    public NiagaraStandaloneEditorTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Editor;
        DefaultBuildSettings = BuildSettingsVersion.Latest;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.AddRange(new [] {"NiagaraStandalone", "NiagaraStandaloneEditor"});
    }
}
