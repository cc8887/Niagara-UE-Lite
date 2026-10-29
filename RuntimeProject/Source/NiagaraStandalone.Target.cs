using UnrealBuildTool;
public class NiagaraStandaloneTarget : TargetRules
{
    public NiagaraStandaloneTarget(TargetInfo Target) : base(Target)
    {
        Type = TargetType.Game;
        DefaultBuildSettings = BuildSettingsVersion.Latest;
        IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
        ExtraModuleNames.Add("NiagaraStandalone");
    }
}
