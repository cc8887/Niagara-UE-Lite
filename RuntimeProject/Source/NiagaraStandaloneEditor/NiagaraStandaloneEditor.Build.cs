using UnrealBuildTool;
public class NiagaraStandaloneEditor : ModuleRules
{
    public NiagaraStandaloneEditor(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PrivateDependencyModuleNames.AddRange(new [] {
            "Core", "CoreUObject", "Engine", "Niagara", "NiagaraCore", "NiagaraEditor",
            "UnrealEd", "AssetRegistry", "AssetTools", "Json", "JsonUtilities", "Projects"
        });
    }
}
