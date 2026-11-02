// Native event/simulation stacks. Identity is the script usage GUID, not its label.
FGuid RequestedGuid(const J& O,const TCHAR* Key,FNiagaraExternalEditContext& C,bool Generate=false)
{
    const FString Text=String(O,Key);FGuid Id;
    if(Text.IsEmpty()&&Generate)return FGuid::NewGuid();
    if(!FGuid::Parse(Text,Id)||!Id.IsValid())ReportError(C,FString(TEXT("Expected a valid GUID: "))+Key);
    return Id;
}

bool ApplyStage(UNiagaraSystem* S,const J& O,FNiagaraExternalEditContext& C)
{
    const FString Op=String(O,TEXT("op"));
    if(Op!=TEXT("add-stage")&&Op!=TEXT("remove-stage")&&Op!=TEXT("stage-properties")&&Op!=TEXT("stage-enabled")&&Op!=TEXT("move-stage")&&
       Op!=TEXT("add-event-handler")&&Op!=TEXT("event-properties")&&Op!=TEXT("remove-event-handler"))return false;
    auto R=Reference(S,O);auto* H=R.GetEmitter(C);if(!H||C.HasErrors())return true;
    const auto Instance=H->GetInstance();auto* Emitter=Instance.Emitter.Get();auto* Data=Instance.GetEmitterData();
    if(!Emitter||!Data){ReportError(C,TEXT("This operation requires a stateful emitter"));return true;}
    const FGuid Version=Data->Version.VersionGuid;
    const bool Adding=Op==TEXT("add-stage")||Op==TEXT("add-event-handler");
    const FGuid Id=RequestedGuid(O,TEXT("usageId"),C,Adding);if(C.HasErrors())return true;
    const TSharedPtr<FJsonObject>* Properties=nullptr;O->TryGetObjectField(TEXT("properties"),Properties);
    if(Properties&&((*Properties)->HasField(TEXT("Script"))||(*Properties)->HasField(TEXT("script"))||(*Properties)->HasField(TEXT("OuterEmitterVersion"))))
    {ReportError(C,TEXT("Script identity cannot be replaced through stage properties"));return true;}
    auto* Source=Cast<UNiagaraScriptSource>(Data->GraphSource);
    if(!Source||!Source->NodeGraph){ReportError(C,TEXT("Emitter has no editable native graph"));return true;}
    if(Adding)
    {
        if(Data->GetSimulationStageById(Id)||Data->GetEventHandlerByIdUnsafe(Id)){ReportError(C,TEXT("Script usage GUID already exists"));return true;}
        const bool Event=Op==TEXT("add-event-handler");
        if(Event&&Data->SimTarget!=ENiagaraSimTarget::CPUSim){ReportError(C,TEXT("Native event handlers require CPU simulation"));return true;}
        if(!Event&&Data->SimTarget!=ENiagaraSimTarget::GPUComputeSim){ReportError(C,TEXT("Native simulation stages require GPU simulation"));return true;}
        Emitter->Modify();S->Modify();
        const ENiagaraScriptUsage Usage=Event?ENiagaraScriptUsage::ParticleEventScript:ENiagaraScriptUsage::ParticleSimulationStageScript;
        UNiagaraScript* Script=nullptr;
        if(Event)
        {
            FNiagaraEventScriptProperties P;
            if(Properties)
            {
                FText Failure;
                if(!FJsonObjectConverter::JsonObjectToUStruct((*Properties).ToSharedRef(),&P,0,0,false,&Failure))
                {ReportError(C,Failure.ToString());return true;}
            }
            if(O->HasField(TEXT("sourceEmitter")))
            {
                const FName Sender=Name(O,TEXT("sourceEmitter"));const auto* Found=S->GetEmitterHandles().FindByPredicate([&](const FNiagaraEmitterHandle& E){return E.GetName()==Sender;});
                if(!Found){ReportError(C,TEXT("Source emitter not found"));return true;}P.SourceEmitterID=Found->GetId();
            }
            Script=NewObject<UNiagaraScript>(Emitter,NAME_None,RF_Transactional);P.Script=Script;
            Script->SetUsage(Usage);Script->SetUsageId(Id);Script->SetLatestSource(Source);
            FNiagaraStackGraphUtilities::ResetGraphForOutput(*Source->NodeGraph,Usage,Id);
            Emitter->AddEventHandler(P,Version);
        }
        else
        {
            const FString ClassPath=String(O,TEXT("class"),TEXT("/Script/Niagara.NiagaraSimulationStageGeneric"));
            auto* Class=LoadClass<UNiagaraSimulationStageBase>(nullptr,*ClassPath);
            if(!Class||Class->HasAnyClassFlags(CLASS_Abstract)){ReportError(C,TEXT("Expected an installed concrete Simulation Stage class"));return true;}
            auto* Stage=NewObject<UNiagaraSimulationStageBase>(Emitter,Class,NAME_None,RF_Transactional);
            Stage->SimulationStageName=Name(O,TEXT("name"));Stage->OuterEmitterVersion=Version;
            if(Properties&&!U::GetPropertyProvider().SetObjectProperties(Stage,Json(*Properties))){ReportError(C,TEXT("Invalid stage properties"));return true;}
            Script=NewObject<UNiagaraScript>(Stage,NAME_None,RF_Transactional);Stage->Script=Script;
            Script->SetUsage(Usage);Script->SetUsageId(Id);Script->SetLatestSource(Source);
            FNiagaraStackGraphUtilities::ResetGraphForOutput(*Source->NodeGraph,Usage,Id);
            Emitter->AddSimulationStage(Stage,Version);
        }
    }
    else if(Op==TEXT("remove-stage")||Op==TEXT("remove-event-handler"))
    {
        R.ScriptName=FName(*((Op==TEXT("remove-stage")?FString(TEXT("ParticleSimulationStageScript")):FString(TEXT("ParticleEventScript")))+TEXT("@")+Id.ToString(EGuidFormats::DigitsWithHyphens)));
        auto* Group=R.GetScript(C);if(!Group||C.HasErrors())return true;
        FText Reason;if(!Group->SupportsDelete()||!Group->TestCanDeleteWithMessage(Reason)){ReportError(C,TEXT("Stack cannot be removed: ")+Reason.ToString());return true;}
        Group->Delete();
    }
    else if(Op==TEXT("event-properties"))
    {
        auto* P=Data->GetEventHandlerByIdUnsafe(Id);if(!P||!Properties){ReportError(C,TEXT("Event handler or properties not found"));return true;}
        Emitter->Modify();FText Failure;
        if(!FJsonObjectConverter::JsonObjectToUStruct((*Properties).ToSharedRef(),P,0,0,false,&Failure)){ReportError(C,Failure.ToString());return true;}
    }
    else
    {
        auto* Stage=Data->GetSimulationStageById(Id);if(!Stage){ReportError(C,TEXT("Simulation stage not found"));return true;}
        Emitter->Modify();Stage->Modify();
        if(Op==TEXT("stage-enabled"))Stage->SetEnabled(O->GetBoolField(TEXT("value")));
        else if(Op==TEXT("move-stage"))
        {
            const int32 Index=int32(O->GetNumberField(TEXT("index")));
            if(Index<0||Index>=Data->GetSimulationStages().Num()){ReportError(C,TEXT("Invalid stage destination"));return true;}
            Emitter->MoveSimulationStageToIndex(Stage,Index,Version);
        }
        else if(!Properties||!U::GetPropertyProvider().SetObjectProperties(Stage,Json(*Properties))){ReportError(C,TEXT("Invalid stage properties"));return true;}
        Stage->PostEditChange();
    }
    Data->SpawnScriptProps.Script->GetLatestSource()->MarkNotSynchronized(TEXT("Native CLI stage edit"));Emitter->PostEditChange();S->PostEditChange();return true;
}

