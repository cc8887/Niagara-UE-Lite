// Native object graph archive. Reflection remains editable; native custom
// serialization is retained per object instead of discarding private graph data.
namespace
{
class FNiagaraDocumentArchive : public FObjectAndNameAsStringProxyArchive
{
public:
    TSet<FString> References;
    TArray<FString> Missing;
    FNiagaraDocumentArchive(FArchive& Inner):FObjectAndNameAsStringProxyArchive(Inner,true)
    {
        ArNoDelta=true;ArIgnoreClassRef=true;ArIgnoreArchetypeRef=true;
    }
    using FObjectAndNameAsStringProxyArchive::operator<<;
    virtual FArchive& operator<<(UObject*& Object) override
    {
        FString Path=IsSaving()?(Object?Object->GetPathName():TEXT("None")):FString();
        FArchive& Base=*this;Base<<Path;
        if(Path!=TEXT("None")&&!Path.IsEmpty())
        {
            References.Add(Path);
            if(IsLoading())
            {
                Object=StaticFindObject(UObject::StaticClass(),nullptr,*Path);
                if(!Object)Object=StaticLoadObject(UObject::StaticClass(),nullptr,*Path);
                if(!Object){Missing.AddUnique(Path);SetError();}
            }
        }
        else if(IsLoading())Object=nullptr;
        return *this;
    }
    virtual FArchive& operator<<(FObjectPtr& Value) override
    {UObject* Object=Value.Get();*this<<Object;if(IsLoading())Value=Object;return *this;}
    virtual FArchive& operator<<(FWeakObjectPtr& Value) override
    {UObject* Object=Value.Get();*this<<Object;if(IsLoading())Value=Object;return *this;}
    virtual FArchive& operator<<(FSoftObjectPath& Value) override
    {FObjectAndNameAsStringProxyArchive::operator<<(Value);if(!Value.IsNull())References.Add(Value.ToString());return *this;}
};

J DocumentProperties(UObject* Object)
{
    J Properties=MakeShared<FJsonObject>();
    for(TFieldIterator<FProperty> It(Object->GetClass());It;++It)
    {
        FProperty* P=*It;
        if(P->HasAnyPropertyFlags(CPF_Transient|CPF_DuplicateTransient|CPF_NonPIEDuplicateTransient|CPF_Deprecated))continue;
        // Read-only/native structural data is restored from nativeData. The
        // explicit text overlay is opt-in and validated on import.
        FString Value;P->ExportText_InContainer(0,Value,Object,Object,Object,PPF_Delimited);
        J V=MakeShared<FJsonObject>();V->SetStringField(TEXT("type"),P->GetCPPType());
        V->SetStringField(TEXT("text"),Value);V->SetBoolField(TEXT("apply"),false);
        Properties->SetObjectField(P->GetName(),V);
    }
    return Properties;
}

J DocumentPins(UEdGraphNode* Node)
{
    J Graph=MakeShared<FJsonObject>();Graph->SetStringField(TEXT("nodeGuid"),Node->NodeGuid.ToString());
    TArray<TSharedPtr<FJsonValue>> Pins;
    for(UEdGraphPin* Pin:Node->Pins)
    {
        J P=MakeShared<FJsonObject>();P->SetStringField(TEXT("id"),Pin->PinId.ToString());P->SetStringField(TEXT("name"),Pin->PinName.ToString());
        P->SetNumberField(TEXT("direction"),int32(Pin->Direction));P->SetObjectField(TEXT("type"),ExportStruct(FEdGraphPinType::StaticStruct(),&Pin->PinType));
        P->SetStringField(TEXT("defaultValue"),Pin->DefaultValue);P->SetStringField(TEXT("defaultObject"),Pin->DefaultObject?Pin->DefaultObject->GetPathName():TEXT("None"));
        P->SetStringField(TEXT("defaultText"),Pin->DefaultTextValue.ToString());
        TArray<FString> Links;for(UEdGraphPin* Other:Pin->LinkedTo)if(Other)Links.Add(Other->GetOwningNode()->GetPathName()+TEXT("#")+Other->PinId.ToString());Links.Sort();
        TArray<TSharedPtr<FJsonValue>> Values;for(const FString& Link:Links)Values.Add(MakeShared<FJsonValueString>(Link));P->SetArrayField(TEXT("links"),Values);Pins.Add(MakeShared<FJsonValueObject>(P));
    }
    Graph->SetArrayField(TEXT("pins"),Pins);return Graph;
}

void RoundTripDocument(const J& Q,const J& Result,FNiagaraExternalEditContext& Errors)
{
    const FString Operation=String(Q,TEXT("operation")),File=String(Q,TEXT("file"));
    if(File.IsEmpty()){ReportError(Errors,TEXT("Document file required"));return;}
    if(Operation==TEXT("export-document"))
    {
        const FString Asset=String(Q,TEXT("asset"));
        if(!Asset.StartsWith(TEXT("/Game/"))||!FPackageName::IsValidLongPackageName(Asset)){ReportError(Errors,TEXT("Expected /Game asset"));return;}
        UObject* Root=LoadObject<UObject>(nullptr,*Asset);
        if(!Root||(!Root->IsA<UNiagaraSystem>()&&!Root->IsA<UNiagaraEmitter>())){ReportError(Errors,TEXT("Expected System or Emitter"));return;}
        if(auto* System=Cast<UNiagaraSystem>(Root))System->WaitForCompilationComplete(true,false);
        TArray<TSharedPtr<FJsonValue>> Records,Packages,Attachments;TSet<FString> References,PackageNames,AttachmentNames;
        TArray<UObject*> Roots;Roots.Add(Root);
        for(int32 RootIndex=0;RootIndex<Roots.Num();++RootIndex)
        {
          UObject* PackageRoot=Roots[RootIndex];const FString CurrentPackage=PackageRoot->GetOutermost()->GetName();
          if(PackageNames.Contains(CurrentPackage))continue;PackageNames.Add(CurrentPackage);
          J PackageInfo=MakeShared<FJsonObject>();PackageInfo->SetStringField(TEXT("package"),CurrentPackage);PackageInfo->SetStringField(TEXT("asset"),PackageRoot->GetPathName());
          PackageInfo->SetStringField(TEXT("persistentGuid"),PackageRoot->GetOutermost()->GetPersistentGuid().ToString());
          J RootMetadata=MakeShared<FJsonObject>(),ObjectMetadata=MakeShared<FJsonObject>();const FMetaData& Metadata=PackageRoot->GetOutermost()->GetMetaData();
          for(const auto& P:Metadata.RootMetaDataMap)RootMetadata->SetStringField(P.Key.ToString(),P.Value);
          for(const auto& O:Metadata.ObjectMetaDataMap){J Fields=MakeShared<FJsonObject>();for(const auto& P:O.Value)Fields->SetStringField(P.Key.ToString(),P.Value);ObjectMetadata->SetObjectField(O.Key.ToString(),Fields);}
          PackageInfo->SetObjectField(TEXT("rootMetadata"),RootMetadata);PackageInfo->SetObjectField(TEXT("objectMetadata"),ObjectMetadata);Packages.Add(MakeShared<FJsonValueObject>(PackageInfo));
          TArray<UObject*> Objects;GetObjectsWithOuter(PackageRoot->GetOutermost(),Objects,true);
          Objects.Sort([](const UObject& A,const UObject& B){return A.GetPathName()<B.GetPathName();});
          TSet<FString> LocalReferences;
          TArray<FName> RegistryDependencies;
          FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().GetDependencies(FName(*CurrentPackage),RegistryDependencies);
          for(FName Dependency:RegistryDependencies)if(Dependency.ToString().StartsWith(TEXT("/Game/")))LocalReferences.Add(Dependency.ToString()+TEXT(".")+FPackageName::GetShortName(Dependency.ToString()));
          for(UObject* Object:Objects)
          {
            if(Object->HasAnyFlags(RF_ClassDefaultObject)||Object->IsA<UPackage>())continue;
            TArray<uint8> Bytes;FMemoryWriter Writer(Bytes,true);FNiagaraDocumentArchive Archive(Writer);
            Object->Serialize(Archive);
            if(Archive.IsError()){ReportError(Errors,TEXT("Native serialization failed: ")+Object->GetPathName());return;}
            J Record=MakeShared<FJsonObject>();Record->SetStringField(TEXT("id"),Object->GetPathName());
            Record->SetStringField(TEXT("class"),Object->GetClass()->GetPathName());Record->SetStringField(TEXT("outer"),Object->GetOuter()->GetPathName());
            Record->SetStringField(TEXT("name"),Object->GetName());
            Record->SetStringField(TEXT("archetype"),Object->GetArchetype()->GetPathName());
            Record->SetNumberField(TEXT("flags"),uint32(Object->GetFlags()&(RF_Public|RF_Standalone|RF_Transactional|RF_ArchetypeObject|RF_DefaultSubObject)));
            Record->SetObjectField(TEXT("properties"),DocumentProperties(Object));
            if(auto* Node=Cast<UEdGraphNode>(Object))Record->SetObjectField(TEXT("graph"),DocumentPins(Node));
            Record->SetStringField(TEXT("nativeData"),FBase64::Encode(Bytes));
            TArray<FString> ObjectRefs=Archive.References.Array();ObjectRefs.Sort();TArray<TSharedPtr<FJsonValue>> ReferenceValues;
            for(const FString& Ref:ObjectRefs)ReferenceValues.Add(MakeShared<FJsonValueString>(Ref));Record->SetArrayField(TEXT("references"),ReferenceValues);
            TArray<TSharedPtr<FJsonValue>> Versions;
            for(const auto& Version:Archive.GetCustomVersions().GetAllVersions())
            {J V=MakeShared<FJsonObject>();V->SetStringField(TEXT("id"),Version.Key.ToString());V->SetNumberField(TEXT("version"),Version.Version);Versions.Add(MakeShared<FJsonValueObject>(V));}
            Record->SetArrayField(TEXT("customVersions"),Versions);Records.Add(MakeShared<FJsonValueObject>(Record));References.Append(Archive.References);LocalReferences.Append(Archive.References);
          }
          for(const FString& Ref:LocalReferences)
          {
            const FString Dependency=FPackageName::ObjectPathToPackageName(Ref);
            if(!Dependency.StartsWith(TEXT("/Game/"))||PackageNames.Contains(Dependency))continue;
            UObject* Referenced=LoadObject<UObject>(nullptr,*Dependency);
            if(!Referenced){ReportError(Errors,TEXT("Missing project dependency: ")+Dependency);return;}
            if(Referenced->IsA<UNiagaraSystem>()||Referenced->IsA<UNiagaraEmitter>()||Referenced->IsA<UNiagaraScript>())Roots.AddUnique(Referenced);
            else if(!AttachmentNames.Contains(Dependency))
            {
                AttachmentNames.Add(Dependency);J A=MakeShared<FJsonObject>();A->SetStringField(TEXT("package"),Dependency);
                A->SetStringField(TEXT("source"),FPaths::ConvertRelativePathToFull(FPackageName::LongPackageNameToFilename(Dependency,FPackageName::GetAssetPackageExtension())));Attachments.Add(MakeShared<FJsonValueObject>(A));
            }
          }
        }
        // Package enumeration also sees orphaned graphs left by native parent
        // merges. SavePackage does not persist those. Keep the serialized object
        // closure, including outer/archetype ancestors, rather than live garbage.
        TMap<FString,J> AllRecords;for(const auto& V:Records)AllRecords.Add(String(V->AsObject(),TEXT("id")),V->AsObject());
        TSet<FString> Reachable;TArray<FString> Pending;
        for(const auto& V:Packages)Pending.Add(String(V->AsObject(),TEXT("asset")));
        while(!Pending.IsEmpty())
        {
            FString Id=Pending.Pop(EAllowShrinking::No);if(Reachable.Contains(Id))continue;J* Found=AllRecords.Find(Id);if(!Found)continue;
            Reachable.Add(Id);Pending.Add(String(*Found,TEXT("outer")));Pending.Add(String(*Found,TEXT("archetype")));
            for(const auto& Ref:(*Found)->GetArrayField(TEXT("references")))Pending.Add(Ref->AsString());
        }
        Records.RemoveAll([&](const TSharedPtr<FJsonValue>& V){return !Reachable.Contains(String(V->AsObject(),TEXT("id")));});
        // Native resource packages are attachments. Traverse their package
        // dependencies too (for example material -> texture), without pretending
        // that texture bulk data is an editable Niagara graph.
        for(int32 I=0;I<Attachments.Num();++I)
        {
            TArray<FName> Dependencies;FModuleManager::LoadModuleChecked<FAssetRegistryModule>(TEXT("AssetRegistry")).Get().GetDependencies(FName(*String(Attachments[I]->AsObject(),TEXT("package"))),Dependencies);
            for(FName Dependency:Dependencies)
            {
                const FString P=Dependency.ToString();if(!P.StartsWith(TEXT("/Game/"))||PackageNames.Contains(P)||AttachmentNames.Contains(P))continue;
                AttachmentNames.Add(P);J A=MakeShared<FJsonObject>();A->SetStringField(TEXT("package"),P);A->SetStringField(TEXT("source"),FPaths::ConvertRelativePathToFull(FPackageName::LongPackageNameToFilename(P,FPackageName::GetAssetPackageExtension())));Attachments.Add(MakeShared<FJsonValueObject>(A));
            }
        }
        J Document=MakeShared<FJsonObject>();Document->SetStringField(TEXT("schema"),TEXT("ue-niagara-document/1"));
        Document->SetStringField(TEXT("engine"),FEngineVersion::Current().ToString());Document->SetStringField(TEXT("asset"),Root->GetPathName());
        Document->SetStringField(TEXT("package"),Root->GetOutermost()->GetName());Document->SetArrayField(TEXT("objects"),Records);Document->SetArrayField(TEXT("packages"),Packages);
        TArray<FString> SortedReferences=References.Array();SortedReferences.Sort();TArray<TSharedPtr<FJsonValue>> External;
        for(const FString& Ref:SortedReferences)if(!PackageNames.Contains(FPackageName::ObjectPathToPackageName(Ref)))External.Add(MakeShared<FJsonValueString>(Ref));
        Document->SetArrayField(TEXT("externalReferences"),External);
        if(!FFileHelper::SaveStringToFile(Json(Document),*File,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM)){ReportError(Errors,TEXT("Document write failed"));return;}
        Result->SetArrayField(TEXT("attachments"),Attachments);Result->SetNumberField(TEXT("objectCount"),Records.Num());Result->SetStringField(TEXT("file"),File);return;
    }
    FString Text;J Document;
    if(!FFileHelper::LoadFileToString(Text,*File)||!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text),Document)||String(Document,TEXT("schema"))!=TEXT("ue-niagara-document/1"))
    {ReportError(Errors,TEXT("Invalid Niagara document"));return;}
    if(String(Document,TEXT("engine"))!=FEngineVersion::Current().ToString()){ReportError(Errors,TEXT("Matching engine build required"));return;}
    const FString PackageName=String(Document,TEXT("package"));TSet<FString> PackageNames;
    const TArray<TSharedPtr<FJsonValue>>* Packages=nullptr;
    if(!Document->TryGetArrayField(TEXT("packages"),Packages)){ReportError(Errors,TEXT("Missing package table"));return;}
    for(const auto& V:*Packages)
    {
        const FString P=String(V->AsObject(),TEXT("package"));
        if(!P.StartsWith(TEXT("/Game/"))||!FPackageName::IsValidLongPackageName(P)||FPackageName::DoesPackageExist(P)||PackageNames.Contains(P))
        {ReportError(Errors,TEXT("Import requires absent, unique /Game packages; overwrite refused: ")+P);return;}
        PackageNames.Add(P);
    }
    if(!PackageNames.Contains(PackageName)){ReportError(Errors,TEXT("Root package missing"));return;}
    const TArray<TSharedPtr<FJsonValue>>* Records=nullptr;
    if(!Document->TryGetArrayField(TEXT("objects"),Records)||Records->Num()==0||Records->Num()>100000){ReportError(Errors,TEXT("Invalid object table"));return;}
    TMap<FString,J> Definitions;TMap<FString,UClass*> Classes;
    for(const auto& V:*Records)
    {
        if(V->Type!=EJson::Object){ReportError(Errors,TEXT("Invalid object record"));return;}J R=V->AsObject();const FString Id=String(R,TEXT("id"));
        if(!PackageNames.Contains(FPackageName::ObjectPathToPackageName(Id))||Definitions.Contains(Id)){ReportError(Errors,TEXT("Invalid/duplicate object identity"));return;}
        UClass* Class=LoadClass<UObject>(nullptr,*String(R,TEXT("class")));
        if(!Class||Class->HasAnyClassFlags(CLASS_Abstract)||Class->IsChildOf(UClass::StaticClass())||Class->IsChildOf(UPackage::StaticClass()))
        {ReportError(Errors,TEXT("Unsupported document class: ")+String(R,TEXT("class")));return;}
        Definitions.Add(Id,R);Classes.Add(Id,Class);
    }
    UPackage* Package=CreatePackage(*PackageName);Package->AddToRoot();TMap<FString,UObject*> Created;
    for(const FString& P:PackageNames)Created.Add(P,CreatePackage(*P));
    for(const auto& V:*Packages)
    {
        J R=V->AsObject();auto* P=CastChecked<UPackage>(Created[String(R,TEXT("package"))]);FGuid Id;
        if(!FGuid::Parse(String(R,TEXT("persistentGuid")),Id)){ReportError(Errors,TEXT("Invalid package GUID"));Package->RemoveFromRoot();return;}P->SetPersistentGuid(Id);
        FMetaData& M=P->GetMetaData();
        for(const auto& Field:R->GetObjectField(TEXT("rootMetadata"))->Values)M.RootMetaDataMap.Add(FName(*Field.Key),Field.Value->AsString());
        for(const auto& Object:R->GetObjectField(TEXT("objectMetadata"))->Values){TMap<FName,FString> Fields;for(const auto& Field:Object.Value->AsObject()->Values)Fields.Add(FName(*Field.Key),Field.Value->AsString());M.ObjectMetaDataMap.Add(FSoftObjectPath(FString(*Object.Key)),MoveTemp(Fields));}
    }
    while(Created.Num()<Definitions.Num()+PackageNames.Num())
    {
        bool Progress=false;
        for(const auto& Pair:Definitions)
        {
            if(Created.Contains(Pair.Key))continue;const J R=Pair.Value;UObject* const* Outer=Created.Find(String(R,TEXT("outer")));if(!Outer)continue;
            const FString ArchetypePath=String(R,TEXT("archetype"));
            UObject* Archetype=Created.FindRef(ArchetypePath);
            if(!Archetype&&Definitions.Contains(ArchetypePath))continue;
            if(!Archetype)Archetype=StaticLoadObject(UObject::StaticClass(),nullptr,*ArchetypePath);
            if(!Archetype||!Archetype->IsA(Classes[Pair.Key])){ReportError(Errors,TEXT("Missing/incompatible archetype: ")+ArchetypePath);Package->RemoveFromRoot();return;}
            UObject* Object=StaticFindObject(Classes[Pair.Key],*Outer,*String(R,TEXT("name")));
            if(!Object)Object=NewObject<UObject>(*Outer,Classes[Pair.Key],FName(*String(R,TEXT("name"))),EObjectFlags(uint32(R->GetNumberField(TEXT("flags")))),Archetype);
            if(!Object||Object->GetPathName()!=Pair.Key){ReportError(Errors,TEXT("Object identity mismatch: ")+Pair.Key);Package->RemoveFromRoot();return;}
            Created.Add(Pair.Key,Object);Progress=true;
        }
        if(!Progress){ReportError(Errors,TEXT("Unresolved outer graph"));Package->RemoveFromRoot();return;}
    }
    for(const auto& V:*Records)
    {
        const J R=V->AsObject();UObject* Object=Created[String(R,TEXT("id"))];TArray<uint8> Bytes;
        if(!FBase64::Decode(String(R,TEXT("nativeData")),Bytes)){ReportError(Errors,TEXT("Invalid native object data"));break;}
        FMemoryReader Reader(Bytes,true);FNiagaraDocumentArchive Archive(Reader);
        for(const auto& Version:R->GetArrayField(TEXT("customVersions")))
        {FGuid Id;if(!FGuid::Parse(String(Version->AsObject(),TEXT("id")),Id)){Archive.SetError();break;}Archive.SetCustomVersion(Id,int32(Version->AsObject()->GetNumberField(TEXT("version"))),NAME_None);}
        if(!Archive.IsError())Object->Serialize(Archive);
        if(Archive.IsError()||Reader.Tell()!=Bytes.Num()){ReportError(Errors,TEXT("Native restore failed: ")+Object->GetPathName()+TEXT(" ")+FString::Join(Archive.Missing,TEXT(", ")));break;}
    }
    if(!Errors.HasErrors())for(const auto& V:*Records)
    {
        J R=V->AsObject();if(auto* Node=Cast<UEdGraphNode>(Created[String(R,TEXT("id"))]))
        {
            const TSharedPtr<FJsonObject>* Graph=nullptr;
            if(!R->TryGetObjectField(TEXT("graph"),Graph)||!FJsonValue::CompareEqual(FJsonValueObject(DocumentPins(Node)),FJsonValueObject(*Graph)))
            {ReportError(Errors,TEXT("Graph/pin restoration mismatch: ")+Node->GetPathName());break;}
        }
    }
    bool AppliedOverlays=false;TArray<UObject*> EditedObjects;
    if(!Errors.HasErrors())for(const auto& V:*Records)
    {
        const J R=V->AsObject();UObject* Object=Created[String(R,TEXT("id"))];
        for(const auto& Field:R->GetObjectField(TEXT("properties"))->Values)
        {
            J Value=Field.Value->AsObject();if(!Value->GetBoolField(TEXT("apply")))continue;
            FProperty* P=FindFProperty<FProperty>(Object->GetClass(),*Field.Key);
            if(!P||P->HasAnyPropertyFlags(CPF_Transient|CPF_Deprecated)||P->GetCPPType()!=String(Value,TEXT("type"))||
               !P->ImportText_InContainer(*String(Value,TEXT("text")),Object,Object,PPF_Delimited))
            {ReportError(Errors,TEXT("Property overlay failed: ")+Object->GetPathName()+TEXT(".")+FString(*Field.Key));break;}
            AppliedOverlays=true;EditedObjects.AddUnique(Object);
        }
        if(Errors.HasErrors())break;
    }
    if(!Errors.HasErrors())
    {
        for(UObject* Edited:EditedObjects)Edited->PostEditChange();
        if(AppliedOverlays)
        {
            TSet<UNiagaraScriptSourceBase*> Sources;
            for(const auto& Pair:Created)if(auto* Script=Cast<UNiagaraScript>(Pair.Value))if(auto* Source=Script->GetLatestSource())Sources.Add(Source);
            for(auto* Source:Sources)Source->MarkNotSynchronized(TEXT("Niagara JSON property overlay"));
        }
        UObject* Root=Created.FindRef(String(Document,TEXT("asset")));
        if(!Root||(!Root->IsA<UNiagaraSystem>()&&!Root->IsA<UNiagaraEmitter>()))ReportError(Errors,TEXT("Missing Niagara root"));
        else
        {
            // All references are restored before editor fixups and compilation.
            // These are constructed objects restored by a current-build archive,
            // not objects loaded by an old package linker. Calling PostLoad here
            // falsely runs legacy migrations (there is no linker version).
            UNiagaraSystem* System=Cast<UNiagaraSystem>(Root);if(!System)System=EmitterEditingSystem(CastChecked<UNiagaraEmitter>(Root));
            System->AddToRoot();System->RequestCompile(AppliedOverlays);System->WaitForCompilationComplete(true,false);
            Result->SetBoolField(TEXT("compileValid"),System->IsValid());
            if(!System->IsValid()&&System->GetEmitterHandles().Num()>0)ReportError(Errors,TEXT("Restored Niagara compilation failed"));
            else
            {
                for(const auto& V:*Packages)
                {
                    J P=V->AsObject();UObject* AssetObject=Created.FindRef(String(P,TEXT("asset")));const FString PName=String(P,TEXT("package"));
                    if(!AssetObject){ReportError(Errors,TEXT("Package asset missing"));break;}
                    const FString Destination=FPackageName::LongPackageNameToFilename(PName,FPackageName::GetAssetPackageExtension());
                    IFileManager::Get().MakeDirectory(*FPaths::GetPath(Destination),true);FSavePackageArgs Args;Args.TopLevelFlags=RF_Public|RF_Standalone;Args.SaveFlags=SAVE_NoError;
                    if(!UPackage::SavePackage(AssetObject->GetOutermost(),AssetObject,*Destination,Args)){ReportError(Errors,TEXT("Restored package save failed"));break;}
                    FAssetRegistryModule::AssetCreated(AssetObject);
                }
                if(!Errors.HasErrors()){Result->SetBoolField(TEXT("saved"),true);Result->SetNumberField(TEXT("objectCount"),Records->Num());}
            }
            System->RemoveFromRoot();
        }
    }
    Package->RemoveFromRoot();
}
}
