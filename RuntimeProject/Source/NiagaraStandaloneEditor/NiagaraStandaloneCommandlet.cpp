#include "NiagaraStandaloneCommandlet.h"
#include "NiagaraExternalSystemEditorUtilities.h"
#include "NiagaraSystem.h"
#include "NiagaraEmitter.h"
#include "NiagaraEmitterHandle.h"
#include "NiagaraScript.h"
#include "NiagaraRendererProperties.h"
#include "NiagaraSpriteRendererProperties.h"
#include "NiagaraRibbonRendererProperties.h"
#include "NiagaraMeshRendererProperties.h"
#include "NiagaraTypes.h"
#include "JsonObjectConverter.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Misc/EngineVersion.h"
#include "UObject/SavePackage.h"
#include "Serialization/JsonSerializer.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "UObject/UnrealType.h"
#include "Engine/World.h"

namespace
{
using J = TSharedPtr<FJsonObject>;
using U = UNiagaraExternalEditUtilities;
FString String(const J& O, const TCHAR* K, const FString& Default = FString())
{ FString V; return O->TryGetStringField(K,V) ? V : Default; }
FName Name(const J& O,const TCHAR* K) { return FName(*String(O,K)); }
FString Json(const J& O)
{ FString S; FJsonSerializer::Serialize(O.ToSharedRef(),TJsonWriterFactory<>::Create(&S)); return S; }
J ExportStruct(const UStruct* Type,const void* Data)
{
    J O=MakeShared<FJsonObject>();
    auto Callback=FJsonObjectConverter::CustomExportCallback::CreateLambda([](FProperty* P,const void* Value)->TSharedPtr<FJsonValue>
    {
        auto* SP=CastField<FStructProperty>(P);
        if(!SP||!SP->Struct->IsChildOf(FInstancedStruct::StaticStruct()))return nullptr;
        const auto& Instance=*static_cast<const FInstancedStruct*>(Value);
        J V=MakeShared<FJsonObject>();V->SetBoolField(TEXT("isSet"),Instance.IsValid());
        if(Instance.IsValid())
        {
            V->SetStringField(TEXT("type"),Instance.GetScriptStruct()->GetPathName());
            V->SetObjectField(TEXT("data"),ExportStruct(Instance.GetScriptStruct(),Instance.GetMemory()));
        }
        return MakeShared<FJsonValueObject>(V);
    });
    FJsonObjectConverter::UStructToJsonObject(Type,Data,O.ToSharedRef(),0,0,&Callback);return O;
}
template<typename T> J Struct(const T& V) { return ExportStruct(T::StaticStruct(),&V); }
void ReportError(FNiagaraExternalEditContext& C,const FString& Message) { C.Error(FText::FromString(Message)); }
FNiagaraExt_StackItemReference Reference(UNiagaraSystem* S,const J& O)
{
    FNiagaraExt_StackItemReference R(S,Name(O,TEXT("emitter")),Name(O,TEXT("script")),Name(O,TEXT("module")));
    if(O->HasField(TEXT("renderer")))R.RendererIndex=int32(O->GetNumberField(TEXT("renderer")));
    const TArray<TSharedPtr<FJsonValue>>* A=nullptr;
    if(O->TryGetArrayField(TEXT("inputs"),A))for(const auto& V:*A)R.InputNameStack.Add(FName(*V->AsString()));
    else if(O->HasField(TEXT("input")))R.InputNameStack.Add(Name(O,TEXT("input")));
    return R;
}
bool InputValue(const J& O,FNiagaraExt_StackInputValue& V,FNiagaraExternalEditContext& C)
{
    const FString T=String(O,TEXT("type"));
    if(!O->HasField(TEXT("value"))){ReportError(C,TEXT("Input operation needs value"));return false;}
    const auto X=O->Values[TEXT("value")];
    if(T==TEXT("float")&&X->Type==EJson::Number){FNiagaraFloat F;F.Value=float(X->AsNumber());V.InitializeAs<FNiagaraFloat>(F);}
    else if(T==TEXT("int")&&X->Type==EJson::Number){FNiagaraInt32 F;F.Value=int32(X->AsNumber());V.InitializeAs<FNiagaraInt32>(F);}
    else if(T==TEXT("bool")&&X->Type==EJson::Boolean){FNiagaraBool F;F.SetValue(X->AsBool());V.InitializeAs<FNiagaraBool>(F);}
    else if((T==TEXT("vec2")||T==TEXT("vec3")||T==TEXT("color"))&&X->Type==EJson::Array)
    {
        const auto& A=X->AsArray();const int N=T==TEXT("vec2")?2:T==TEXT("vec3")?3:4;
        if(A.Num()!=N){ReportError(C,TEXT("Incorrect vector/color length"));return false;}
        for(const auto& E:A)if(E->Type!=EJson::Number){ReportError(C,TEXT("Vector elements must be numbers"));return false;}
        if(N==2){FVector2f F(A[0]->AsNumber(),A[1]->AsNumber());V.InitializeAs(FNiagaraTypeDefinition::GetVec2Def().GetScriptStruct(),reinterpret_cast<const uint8*>(&F));}
        if(N==3){FVector3f F(A[0]->AsNumber(),A[1]->AsNumber(),A[2]->AsNumber());V.InitializeAs(FNiagaraTypeDefinition::GetVec3Def().GetScriptStruct(),reinterpret_cast<const uint8*>(&F));}
        if(N==4)V.InitializeAs<FLinearColor>(FLinearColor(A[0]->AsNumber(),A[1]->AsNumber(),A[2]->AsNumber(),A[3]->AsNumber()));
    }
    else {ReportError(C,TEXT("Unsupported typed input: ")+T);return false;}
    return true;
}
void Apply(UNiagaraSystem* S,const J& O,FNiagaraExternalEditContext& C)
{
    const FString Op=String(O,TEXT("op"));auto R=Reference(S,O);
    if(Op==TEXT("add-emitter"))
    {
        auto* E=LoadObject<UNiagaraEmitter>(nullptr,*String(O,TEXT("template")));
        if(!E||R.EmitterName.IsNone()){ReportError(C,TEXT("add-emitter requires a valid template and name"));return;}
        for(const auto& H:S->GetEmitterHandles())if(H.GetName()==R.EmitterName){ReportError(C,TEXT("Emitter already exists"));return;}
        FNiagaraExt_EmitterTopology T;U::AddEmitter(E,R.EmitterName,T,C);
    }
    else if(Op==TEXT("remove-emitter"))U::RemoveEmitter(R,C);
    else if(Op==TEXT("add-module"))
    {
        const auto* M=LoadObject<UNiagaraScript>(nullptr,*String(O,TEXT("asset")));
        if(!M){ReportError(C,TEXT("Module asset not found"));return;}FNiagaraExt_ModuleTopology T;U::AddModule(R,M,T,C);
    }
    else if(Op==TEXT("remove-module"))U::RemoveModule(R,C);
    else if(Op==TEXT("module-enabled"))U::SetModuleEnabled(R,O->GetBoolField(TEXT("value")),C);
    else if(Op==TEXT("input")){FNiagaraExt_StackInputValue V;if(InputValue(O,V,C))U::SetStackInputData(R,V,C);}
    else if(Op==TEXT("emitter-enabled"))
    {
        bool Found=false;for(auto& H:S->GetEmitterHandles())if(H.GetName()==R.EmitterName){H.SetIsEnabled(O->GetBoolField(TEXT("value")),*S,true);Found=true;}
        if(!Found)ReportError(C,TEXT("Emitter not found"));
    }
    else if(Op==TEXT("system-properties")||Op==TEXT("emitter-properties")||Op==TEXT("renderer-properties"))
    {
        const TSharedPtr<FJsonObject>* P=nullptr;
        if(!O->TryGetObjectField(TEXT("properties"),P)){ReportError(C,TEXT("properties must be an object"));return;}
        if(Op==TEXT("system-properties")){FNiagaraExt_SystemData D;D.PropertyValues=Json(*P);U::SetSystemData(S,D,C);}
        if(Op==TEXT("emitter-properties")){FNiagaraExt_EmitterData D;D.PropertyValues=Json(*P);U::SetEmitterData(R,D,C);}
        if(Op==TEXT("renderer-properties")){FNiagaraExt_RendererData D;D.PropertyValues=Json(*P);U::SetRendererData(R,D,C);}
    }
    else if(Op==TEXT("add-sprite-renderer")){FNiagaraExt_RendererRef Out;U::AddRenderer(R,UNiagaraSpriteRendererProperties::StaticClass(),Out,C);}
    else if(Op==TEXT("add-ribbon-renderer")){FNiagaraExt_RendererRef Out;U::AddRenderer(R,UNiagaraRibbonRendererProperties::StaticClass(),Out,C);}
    else if(Op==TEXT("add-mesh-renderer")){FNiagaraExt_RendererRef Out;U::AddRenderer(R,UNiagaraMeshRendererProperties::StaticClass(),Out,C);}
    else if(Op==TEXT("remove-renderer"))U::RemoveRenderer(R,C);
    else ReportError(C,TEXT("Unsupported operation: ")+Op);
}
J Describe(UNiagaraSystem* S,FNiagaraExternalEditContext& C)
{
    J Out=MakeShared<FJsonObject>();Out->SetStringField(TEXT("schema"),TEXT("ue-niagara-snapshot/1"));
    Out->SetStringField(TEXT("asset"),S->GetPathName());Out->SetBoolField(TEXT("valid"),S->IsValid());
    Out->SetBoolField(TEXT("readyToRun"),S->IsReadyToRun());
    FNiagaraExt_SystemSummary Summary;U::GetSystemSummary(S,Summary,C);Out->SetObjectField(TEXT("summary"),Struct(Summary));
    FNiagaraExt_SystemCompileState Compile;U::GetSystemCompileState(S,Compile,C);Out->SetObjectField(TEXT("compile"),Struct(Compile));
    FNiagaraExt_SystemDependencies Dependencies;U::GetSystemDependencies(S,Dependencies,C);Out->SetObjectField(TEXT("staticDependencies"),Struct(Dependencies));
    TArray<TSharedPtr<FJsonValue>> Emitters;
    for(const auto& H:S->GetEmitterHandles())
    {
        auto E=MakeShared<FJsonObject>();FNiagaraExt_StackItemReference R(S,H.GetName());
        FNiagaraExt_EmitterTopology Topology;U::GetEmitterTopology(R,Topology,C);E->SetObjectField(TEXT("topology"),Struct(Topology));
        FNiagaraExt_EmitterData Data;U::GetEmitterData(R,Data,C);E->SetStringField(TEXT("propertiesJson"),Data.PropertyValues);
        TArray<FNiagaraExt_ModuleInputValues> Inputs;U::GetEmitterInputValues(R,Inputs,C);
        TArray<TSharedPtr<FJsonValue>> Values;for(const auto& I:Inputs)Values.Add(MakeShared<FJsonValueObject>(Struct(I)));
        E->SetArrayField(TEXT("moduleInputs"),Values);
        TArray<TSharedPtr<FJsonValue>> Renderers;for(const auto& Ref:Topology.Renderers)
        {R.RendererIndex=Ref.RendererIndex;FNiagaraExt_RendererData D;U::GetRendererData(R,D,C);Renderers.Add(MakeShared<FJsonValueObject>(Struct(D)));}
        E->SetArrayField(TEXT("renderers"),Renderers);Emitters.Add(MakeShared<FJsonValueObject>(E));
    }
    Out->SetArrayField(TEXT("emitters"),Emitters);return Out;
}
}