J StageInventory(UNiagaraSystem* S,FName EmitterName,FNiagaraExternalEditContext& C)
{
    J Result=MakeShared<FJsonObject>();auto R=FNiagaraExt_StackItemReference(S,EmitterName);auto* H=R.GetEmitter(C);
    if(!H||!H->GetEmitterData())return Result;auto* Data=H->GetEmitterData();
    Result->SetBoolField(TEXT("hasParent"),Data->GetParent().Emitter!=nullptr);
    TArray<TSharedPtr<FJsonValue>> Stacks;
    auto Add=[&](UNiagaraScript* Script,const FString& Label,const J& Properties,const FString& PropertySchema)
    {
        if(!Script)return;
        J Stack=MakeShared<FJsonObject>();const FString Usage=StaticEnum<ENiagaraScriptUsage>()->GetNameStringByValue(int64(Script->GetUsage()));
        Stack->SetStringField(TEXT("usage"),Usage);Stack->SetStringField(TEXT("usageId"),Script->GetUsageId().ToString(EGuidFormats::DigitsWithHyphens));
        Stack->SetStringField(TEXT("name"),Label);Stack->SetObjectField(TEXT("properties"),Properties);Stack->SetStringField(TEXT("propertySchemaJson"),PropertySchema);
        FNiagaraExt_StackItemReference StackRef(S,EmitterName,FName(*(Usage+TEXT("@")+Script->GetUsageId().ToString(EGuidFormats::DigitsWithHyphens))));
        FNiagaraExt_ScriptStackTopology Topology;U::GetScriptStackTopology(StackRef,Topology,C);Stack->SetObjectField(TEXT("topology"),Struct(Topology));
        Stacks.Add(MakeShared<FJsonValueObject>(Stack));
    };
    for(const auto& Event:Data->GetEventHandlers())Add(Event.Script,Event.SourceEventName.ToString(),Struct(Event),U::GetPropertyProvider().ListStructProperties(FNiagaraEventScriptProperties::StaticStruct(),true));
    for(auto* Stage:Data->GetSimulationStages())
    {
        Add(Stage->Script,Stage->SimulationStageName.ToString(),ExportStruct(Stage->GetClass(),Stage),U::GetPropertyProvider().ListStructProperties(Stage->GetClass(),true));
    }
    Result->SetArrayField(TEXT("extraStacks"),Stacks);return Result;
}
