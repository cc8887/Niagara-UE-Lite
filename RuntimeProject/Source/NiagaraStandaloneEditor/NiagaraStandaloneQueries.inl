J InstancedValue(const FInstancedStruct& Value)
{
    J O=MakeShared<FJsonObject>();O->SetBoolField(TEXT("isSet"),Value.IsValid());
    if(Value.IsValid()){O->SetStringField(TEXT("type"),Value.GetScriptStruct()->GetPathName());O->SetObjectField(TEXT("data"),ExportStruct(Value.GetScriptStruct(),Value.GetMemory()));}
    return O;
}

J TypeInfo(const FNiagaraTypeDefinition& Type)
{
    J O=MakeShared<FJsonObject>();O->SetStringField(TEXT("name"),Type.GetName());
    if(auto* Enum=Type.GetEnum())
    {
        O->SetStringField(TEXT("enum"),Enum->GetPathName());TArray<TSharedPtr<FJsonValue>> Entries;
        for(int32 I=0;I<Enum->NumEnums();++I)
        {
            J E=MakeShared<FJsonObject>();E->SetStringField(TEXT("name"),Enum->GetNameByIndex(I).ToString());
            E->SetStringField(TEXT("displayName"),Enum->GetDisplayNameTextByIndex(I).ToString());E->SetNumberField(TEXT("value"),Enum->GetValueByIndex(I));
            Entries.Add(MakeShared<FJsonValueObject>(E));
        }
        O->SetArrayField(TEXT("entries"),Entries);
    }
    else if(auto* Class=Type.GetClass()){O->SetStringField(TEXT("class"),Class->GetPathName());O->SetBoolField(TEXT("dataInterface"),Type.IsDataInterface());}
    else if(auto* Value=Type.GetScriptStruct())O->SetStringField(TEXT("struct"),Value->GetPathName());
    return O;
}

void Catalog(const J& Q,const J& Out,FNiagaraExternalEditContext& C)
{
    const FString Kind=String(Q,TEXT("kind")),Search=String(Q,TEXT("search")),Root=String(Q,TEXT("root"),TEXT("/"));
    int32 Offset=Q->HasField(TEXT("offset"))?int32(Q->GetNumberField(TEXT("offset"))):0;
    int32 Limit=Q->HasField(TEXT("limit"))?int32(Q->GetNumberField(TEXT("limit"))):200;
    if(Offset<0||Limit<1||Limit>5000){ReportError(C,TEXT("Invalid catalog page"));return;}
    TArray<J> Items;
    if(Kind==TEXT("renderers")||Kind==TEXT("data-interfaces")||Kind==TEXT("stage-classes"))
    {
        UClass* Base=Kind==TEXT("renderers")?UNiagaraRendererProperties::StaticClass():Kind==TEXT("stage-classes")?UNiagaraSimulationStageBase::StaticClass():UNiagaraDataInterface::StaticClass();
        for(TObjectIterator<UClass> It;It;++It)
        {
            UClass* Class=*It;
            if(!Class->IsChildOf(Base)||Class->HasAnyClassFlags(CLASS_Abstract|CLASS_Deprecated|CLASS_NewerVersionExists))continue;
            if(!Search.IsEmpty()&&!Class->GetPathName().Contains(Search))continue;
            J O=MakeShared<FJsonObject>();O->SetStringField(TEXT("asset"),Class->GetPathName());O->SetStringField(TEXT("name"),Class->GetName());Items.Add(O);
        }
    }
    else
    {
        UClass* Class=nullptr;
        if(Kind==TEXT("emitters"))Class=UNiagaraEmitter::StaticClass();
        else if(Kind==TEXT("systems"))Class=UNiagaraSystem::StaticClass();
        else if(Kind==TEXT("materials"))Class=UMaterialInterface::StaticClass();
        else if(Kind==TEXT("textures"))Class=UTexture::StaticClass();
        else if(Kind==TEXT("meshes"))Class=UStaticMesh::StaticClass();
        else if(Kind==TEXT("assets"))Class=LoadClass<UObject>(nullptr,*String(Q,TEXT("class")));
        else if(Kind==TEXT("modules")||Kind==TEXT("dynamic-inputs"))Class=UNiagaraScript::StaticClass();
        else {ReportError(C,TEXT("Unknown catalog kind"));return;}
        if(!Class){ReportError(C,TEXT("Expected an installed asset class"));return;}
        auto& Registry=FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get();
        Registry.SearchAllAssets(true);FARFilter Filter;Filter.ClassPaths.Add(Class->GetClassPathName());Filter.bRecursiveClasses=true;
        if(Root!=TEXT("/")){Filter.PackagePaths.Add(FName(*Root));Filter.bRecursivePaths=true;}
        TArray<FAssetData> Assets;Registry.GetAssets(Filter,Assets);
        for(const auto& A:Assets)
        {
            if(!FPackageName::DoesPackageExist(A.PackageName.ToString()))continue;
            const FString Path=A.GetSoftObjectPath().ToString();if(!Search.IsEmpty()&&!Path.Contains(Search))continue;
            J O=MakeShared<FJsonObject>();
            if(Class==UNiagaraScript::StaticClass())
            {
                auto* Script=Cast<UNiagaraScript>(A.GetAsset());if(!Script)continue;
                const auto Usage=Script->GetUsage();
                if(Usage!=(Kind==TEXT("modules")?ENiagaraScriptUsage::Module:ENiagaraScriptUsage::DynamicInput))continue;
                O->SetStringField(TEXT("usage"),StaticEnum<ENiagaraScriptUsage>()->GetNameStringByValue(int64(Usage)));
            }
            O->SetStringField(TEXT("asset"),Path);O->SetStringField(TEXT("name"),A.AssetName.ToString());
            FString Category;A.GetTagValue(TEXT("Category"),Category);O->SetStringField(TEXT("category"),Category);Items.Add(O);
        }
    }
    Items.Sort([](const J& A,const J& B){return A->GetStringField(TEXT("asset"))<B->GetStringField(TEXT("asset"));});
    TArray<TSharedPtr<FJsonValue>> Page;
    for(int32 I=Offset;I<FMath::Min(Items.Num(),Offset+Limit);++I)Page.Add(MakeShared<FJsonValueObject>(Items[I]));
    Out->SetStringField(TEXT("schema"),TEXT("ue-niagara-catalog/1"));Out->SetStringField(TEXT("kind"),Kind);
    Out->SetNumberField(TEXT("total"),Items.Num());Out->SetNumberField(TEXT("offset"),Offset);Out->SetArrayField(TEXT("items"),Page);
}