UNiagaraStandaloneCommandlet::UNiagaraStandaloneCommandlet()
{ IsClient=false;IsServer=false;IsEditor=true;LogToConsole=true;ShowErrorCount=true; }

int32 UNiagaraStandaloneCommandlet::Main(const FString& Params)
{
    FString Input,Output,Text;
    if(!FParse::Value(*Params,TEXT("Request="),Input)||!FParse::Value(*Params,TEXT("Response="),Output)||
       !FFileHelper::LoadFileToString(Text,*Input))return 2;
    J Q;if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Q)||!Q)return 2;
    J Result=MakeShared<FJsonObject>();FNiagaraExternalEditContext Errors;UNiagaraSystem* S=nullptr;
    FString Asset=String(Q,TEXT("asset")),Op=String(Q,TEXT("operation")),Backup;
    const bool Mutating=Op==TEXT("create")||Op==TEXT("edit")||Op==TEXT("save");
    Result->SetStringField(TEXT("engine"),FEngineVersion::Current().ToString());
    if(!FPackageName::IsValidLongPackageName(Asset)||!Asset.StartsWith(TEXT("/Game/")))ReportError(Errors,TEXT("Expected a /Game package path"));
    else if(Op==TEXT("prepare-preview"))
    {
        if(Asset!=TEXT("/Game/NiagaraPreview/Preview"))ReportError(Errors,TEXT("Unexpected preview map path"));
        else if(FPackageName::DoesPackageExist(Asset))
        {
            if(!LoadObject<UWorld>(nullptr,*Asset))ReportError(Errors,TEXT("Existing preview package is not a world"));
            else Result->SetBoolField(TEXT("saved"),true);
        }
        else
        {
            UPackage* Package=CreatePackage(*Asset);
            UWorld::InitializationValues Values;
            Values.AllowAudioPlayback(false).RequiresHitProxies(false).CreatePhysicsScene(false).CreateNavigation(false).CreateAISystem(false);
            UWorld* World=UWorld::CreateWorld(EWorldType::Editor,false,FName(TEXT("Preview")),Package,true,ERHIFeatureLevel::SM6,&Values);
            if(!World)ReportError(Errors,TEXT("Unable to create preview world"));
            else
            {
                World->SetFlags(RF_Public|RF_Standalone);
                const FString File=FPackageName::LongPackageNameToFilename(Asset,FPackageName::GetMapPackageExtension());
                IFileManager::Get().MakeDirectory(*FPaths::GetPath(File),true);
                FSavePackageArgs Args;Args.TopLevelFlags=RF_Public|RF_Standalone;Args.SaveFlags=SAVE_NoError;
                if(!UPackage::SavePackage(Package,World,*File,Args))ReportError(Errors,TEXT("Unable to save preview world"));
                else {FAssetRegistryModule::AssetCreated(World);Result->SetBoolField(TEXT("saved"),true);}
                World->DestroyWorld(false);
                World->RemoveFromRoot();
            }
        }
    }
    else if(Op==TEXT("create"))
    {
        if(FPackageName::DoesPackageExist(Asset))ReportError(Errors,TEXT("Refusing to replace an existing package"));
        else
        {
            FString Template=String(Q,TEXT("template"));UNiagaraSystem* Source=nullptr;
            if(!Template.IsEmpty()){Source=LoadObject<UNiagaraSystem>(nullptr,*Template);if(!Source)ReportError(Errors,TEXT("System template not found"));}
            if(!Errors.HasErrors())S=U::CreateNiagaraSystem(FPackageName::GetShortName(Asset),FPackageName::GetLongPackagePath(Asset),Source,Errors);
        }
    }
    else if(Op==TEXT("read")||Op==TEXT("edit")||Op==TEXT("save")||Op==TEXT("compile"))
    {S=LoadObject<UNiagaraSystem>(nullptr,*Asset);if(!S)ReportError(Errors,TEXT("Niagara System not found"));}
    else ReportError(Errors,TEXT("Unsupported command"));
    if(S&&!Errors.HasErrors())
    {
        S->AddToRoot();S->WaitForCompilationComplete(true,false);
        {
            FNiagaraExternalEditContext Context(S);
            const TArray<TSharedPtr<FJsonValue>>* Ops=nullptr;
            if(Mutating&&Q->TryGetArrayField(TEXT("operations"),Ops))
                for(const auto& V:*Ops){if(V->Type!=EJson::Object){ReportError(Context,TEXT("Operation must be object"));break;}Apply(S,V->AsObject(),Context);if(Context.HasErrors())break;}
            Errors.Errors.Append(Context.Errors);
        }
        if(!Errors.HasErrors()&&(Mutating||Op==TEXT("compile")))
        {
            S->RequestCompile(false);S->WaitForCompilationComplete(true,false);
            // Empty systems may be authored, but systems with emitters must compile.
            if(S->GetEmitterHandles().Num()>0&&!S->IsValid())ReportError(Errors,TEXT("Native Niagara compile failed"));
        }
        if(!Errors.HasErrors()&&Mutating)
        {
            const FString File=FPackageName::LongPackageNameToFilename(Asset,FPackageName::GetAssetPackageExtension());
            if(Op!=TEXT("create")&&IFileManager::Get().FileExists(*File))
            {
                Backup=FPaths::ProjectSavedDir()/TEXT("NiagaraStandalone/Backups")/FGuid::NewGuid().ToString(EGuidFormats::Digits)/FPaths::GetCleanFilename(File);
                IFileManager::Get().MakeDirectory(*FPaths::GetPath(Backup),true);
                if(IFileManager::Get().Copy(*Backup,*File,false,false)!=COPY_OK)ReportError(Errors,TEXT("Unable to back up source package"));
            }
            if(!Errors.HasErrors())
            {
                IFileManager::Get().MakeDirectory(*FPaths::GetPath(File),true);S->MarkPackageDirty();
                FSavePackageArgs Args;Args.TopLevelFlags=RF_Public|RF_Standalone;Args.SaveFlags=SAVE_NoError;
                if(!UPackage::SavePackage(S->GetOutermost(),S,*File,Args))ReportError(Errors,TEXT("Package save failed"));
                else Result->SetBoolField(TEXT("saved"),true);
            }
        }
        if(!Errors.HasErrors()){FNiagaraExternalEditContext Context(S);Result->SetObjectField(TEXT("snapshot"),Describe(S,Context));Errors.Errors.Append(Context.Errors);}
        S->RemoveFromRoot();
    }
    TArray<TSharedPtr<FJsonValue>> Messages;for(const FText& E:Errors.Errors)Messages.Add(MakeShared<FJsonValueString>(E.ToString()));
    Result->SetArrayField(TEXT("errors"),Messages);Result->SetBoolField(TEXT("ok"),!Errors.HasErrors());Result->SetStringField(TEXT("backup"),Backup);
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(Output),true);
    if(!FFileHelper::SaveStringToFile(Json(Result),*Output,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))return 4;
    return Errors.HasErrors()?3:0;
}
