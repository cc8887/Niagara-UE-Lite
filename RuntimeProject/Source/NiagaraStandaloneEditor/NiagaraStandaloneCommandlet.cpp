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
#include "Engine/Texture.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "NiagaraDataInterface.h"
#include "AssetRegistry/ARFilter.h"
#include "UObject/UObjectIterator.h"
#include "NiagaraEditorUtilities.h"
#include "NiagaraNodeFunctionCall.h"
#include "NiagaraScriptSourceBase.h"
#include "NiagaraEmitterFactoryNew.h"
#include "NiagaraSystemFactoryNew.h"
#include "NiagaraSystemEditorData.h"
#include "NiagaraSimulationStageBase.h"
#include "NiagaraScriptSource.h"
#include "NiagaraGraph.h"
#include "NiagaraNodeOutput.h"
#include "ViewModels/Stack/NiagaraStackFunctionInput.h"
#include "ViewModels/Stack/NiagaraStackModuleItem.h"
#include "ViewModels/Stack/NiagaraStackScriptItemGroup.h"
#include "ViewModels/Stack/NiagaraStackGraphUtilities.h"
#include "Serialization/ObjectAndNameAsStringProxyArchive.h"
#include "Serialization/MemoryReader.h"
#include "Serialization/MemoryWriter.h"
#include "Serialization/CustomVersion.h"
#include "Misc/Base64.h"
#include "UObject/UObjectHash.h"
#include "EdGraph/EdGraphPin.h"

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
bool EmitterNameAllowed(FName Value,FNiagaraExternalEditContext& C)
{
    // Same reserved namespaces as UE 5.8.1's emitter-name editor validator.
    const FString Text=Value.ToString();
    for(const TCHAR* Reserved:{TEXT("Particles"),TEXT("Local"),TEXT("Engine"),TEXT("Transient"),TEXT("User"),TEXT("Emitter"),TEXT("Module"),TEXT("NPC")})
        if(Text.Equals(Reserved,ESearchCase::IgnoreCase)){ReportError(C,TEXT("Emitter name is a reserved Niagara namespace: ")+Text);return false;}
    if(Value.IsNone()||Text.TrimStartAndEnd().IsEmpty()){ReportError(C,TEXT("Emitter name must not be empty"));return false;}
    return true;
}
UNiagaraSystem* EmitterEditingSystem(UNiagaraEmitter* Emitter)
{
    // UE edits a standalone emitter through a transient placeholder System. The
    // direct handle points at the original emitter; its own package is saved.
    auto* System=NewObject<UNiagaraSystem>(GetTransientPackage(),NAME_None,RF_Transient|RF_Transactional);
    UNiagaraSystemFactoryNew::InitializeSystem(System,true);
    auto* EditorData=CastChecked<UNiagaraSystemEditorData>(System->GetEditorData());
    EditorData->SetOwningSystemIsPlaceholder(true,*System);
    FNiagaraEditorUtilities::AddEmitterToSystem(*System,*Emitter,Emitter->GetExposedVersion().VersionGuid,false);
    return System;
}
FNiagaraExt_StackItemReference Reference(UNiagaraSystem* S,const J& O)
{
    FNiagaraExt_StackItemReference R(S,Name(O,TEXT("emitter")),Name(O,TEXT("script")),Name(O,TEXT("module")));
    if(O->HasField(TEXT("usageId")))R.ScriptName=FName(*(R.ScriptName.ToString()+TEXT("@")+String(O,TEXT("usageId"))));
    if(O->HasField(TEXT("renderer")))R.RendererIndex=int32(O->GetNumberField(TEXT("renderer")));
    const TArray<TSharedPtr<FJsonValue>>* A=nullptr;
    if(O->TryGetArrayField(TEXT("inputs"),A))for(const auto& V:*A)R.InputNameStack.Add(FName(*V->AsString()));
    else if(O->HasField(TEXT("input")))R.InputNameStack.Add(Name(O,TEXT("input")));
    return R;
}
bool InputValue(const J& O,FNiagaraExt_StackInputValue& V,FNiagaraExternalEditContext& C,const FNiagaraExt_StackItemReference* Ref=nullptr)
{
    const FString T=String(O,TEXT("type"));
    if(!O->HasField(TEXT("value"))){ReportError(C,TEXT("Input operation needs value"));return false;}
    const auto X=O->Values[TEXT("value")];
    if(T==TEXT("float")&&X->Type==EJson::Number){FNiagaraFloat F;F.Value=float(X->AsNumber());V.InitializeAs<FNiagaraFloat>(F);}
    else if(T==TEXT("int")&&X->Type==EJson::Number)
    {
        const double N=X->AsNumber();if(!FMath::IsFinite(N)||N<MIN_int32||N>MAX_int32||FMath::FloorToDouble(N)!=N)
        {ReportError(C,TEXT("Expected an exact int32 value"));return false;}
        FNiagaraInt32 F;F.Value=int32(N);V.InitializeAs<FNiagaraInt32>(F);
    }
    else if(T==TEXT("bool")&&X->Type==EJson::Boolean){FNiagaraBool F;F.SetValue(X->AsBool());V.InitializeAs<FNiagaraBool>(F);}
    else if((T==TEXT("vec2")||T==TEXT("vec3")||T==TEXT("position")||T==TEXT("color"))&&X->Type==EJson::Array)
    {
        const auto& A=X->AsArray();const int N=T==TEXT("vec2")?2:(T==TEXT("vec3")||T==TEXT("position"))?3:4;
        if(A.Num()!=N){ReportError(C,TEXT("Incorrect vector/color length"));return false;}
        for(const auto& E:A)if(E->Type!=EJson::Number){ReportError(C,TEXT("Vector elements must be numbers"));return false;}
        if(N==2){FVector2f F(A[0]->AsNumber(),A[1]->AsNumber());V.InitializeAs(FNiagaraTypeDefinition::GetVec2Def().GetScriptStruct(),reinterpret_cast<const uint8*>(&F));}
        if(N==3){FVector3f F(A[0]->AsNumber(),A[1]->AsNumber(),A[2]->AsNumber());V.InitializeAs((T==TEXT("position")?FNiagaraTypeDefinition::GetPositionDef():FNiagaraTypeDefinition::GetVec3Def()).GetScriptStruct(),reinterpret_cast<const uint8*>(&F));}
        if(N==4)V.InitializeAs<FLinearColor>(FLinearColor(A[0]->AsNumber(),A[1]->AsNumber(),A[2]->AsNumber(),A[3]->AsNumber()));
    }
    else if(T==TEXT("dynamic-input")&&X->Type==EJson::String)
    {
        auto* Script=LoadObject<UNiagaraScript>(nullptr,*X->AsString());
        if(!Script||Script->GetUsage()!=ENiagaraScriptUsage::DynamicInput){ReportError(C,TEXT("Expected a compatible DynamicInput script asset"));return false;}
        FNiagaraExt_StackInputData_DynamicInput D;D.DynamicInputAsset=Script;V.InitializeAs<FNiagaraExt_StackInputData_DynamicInput>(D);
    }
    else if(T==TEXT("expression")&&X->Type==EJson::String)
    {
        FNiagaraExt_StackInputData_HlslExpression D;D.HlslExpression=X->AsString();V.InitializeAs<FNiagaraExt_StackInputData_HlslExpression>(D);
    }
    else if(T==TEXT("data-interface")&&X->Type==EJson::Object)
    {
        FNiagaraExt_StackInputData_DataInterface D;D.PropertyValues=Json(X->AsObject());V.InitializeAs<FNiagaraExt_StackInputData_DataInterface>(D);
    }
    else if((T==TEXT("enum")||T==TEXT("linked"))&&Ref)
    {
        FNiagaraExt_StackInputSchema Schema;U::GetStackInputSchema(*Ref,Schema,C);if(C.HasErrors())return false;
        if(T==TEXT("enum")&&X->Type==EJson::String)
        {
            UEnum* Enum=Schema.Type.GetEnum();
            const FName Entry(*X->AsString());
            if(!Enum||Enum->GetValueByName(Entry)==INDEX_NONE){ReportError(C,TEXT("Unknown enum entry for this input"));return false;}
            FNiagaraExt_StackInputData_Enum D;D.Enum=Enum;D.EnumName=Entry;V.InitializeAs<FNiagaraExt_StackInputData_Enum>(D);
        }
        else if(T==TEXT("linked")&&X->Type==EJson::String)
        {
            FNiagaraExt_StackInputData_Linked D;D.LinkedVariable.Type=Schema.Type;D.LinkedVariable.Name=FName(*X->AsString());
            V.InitializeAs<FNiagaraExt_StackInputData_Linked>(D);
        }
        else {ReportError(C,TEXT("Expected a named enum entry or parameter binding"));return false;}
    }
    else if(T==TEXT("struct")&&X->Type==EJson::Object)
    {
        auto* Type=LoadObject<UScriptStruct>(nullptr,*String(O,TEXT("struct")));
        if(!Type){ReportError(C,TEXT("Struct type was not found"));return false;}
        V.InitializeAs(Type);FText Failure;
        if(!FJsonObjectConverter::JsonObjectToUStruct(X->AsObject().ToSharedRef(),Type,V.GetMutableMemory(),0,0,true,&Failure))
        {ReportError(C,TEXT("Invalid struct value: ")+Failure.ToString());return false;}
    }
    else {ReportError(C,TEXT("Unsupported typed input: ")+T);return false;}
    return true;
}
bool VariableValue(const J& O,FNiagaraTypeDefinition& Type,FNiagaraExt_VariableValue& Value,UObject* Owner,FNiagaraExternalEditContext& C)
{
    const FString Kind=String(O,TEXT("type"));
    if(Kind==TEXT("enum"))
    {
        auto* Enum=LoadObject<UEnum>(nullptr,*String(O,TEXT("enum")));const FName Entry=Name(O,TEXT("value"));
        if(!Enum||Enum->GetValueByName(Entry)==INDEX_NONE){ReportError(C,TEXT("Expected an enum asset/type and valid qualified entry"));return false;}
        Type=FNiagaraTypeDefinition(Enum);FNiagaraExt_VariableValue_Enum D;D.Enum=Enum;D.EnumName=Entry;
        Value.InitializeAs<FNiagaraExt_VariableValue_Enum>(D);return true;
    }
    if(Kind==TEXT("object")||Kind==TEXT("data-interface"))
    {
        auto* Class=LoadClass<UObject>(nullptr,*String(O,TEXT("class")));if(!Class){ReportError(C,TEXT("Expected an installed object class"));return false;}
        Type=FNiagaraTypeDefinition(Class);
        if(Kind==TEXT("data-interface"))
        {
            const TSharedPtr<FJsonObject>* Properties=nullptr;
            if(!Class->IsChildOf(UNiagaraDataInterface::StaticClass())||Class->HasAnyClassFlags(CLASS_Abstract)||!O->TryGetObjectField(TEXT("value"),Properties))
            {ReportError(C,TEXT("Expected a concrete DI class and property object"));return false;}
            auto* DI=NewObject<UNiagaraDataInterface>(Owner,Class,NAME_None,RF_Transactional);
            if(!U::GetPropertyProvider().SetObjectProperties(DI,Json(*Properties))){ReportError(C,TEXT("Invalid DI properties"));return false;}
            DI->PostEditChange();FNiagaraExt_VariableValue_DataInterface D;D.DataInterfaceClass=Class;D.DataInterface=DI;
            Value.InitializeAs<FNiagaraExt_VariableValue_DataInterface>(D);return true;
        }
        if(!O->HasField(TEXT("value"))){ReportError(C,TEXT("Object value is required; null clears it"));return false;}
        UObject* Object=nullptr;
        if(O->Values[TEXT("value")]->Type!=EJson::Null)
        {
            Object=LoadObject<UObject>(nullptr,*String(O,TEXT("value")));
            if(!Object||!Object->IsA(Class)){ReportError(C,TEXT("Object asset does not match its class"));return false;}
        }
        FNiagaraExt_VariableValue_Object D;D.ObjectClass=Class;D.Object=Object;Value.InitializeAs<FNiagaraExt_VariableValue_Object>(D);return true;
    }
    if(Kind==TEXT("dynamic-input")||Kind==TEXT("linked")||Kind==TEXT("expression"))
    {ReportError(C,TEXT("Declare a concrete parameter first, then configure its stack input"));return false;}
    FNiagaraExt_StackInputValue V;if(!InputValue(O,V,C))return false;
    Type=FNiagaraTypeDefinition(const_cast<UScriptStruct*>(V.GetScriptStruct()),FNiagaraTypeDefinition::EAllowUnfriendlyStruct::Allow);
    Value.InitializeAs(V.GetScriptStruct(),V.GetMemory());return true;
}
#include "NiagaraStandaloneStages.inl"
void Apply(UNiagaraSystem* S,const J& O,FNiagaraExternalEditContext& C)
{
    const FString Op=String(O,TEXT("op"));auto R=Reference(S,O);
    if(Op==TEXT("add-emitter"))
    {
        const FString Template=String(O,TEXT("asset"),String(O,TEXT("template")));UNiagaraEmitter* E=nullptr;
        if(!EmitterNameAllowed(R.EmitterName,C))return;
        for(const auto& H:S->GetEmitterHandles())if(H.GetName()==R.EmitterName){ReportError(C,TEXT("Emitter already exists"));return;}
        if(Template.IsEmpty())
        {
            E=NewObject<UNiagaraEmitter>(GetTransientPackage(),NAME_None,RF_Transactional);
            UNiagaraEmitterFactoryNew::InitializeEmitter(E,false);
            // A blank seed is transient, not a persisted parent asset. UE's native
            // AddEmitterHandle removes inheritance for non-inheritable sources.
            E->bIsInheritable=false;
        }
        else E=LoadObject<UNiagaraEmitter>(nullptr,*Template);
        if(!E){ReportError(C,TEXT("Emitter asset not found"));return;}
        FNiagaraExt_EmitterTopology T;U::AddEmitter(E,R.EmitterName,T,C);
    }
    else if(Op==TEXT("remove-emitter"))U::RemoveEmitter(R,C);
    else if(ApplyStage(S,O,C)){}
    else if(Op==TEXT("rename-emitter")||Op==TEXT("duplicate-emitter"))
    {
        auto* Emitter=R.GetEmitter(C);const FName NewName=Name(O,TEXT("name"));if(!Emitter||C.HasErrors())return;
        if(!EmitterNameAllowed(NewName,C))return;
        for(const auto& H:S->GetEmitterHandles())if(H.GetName()==NewName){ReportError(C,TEXT("Emitter name already exists"));return;}
        S->Modify();
        if(Op==TEXT("rename-emitter"))Emitter->SetName(NewName,*S);
        else S->DuplicateEmitterHandle(*Emitter,NewName);
    }
    else if(Op==TEXT("add-module"))
    {
        if(O->HasField(TEXT("after")))R.ModuleName=Name(O,TEXT("after"));
        const auto* M=LoadObject<UNiagaraScript>(nullptr,*String(O,TEXT("asset")));
        if(!M){ReportError(C,TEXT("Module asset not found"));return;}FNiagaraExt_ModuleTopology T;U::AddModule(R,M,T,C);
    }
    else if(Op==TEXT("remove-module"))U::RemoveModule(R,C);
    else if(Op==TEXT("scratch-module"))
    {
        auto* Module=R.GetModule(C);if(!Module||C.HasErrors())return;
        UNiagaraScript* Original=Module->GetModuleNode().FunctionScript;
        const FString NewName=String(O,TEXT("name"));
        if(!Original||NewName.IsEmpty()||NewName.Contains(TEXT("."))||NewName.Contains(TEXT(":"))||StaticFindObject(UObject::StaticClass(),S,*NewName))
        {ReportError(C,TEXT("Expected an existing script and unused scratch name"));return;}
        auto* Scratch=DuplicateObject<UNiagaraScript>(Original,S,FName(*NewName));Scratch->ClearFlags(RF_Public|RF_Standalone);
        S->Modify();S->ScratchPadScripts.Add(Scratch);Module->ReassignModuleScript(Scratch);
    }
    else if(Op==TEXT("add-set-parameters")||Op==TEXT("add-set-parameter"))
    {
        const TArray<TSharedPtr<FJsonValue>>* Params=nullptr;
        if(!O->TryGetArrayField(TEXT("parameters"),Params)||Params->IsEmpty()){ReportError(C,TEXT("Expected non-empty parameters array"));return;}
        TArray<FNiagaraExt_SetParameterEntry> Entries;
        for(const auto& P:*Params)
        {
            if(P->Type!=EJson::Object){ReportError(C,TEXT("Parameter entry must be an object"));return;}
            const J Item=P->AsObject();
            FNiagaraExt_SetParameterEntry Entry;Entry.Variable.Name=Name(Item,TEXT("name"));
            if(Entry.Variable.Name.IsNone()){ReportError(C,TEXT("Parameter needs a qualified name"));return;}
            if(!VariableValue(Item,Entry.Variable.Type,Entry.DefaultValue,S,C))return;Entries.Add(Entry);
        }
        if(O->HasField(TEXT("after")))R.ModuleName=Name(O,TEXT("after"));
        FNiagaraExt_ModuleTopology T;
        if(Op==TEXT("add-set-parameters"))U::AddSetParametersModule(R,Entries,T,C);
        else for(const auto& Entry:Entries)U::AddSetParameterEntry(R,Entry,T,C);
    }
    else if(Op==TEXT("remove-set-parameter"))U::RemoveSetParameterEntry(R,Name(O,TEXT("name")),C);
    else if(Op==TEXT("move-module"))
    {
        auto* Module=R.GetModule(C);auto* Group=R.GetScript(C);auto* Emitter=R.GetEmitter(C,false);
        if(!Module||!Group||C.HasErrors())return;
        if(!Module->CanMoveAndDelete()){ReportError(C,TEXT("This inherited or required module cannot be moved"));return;}
        const FGuid EmitterId=Emitter?Emitter->GetId():FGuid();
        auto* Source=FNiagaraEditorUtilities::GetScriptFromSystem(*S,EmitterId,Group->GetScriptUsage(),Group->GetScriptUsageId());
        const int32 Index=int32(O->GetNumberField(TEXT("index")));
        FNiagaraExt_ScriptStackTopology Stack;U::GetScriptStackTopology(R,Stack,C);
        if(C.HasErrors()||!Source||Index<0||Index>=Stack.Modules.Num()){ReportError(C,TEXT("Invalid module destination"));return;}
        const int32 SourceIndex=Module->GetModuleIndex();if(Index==SourceIndex)return;
        // UE takes an insertion boundary in the original stack, before removing
        // the source. Convert the CLI's final index to avoid a self-linked graph.
        const int32 InsertionIndex=Index>SourceIndex?Index+1:Index;
        S->Modify();
        UNiagaraNodeFunctionCall* Moved=nullptr;
        FNiagaraStackGraphUtilities::MoveModule(*Source,Module->GetModuleNode(),*S,EmitterId,Group->GetScriptUsage(),Group->GetScriptUsageId(),InsertionIndex,false,Moved);
        if(!Moved)ReportError(C,TEXT("Native module move failed"));
        else
        {
            Source->GetLatestSource()->MarkNotSynchronized(TEXT("Niagara CLI module reorder"));
            Group->RefreshChildren();S->PostEditChange();
        }
    }
    else if(Op==TEXT("set-user")||Op==TEXT("remove-user"))
    {
        const FString VariableName=String(O,TEXT("name"));
        if(!VariableName.StartsWith(TEXT("User."))){ReportError(C,TEXT("User parameter name must start with User."));return;}
        FNiagaraExt_UserVariables Existing;U::GetUserVariables(S,Existing,C);
        if(Op==TEXT("remove-user"))
        {
            const auto* Found=Existing.UserVariables.FindByPredicate([&](const FNiagaraExt_UserVariable& V){return V.Name==FName(*VariableName);});
            if(!Found){ReportError(C,TEXT("User parameter not found"));return;}
            U::RemoveUserVariable(S,*Found,C);return;
        }
        FNiagaraExt_UserVariable Variable;Variable.Name=FName(*VariableName);
        Variable.Description=FText::FromString(String(O,TEXT("description")));
        if(!VariableValue(O,Variable.Type,Variable.DefaultValue,S,C))return;
        for(const auto& Current:Existing.UserVariables)if(Current.Name==Variable.Name&&Current.Type!=Variable.Type)
        {ReportError(C,TEXT("Remove the existing user parameter before changing its type"));return;}
        U::AddUserVariable(S,Variable,C);
    }
    else if(Op==TEXT("module-enabled"))U::SetModuleEnabled(R,O->GetBoolField(TEXT("value")),C);
    else if(Op==TEXT("reset-input"))
    {
        auto* Input=R.GetInput(C);if(!Input||C.HasErrors())return;
        if(!Input->CanReset()){ReportError(C,TEXT("Input cannot be reset in this context"));return;}Input->Reset();
    }
    else if(Op==TEXT("input"))
    {
        if(String(O,TEXT("type"))==TEXT("object"))
        {
            auto* Input=R.GetInput(C);if(!Input||C.HasErrors())return;
            auto* Class=Input->GetInputType().GetClass();auto* Object=LoadObject<UObject>(nullptr,*String(O,TEXT("value")));
            if(!Class||Class->IsChildOf(UNiagaraDataInterface::StaticClass())||!Object||!Object->IsA(Class))
            {ReportError(C,TEXT("Object asset does not match this input type"));return;}
            Input->SetObjectAssetValue(Object);
        }
        else {FNiagaraExt_StackInputValue V;if(InputValue(O,V,C,&R))U::SetStackInputData(R,V,C);}
    }
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
    else if(Op==TEXT("add-renderer"))
    {
        auto* Class=LoadClass<UNiagaraRendererProperties>(nullptr,*String(O,TEXT("class")));
        if(!Class||Class->HasAnyClassFlags(CLASS_Abstract)){ReportError(C,TEXT("Expected an installed concrete Niagara renderer class"));return;}
        FNiagaraExt_RendererRef Out;U::AddRenderer(R,Class,Out,C);
    }
    else if(Op==TEXT("remove-renderer"))U::RemoveRenderer(R,C);
    else ReportError(C,TEXT("Unsupported operation: ")+Op);
}
#include "NiagaraStandaloneQueries.inl"