void SchemaQuery(const J& Q,const J& Out,FNiagaraExternalEditContext& C)
{
    const FString Kind=String(Q,TEXT("kind")),Asset=String(Q,TEXT("asset"));
    Out->SetStringField(TEXT("schema"),TEXT("ue-niagara-schema/1"));Out->SetStringField(TEXT("kind"),Kind);
    if(Kind==TEXT("asset"))
    {
        auto* Root=LoadObject<UObject>(nullptr,*Asset);if(!Root){ReportError(C,TEXT("Asset not found"));return;}
        const FString Text=U::GetPropertyProvider().ListStructProperties(Root->GetClass(),true);J Definition;
        Out->SetStringField(TEXT("class"),Root->GetClass()->GetPathName());Out->SetStringField(TEXT("propertySchemaJson"),Text);
        if(FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Definition))
        {
            TArray<FName> Names;for(const auto& Pair:Definition->Values)Names.Add(FName(*Pair.Key));
            Out->SetStringField(TEXT("propertiesJson"),U::GetPropertyProvider().GetObjectProperties(Root,Names));
        }
    }
    else if(Kind==TEXT("system")){FNiagaraExt_SystemSchema D;U::GetSystemSchema(D);Out->SetObjectField(TEXT("definition"),Struct(D));}
    else if(Kind==TEXT("emitter")){FNiagaraExt_EmitterSchema D;U::GetEmitterSchema(D);Out->SetObjectField(TEXT("definition"),Struct(D));}
    else if(Kind==TEXT("renderer"))
    {
        auto* Class=LoadClass<UNiagaraRendererProperties>(nullptr,*Asset);if(!Class){ReportError(C,TEXT("Renderer class not found"));return;}
        FNiagaraExt_RendererSchema D;U::GetRendererSchema(Class,D);Out->SetObjectField(TEXT("definition"),Struct(D));
    }
    else if(Kind==TEXT("data-interface"))
    {
        auto* Class=LoadClass<UNiagaraDataInterface>(nullptr,*Asset);if(!Class){ReportError(C,TEXT("Data interface class not found"));return;}
        FNiagaraExt_DataInterfaceSchema D;U::GetDataInterfaceSchema(Class,D);Out->SetObjectField(TEXT("definition"),Struct(D));
    }
    else if(Kind==TEXT("stage"))
    {
        auto* Class=LoadClass<UNiagaraSimulationStageBase>(nullptr,*Asset);if(!Class){ReportError(C,TEXT("Simulation Stage class not found"));return;}
        Out->SetStringField(TEXT("propertySchemaJson"),U::GetPropertyProvider().ListStructProperties(Class,true));
    }
    else if(Kind==TEXT("module")||Kind==TEXT("dynamic-input"))
    {
        auto* Script=LoadObject<UNiagaraScript>(nullptr,*Asset);if(!Script){ReportError(C,TEXT("Script asset not found"));return;}
        const auto* Data=Script->GetLatestScriptData();TArray<TSharedPtr<FJsonValue>> Usages,Versions;
        if(Data)
        {
            const auto* Enum=StaticEnum<ENiagaraScriptUsage>();
            for(int32 I=0;I<Enum->NumEnums();++I){const int64 Usage=Enum->GetValueByIndex(I);if(Usage>=0&&Usage<32&&(uint32(Data->ModuleUsageBitmask)&(uint32(1)<<Usage)))Usages.Add(MakeShared<FJsonValueString>(Enum->GetNameStringByIndex(I)));}
            Out->SetBoolField(TEXT("deprecated"),Data->bDeprecated);
        }
        for(const auto& V:Script->GetAllAvailableVersions())Versions.Add(MakeShared<FJsonValueObject>(Struct(V)));
        Out->SetArrayField(TEXT("versions"),Versions);Out->SetArrayField(TEXT("supportedUsages"),Usages);
        if(Kind==TEXT("module")){FNiagaraExt_ModuleSchema D;U::GetModuleSchema(Script,D,C);Out->SetObjectField(TEXT("definition"),Struct(D));}
        else {FNiagaraExt_DynamicInputSchema D;U::GetDynamicInputSchema(Script,D,C);Out->SetObjectField(TEXT("definition"),Struct(D));}
    }
    else if(Kind==TEXT("instance")||Kind==TEXT("input")||Kind==TEXT("stacks"))
    {
        UObject* Root=LoadObject<UObject>(nullptr,*Asset);auto* System=Cast<UNiagaraSystem>(Root);
        if(auto* Emitter=Cast<UNiagaraEmitter>(Root))
        {
            System=EmitterEditingSystem(Emitter);
            if(!Q->HasField(TEXT("emitter")))Q->SetStringField(TEXT("emitter"),System->GetEmitterHandles()[0].GetName().ToString());
        }
        if(!System){ReportError(C,TEXT("Expected a System or Emitter asset"));return;}
        System->WaitForCompilationComplete(true,false);FNiagaraExternalEditContext Context(System);auto R=Reference(System,Q);
        if(Kind==TEXT("stacks"))Out->SetObjectField(TEXT("stacks"),StageInventory(System,Name(Q,TEXT("emitter")),Context));
        else if(Kind==TEXT("instance"))
        {
            if(auto* Module=R.GetModule(Context))
            {
                Out->SetStringField(TEXT("nodeGuid"),Module->GetModuleNode().NodeGuid.ToString());
                Out->SetNumberField(TEXT("moduleIndex"),Module->GetModuleIndex());
            }
            FNiagaraExt_ModuleTopology Topology;U::GetModuleTopology(R,Topology,Context);Out->SetObjectField(TEXT("topology"),Struct(Topology));
            FNiagaraExt_ModuleSchema Definition;U::GetModuleSchema(R,Definition,Context);Out->SetObjectField(TEXT("definition"),Struct(Definition));
            FNiagaraExt_ModuleInputValues Values;U::GetModuleInputValues(R,Values,Context);Out->SetObjectField(TEXT("values"),Struct(Values));
        }
        else
        {
            FNiagaraExt_StackInputSchema Definition;U::GetStackInputSchema(R,Definition,Context);Out->SetObjectField(TEXT("definition"),Struct(Definition));
            Out->SetObjectField(TEXT("type"),TypeInfo(Definition.Type));
            FNiagaraExt_StackInputTopology Topology;U::GetStackInputTopology(R,Topology,Context);Out->SetObjectField(TEXT("topology"),Struct(Topology));
            FNiagaraExt_StackInputValue Value;U::GetStackInputData(R,Value,Context);Out->SetObjectField(TEXT("value"),InstancedValue(Value));
            if(Topology.bIsDynamic){FNiagaraExt_DynamicInputChainRef Chain;U::GetDynamicInputChain(R,Chain,Context);Out->SetObjectField(TEXT("dynamicChain"),InstancedValue(Chain));}
            if(Definition.Type.IsDataInterface()){FNiagaraExt_DataInterfaceSchema D;U::GetDataInterfaceSchema(Definition.Type.GetClass(),D);Out->SetObjectField(TEXT("dataInterfaceSchema"),Struct(D));}
            TArray<UNiagaraScript*> Scripts;U::GetAvailableDynamicInputs(Definition.Type,Scripts,Context);
            TArray<TSharedPtr<FJsonValue>> Choices;for(auto* Script:Scripts)Choices.Add(MakeShared<FJsonValueString>(Script->GetPathName()));
            Out->SetArrayField(TEXT("compatibleDynamicInputs"),Choices);
        }
        C.Errors.Append(Context.Errors);
    }
    else ReportError(C,TEXT("Unknown schema kind"));
}
