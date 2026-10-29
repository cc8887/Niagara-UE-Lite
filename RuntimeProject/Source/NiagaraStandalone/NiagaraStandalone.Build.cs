using UnrealBuildTool;
public class NiagaraStandalone : ModuleRules
{
    public NiagaraStandalone(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PrivateDependencyModuleNames.AddRange(new [] {
            "Core", "CoreUObject", "Engine", "Niagara", "NiagaraCore",
            "RHI", "RenderCore", "Json", "ImageWrapper"
        });
    }
}
