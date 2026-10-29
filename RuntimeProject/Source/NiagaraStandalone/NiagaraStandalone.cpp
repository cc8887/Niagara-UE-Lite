#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/Pawn.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "NiagaraComponent.h"
#include "NiagaraSystem.h"
#include "NiagaraSystemInstanceController.h"
#include "NiagaraSystemInstance.h"
#include "NiagaraEmitterInstance.h"
#include "NiagaraEmitterHandle.h"
#include "ImageUtils.h"
#include "UnrealClient.h"
#include "DynamicRHI.h"
#include "RHI.h"
#include "Misc/App.h"
#include "Misc/CoreDelegates.h"
#include "Misc/DelayedAutoRegister.h"
#include "Misc/EngineVersion.h"
#include "Misc/FileHelper.h"
#include "HAL/IConsoleManager.h"
#include "Serialization/JsonSerializer.h"

#if PLATFORM_LINUX && !WITH_EDITOR
static FDelayedAutoRegisterHelper GCpuVulkan(EDelayedRegisterRunPhase::PreRHIInit,[]()
{
    if(!FParse::Param(FCommandLine::Get(),TEXT("CpuVulkan")))return;
    for(const auto& Pair:TArray<TPair<const TCHAR*,int32>>{
        {TEXT("r.Nanite.Streaming.StreamingPoolSize"),64},
        {TEXT("r.RDG.TransientAllocator"),0},{TEXT("r.PSOPrecaching"),0}})
        if(auto* V=IConsoleManager::Get().FindConsoleVariable(Pair.Key))V->Set(Pair.Value,ECVF_SetByCommandline);
});
#endif