J Describe(UNiagaraSystem* S,FNiagaraExternalEditContext& C)
{
    J Out=MakeShared<FJsonObject>();Out->SetStringField(TEXT("schema"),TEXT("ue-niagara-snapshot/1"));
    Out->SetStringField(TEXT("asset"),S->GetPathName());Out->SetBoolField(TEXT("valid"),S->IsValid());
    Out->SetBoolField(TEXT("readyToRun"),S->IsReadyToRun());
    FNiagaraExt_SystemSummary Summary;U::GetSystemSummary(S,Summary,C);Out->SetObjectField(TEXT("summary"),Struct(Summary));
    FNiagaraExt_UserVariables UserVariables;U::GetUserVariables(S,UserVariables,C);Out->SetObjectField(TEXT("userVariables"),Struct(UserVariables));
    FNiagaraExt_SystemCompileState Compile;U::GetSystemCompileState(S,Compile,C);Out->SetObjectField(TEXT("compile"),Struct(Compile));
    FNiagaraExt_SystemDependencies Dependencies;U::GetSystemDependencies(S,Dependencies,C);Out->SetObjectField(TEXT("staticDependencies"),Struct(Dependencies));
    TArray<TSharedPtr<FJsonValue>> Emitters;
    for(const auto& H:S->GetEmitterHandles())
    {
        auto E=MakeShared<FJsonObject>();FNiagaraExt_StackItemReference R(S,H.GetName());
        E->SetStringField(TEXT("handleId"),H.GetId().ToString(EGuidFormats::DigitsWithHyphens));
        E->SetObjectField(TEXT("stacks"),StageInventory(S,H.GetName(),C));
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

#include "NiagaraStandaloneRoundTrip.inl"

UNiagaraStandaloneCommandlet::UNiagaraStandaloneCommandlet()
    { IsClient=false;IsServer=false;IsEditor=true;LogToConsole=true;ShowErrorCount=true;UseCommandletResultAsExitCode=true; }

int32 UNiagaraStandaloneCommandlet::Main(const FString& Params)
{
    FString Input,Output,Text;
    if(!FParse::Value(*Params,TEXT("Request="),Input)||!FParse::Value(*Params,TEXT("Response="),Output)||
       !FFileHelper::LoadFileToString(Text,*Input))return 2;
    J Q;if(!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Q)||!Q)return 2;
    J Result=MakeShared<FJsonObject>();FNiagaraExternalEditContext Errors;UNiagaraSystem* S=nullptr;UObject* SaveObject=nullptr;
    FString Asset=String(Q,TEXT("asset")),Op=String(Q,TEXT("operation")),Backup;
    const FString CompilePolicy=String(Q,TEXT("compilePolicy"),TEXT("require-valid"));
    const bool Mutating=Op==TEXT("create")||Op==TEXT("edit")||Op==TEXT("save");
    Result->SetStringField(TEXT("engine"),FEngineVersion::Current().ToString());
    Result->SetStringField(TEXT("compilePolicy"),CompilePolicy);
    if(CompilePolicy!=TEXT("require-valid")&&CompilePolicy!=TEXT("allow-errors")&&CompilePolicy!=TEXT("defer"))ReportError(Errors,TEXT("Invalid compile policy"));
    else if(Op==TEXT("catalog"))Catalog(Q,Result,Errors);
    else if(Op==TEXT("schema"))SchemaQuery(Q,Result,Errors);
    else if(Op==TEXT("export-document")||Op==TEXT("import-document"))RoundTripDocument(Q,Result,Errors);
    else if(!FPackageName::IsValidLongPackageName(Asset)||!Asset.StartsWith(TEXT("/Game/")))ReportError(Errors,TEXT("Expected a /Game package path"));
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
            if(String(Q,TEXT("assetKind"),TEXT("system"))==TEXT("emitter"))
            {
                const FName EmitterName(*FPackageName::GetShortName(Asset));
                if(EmitterNameAllowed(EmitterName,Errors))
                {
                    auto* Emitter=NewObject<UNiagaraEmitter>(CreatePackage(*Asset),EmitterName,RF_Public|RF_Standalone|RF_Transactional);
                    UNiagaraEmitterFactoryNew::InitializeEmitter(Emitter,false);Emitter->SetUniqueEmitterName(EmitterName.ToString());
                    FAssetRegistryModule::AssetCreated(Emitter);SaveObject=Emitter;S=EmitterEditingSystem(Emitter);
                }
            }
            else
            {
                FString Template=String(Q,TEXT("template"));UNiagaraSystem* Source=nullptr;
                if(!Template.IsEmpty()){Source=LoadObject<UNiagaraSystem>(nullptr,*Template);if(!Source)ReportError(Errors,TEXT("System template not found"));}
                if(!Errors.HasErrors())S=U::CreateNiagaraSystem(FPackageName::GetShortName(Asset),FPackageName::GetLongPackagePath(Asset),Source,Errors);
            }
        }
    }
    else if(Op==TEXT("read")||Op==TEXT("edit")||Op==TEXT("save")||Op==TEXT("compile"))
    {
        SaveObject=LoadObject<UObject>(nullptr,*Asset);S=Cast<UNiagaraSystem>(SaveObject);
        if(auto* Emitter=Cast<UNiagaraEmitter>(SaveObject))S=EmitterEditingSystem(Emitter);
        if(!S)ReportError(Errors,TEXT("Expected a Niagara System or Emitter asset"));
    }
    else ReportError(Errors,TEXT("Unsupported command"));
    if(S&&!Errors.HasErrors())
    {
        if(!SaveObject)SaveObject=S;
        const bool EmitterAsset=SaveObject!=S;
        Result->SetStringField(TEXT("assetKind"),EmitterAsset?TEXT("emitter"):TEXT("system"));
        S->AddToRoot();S->WaitForCompilationComplete(true,false);
        {
            const TArray<TSharedPtr<FJsonValue>>* Ops=nullptr;
            if(Mutating&&Q->TryGetArrayField(TEXT("operations"),Ops))
                for(const auto& V:*Ops)
                {
                    if(V->Type!=EJson::Object){ReportError(Errors,TEXT("Operation must be object"));break;}
                    J Operation=V->AsObject();
                    if(String(Operation,TEXT("op"))==TEXT("asset-properties"))
                    {
                        const TSharedPtr<FJsonObject>* Properties=nullptr;
                        J Schema;const FString SchemaText=U::GetPropertyProvider().ListStructProperties(SaveObject->GetClass(),true);
                        if(!Operation->TryGetObjectField(TEXT("properties"),Properties)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(SchemaText),Schema))
                        {ReportError(Errors,TEXT("Expected editable asset properties"));break;}
                        bool Valid=true;
                        for(const auto& Pair:(*Properties)->Values)
                        {
                            bool Found=false;for(const auto& Declared:Schema->Values)if(FString(*Declared.Key).Equals(*Pair.Key,ESearchCase::IgnoreCase)){Found=true;break;}
                            if(!Found){ReportError(Errors,FString(TEXT("Unknown or non-editable asset property: "))+FString(*Pair.Key));Valid=false;}
                        }
                        if(!Valid)break;SaveObject->Modify();
                        if(!U::GetPropertyProvider().SetObjectProperties(SaveObject,Json(*Properties))){ReportError(Errors,TEXT("Asset property conversion failed"));break;}
                        SaveObject->PostEditChange();continue;
                    }
                    if(EmitterAsset)
                    {
                        const FString Action=String(Operation,TEXT("op"));
                        if(Action==TEXT("add-emitter")||Action==TEXT("remove-emitter")||Action==TEXT("duplicate-emitter")||Action==TEXT("set-user")||Action==TEXT("remove-user")||Action==TEXT("system-properties")||String(Operation,TEXT("script")).StartsWith(TEXT("System")))
                        {ReportError(Errors,TEXT("This operation belongs to a System, not a standalone Emitter asset"));break;}
                        if(!Operation->HasField(TEXT("emitter")))Operation->SetStringField(TEXT("emitter"),S->GetEmitterHandles()[0].GetName().ToString());
                    }
                    FNiagaraExternalEditContext Context(S);Apply(S,Operation,Context);
                    Errors.Errors.Append(Context.Errors);if(Errors.HasErrors())break;
                }
        }
        if(!Errors.HasErrors()&&(Mutating||Op==TEXT("compile"))&&CompilePolicy!=TEXT("defer"))
        {
            S->RequestCompile(false);S->WaitForCompilationComplete(true,false);
            FNiagaraExternalEditContext DiagnosticContext(S);FNiagaraExt_SystemCompileState Compilation;
            U::GetSystemCompileState(S,Compilation,DiagnosticContext);Result->SetObjectField(TEXT("compilation"),Struct(Compilation));
            // Empty systems may be authored, but systems with emitters must compile.
            if(S->GetEmitterHandles().Num()>0&&!S->IsValid()&&CompilePolicy==TEXT("require-valid"))ReportError(Errors,TEXT("Native Niagara compile failed"));
        }
        Result->SetBoolField(TEXT("compileValid"),S->IsValid());
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
                IFileManager::Get().MakeDirectory(*FPaths::GetPath(File),true);SaveObject->MarkPackageDirty();
                FSavePackageArgs Args;Args.TopLevelFlags=RF_Public|RF_Standalone;Args.SaveFlags=SAVE_NoError;
                if(!UPackage::SavePackage(SaveObject->GetOutermost(),SaveObject,*File,Args))ReportError(Errors,TEXT("Package save failed"));
                else Result->SetBoolField(TEXT("saved"),true);
            }
        }
        if(!Errors.HasErrors())
        {
            FNiagaraExternalEditContext Context(S);auto Snapshot=Describe(S,Context);Snapshot->SetStringField(TEXT("asset"),SaveObject->GetPathName());
            Snapshot->SetStringField(TEXT("assetKind"),EmitterAsset?TEXT("emitter"):TEXT("system"));
            Result->SetObjectField(TEXT("snapshot"),Snapshot);Errors.Errors.Append(Context.Errors);
        }
        S->RemoveFromRoot();
    }
    TArray<TSharedPtr<FJsonValue>> Messages;for(const FText& E:Errors.Errors)Messages.Add(MakeShared<FJsonValueString>(E.ToString()));
    Result->SetArrayField(TEXT("errors"),Messages);Result->SetBoolField(TEXT("ok"),!Errors.HasErrors());Result->SetStringField(TEXT("backup"),Backup);
    IFileManager::Get().MakeDirectory(*FPaths::GetPath(Output),true);
    if(!FFileHelper::SaveStringToFile(Json(Result),*Output,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))return 4;
    return Errors.HasErrors()?3:0;
}