class FNiagaraStandaloneModule final:public FDefaultGameModuleImpl
{
    FString Output,Metadata,SystemPath;
    FDelegateHandle FrameHandle,CaptureHandle;
    UNiagaraComponent* Component=nullptr;
    int32 SimFrames=60,Warmup=16,Frames=0,Wait=0;
    bool Requested=false,Finished=false,Paused=false;
    TSharedRef<FJsonObject> State=MakeShared<FJsonObject>();
    void SaveState()
    {
        FString S;FJsonSerializer::Serialize(State,TJsonWriterFactory<>::Create(&S));
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(Metadata),true);
        FFileHelper::SaveStringToFile(S,*Metadata,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    }
    void Fail(const FString& Message)
    {State->SetBoolField(TEXT("ok"),false);State->SetStringField(TEXT("error"),Message);SaveState();Finished=true;FPlatformMisc::RequestExitWithStatus(false,3);}
    bool Prepare(UWorld* World)
    {
        auto* System=LoadObject<UNiagaraSystem>(nullptr,*SystemPath);
        if(!System||!System->IsValid()){Fail(TEXT("Niagara System missing or invalid"));return false;}
        State->SetBoolField(TEXT("systemValid"),System->IsValid());
        State->SetBoolField(TEXT("systemReady"),System->IsReadyToRun());
        auto* Owner=World->SpawnActor<AActor>();Component=NewObject<UNiagaraComponent>(Owner);
        Owner->SetRootComponent(Component);Owner->AddInstanceComponent(Component);
        Component->SetAutoActivate(false);Component->SetAsset(System);Component->SetForceSolo(true);
        Component->SetAutoDestroy(false);Component->SetAllowScalability(false);Component->RegisterComponent();
        Component->SetWorldLocation(FVector::ZeroVector);Component->Activate(true);
        const FVector Pos(500,-800,300),Target(0,0,180);
        auto* Camera=World->SpawnActor<ACameraActor>(Pos,(Target-Pos).Rotation());
        auto* Cam=Camera->GetCameraComponent();Cam->SetFieldOfView(45);Cam->SetConstraintAspectRatio(false);
        Cam->PostProcessSettings.bOverride_AutoExposureMethod=true;Cam->PostProcessSettings.AutoExposureMethod=AEM_Manual;
        Cam->PostProcessSettings.bOverride_AutoExposureApplyPhysicalCameraExposure=true;
        Cam->PostProcessSettings.AutoExposureApplyPhysicalCameraExposure=false;
        if(auto* P=World->GetFirstPlayerController()){P->SetViewTarget(Camera);if(P->GetPawn())P->GetPawn()->SetActorHiddenInGame(true);}
        State->SetStringField(TEXT("system"),System->GetPathName());
        State->SetStringField(TEXT("engine"),FEngineVersion::Current().ToString());
        State->SetStringField(TEXT("adapter"),GRHIAdapterName);
        State->SetStringField(TEXT("rhi"),GDynamicRHI?GDynamicRHI->GetName():TEXT("unknown"));
        State->SetBoolField(TEXT("withEditor"),WITH_EDITOR!=0);
        State->SetBoolField(TEXT("requiresCookedData"),FPlatformProperties::RequiresCookedData());
        State->SetBoolField(TEXT("niagaraEditorLoaded"),FModuleManager::Get().IsModuleLoaded(TEXT("NiagaraEditor")));
        State->SetBoolField(TEXT("unrealEdLoaded"),FModuleManager::Get().IsModuleLoaded(TEXT("UnrealEd")));
        return true;
    }
    void DescribeSimulation()
    {
        auto C=Component->GetSystemInstanceController();
        if(!C.IsValid()||!C->IsValid()){State->SetBoolField(TEXT("simulationValid"),false);return;}
        auto* S=C->GetSoloSystemInstance();S->WaitForConcurrentTickAndFinalize();
        State->SetBoolField(TEXT("simulationValid"),true);State->SetNumberField(TEXT("simulationAge"),S->GetAge());
        TArray<TSharedPtr<FJsonValue>> Emitters;int32 Total=0;
        for(const auto& E:S->GetEmitters())
        {
            auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("name"),E->GetEmitterHandle().GetName().ToString());
            const int32 Count=E->GetNumParticles();Total+=Count;J->SetNumberField(TEXT("particles"),Count);
            J->SetNumberField(TEXT("executionState"),int32(E->GetExecutionState()));Emitters.Add(MakeShared<FJsonValueObject>(J));
        }
        State->SetArrayField(TEXT("emitters"),Emitters);State->SetNumberField(TEXT("particleCount"),Total);
    }
    void Frame()
    {
        if(Finished||Requested)return;
        if(++Wait>SimFrames+Warmup+1800){Fail(TEXT("Preview timed out"));return;}
        if(!GEngine||!GEngine->GameViewport||!GEngine->GameViewport->Viewport)return;
        auto* World=GEngine->GameViewport->GetWorld();if(!World||!World->HasBegunPlay())return;
        if(!Component){Prepare(World);return;}
        if(++Frames==SimFrames){DescribeSimulation();Component->SetPaused(true);Paused=true;}
        if(Frames<SimFrames+Warmup)return;
        if(!Paused){Fail(TEXT("Simulation did not reach requested frame"));return;}
        Requested=true;FScreenshotRequest::RequestScreenshot(Output,false,false);
    }
    void Captured(int32 Width,int32 Height,const TArray<FColor>& Pixels)
    {
        if(Finished)return;
        int64 Nonzero=0;uint8 Max=0;
        for(const auto& P:Pixels){const auto V=FMath::Max3(P.R,P.G,P.B);Max=FMath::Max(Max,V);Nonzero+=V>0;}
        State->SetNumberField(TEXT("maxRGB"),Max);State->SetNumberField(TEXT("nonZeroPixels"),Nonzero);
        State->SetNumberField(TEXT("width"),Width);State->SetNumberField(TEXT("height"),Height);
        State->SetNumberField(TEXT("simFrames"),SimFrames);State->SetNumberField(TEXT("warmupFrames"),Warmup);
        State->SetBoolField(TEXT("sceneProxyExists"),Component&&Component->GetSceneProxy()!=nullptr);
        if(auto* AA=IConsoleManager::Get().FindConsoleVariable(TEXT("r.AntiAliasingMethod")))State->SetNumberField(TEXT("antiAliasingMethod"),AA->GetInt());
        if(!Nonzero){Fail(TEXT("black_frame"));return;}
        TArray64<uint8> PNG;FImageUtils::PNGCompressImageArray(Width,Height,Pixels,PNG);
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(Output),true);
        if(!FFileHelper::SaveArrayToFile(PNG,*Output)){Fail(TEXT("Image write failed"));return;}
        State->SetBoolField(TEXT("ok"),true);State->SetBoolField(TEXT("imageSaved"),true);SaveState();Finished=true;
        FPlatformMisc::RequestExitWithStatus(false,0);
    }
public:
    void StartupModule() override
    {
        if(!FParse::Value(FCommandLine::Get(),TEXT("NiagaraOutput="),Output))return;
        Output=FPaths::ConvertRelativePathToFull(Output);Metadata=Output+TEXT(".json");
        FParse::Value(FCommandLine::Get(),TEXT("NiagaraSystem="),SystemPath);
        FParse::Value(FCommandLine::Get(),TEXT("SimFrames="),SimFrames);
        FParse::Value(FCommandLine::Get(),TEXT("WarmupFrames="),Warmup);
        if(SimFrames<1||SimFrames>36000||Warmup<1||Warmup>4096){Fail(TEXT("Invalid frame count"));return;}
        FApp::SetFixedDeltaTime(1.0/60.0);FApp::SetUseFixedTimeStep(true);
        FrameHandle=FCoreDelegates::OnEndFrame.AddRaw(this,&FNiagaraStandaloneModule::Frame);
        CaptureHandle=UGameViewportClient::OnScreenshotCaptured().AddRaw(this,&FNiagaraStandaloneModule::Captured);
    }
    void ShutdownModule() override
    {FCoreDelegates::OnEndFrame.Remove(FrameHandle);UGameViewportClient::OnScreenshotCaptured().Remove(CaptureHandle);}
};
IMPLEMENT_PRIMARY_GAME_MODULE(FNiagaraStandaloneModule, NiagaraStandalone, "NiagaraStandalone");
