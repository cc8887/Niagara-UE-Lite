#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/LocalPlayer.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/Pawn.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "Camera/PlayerCameraManager.h"
#include "NiagaraComponent.h"
#include "NiagaraSystem.h"
#include "NiagaraSystemInstanceController.h"
#include "NiagaraSystemInstance.h"
#include "NiagaraEmitterInstance.h"
#include "NiagaraEmitterHandle.h"
#include "NiagaraRendererProperties.h"
#include "NiagaraDataSetAccessor.h"
#include "Materials/MaterialInterface.h"
#if !WITH_EDITOR
#include "NiagaraDataSetReadback.h"
#endif
#include "ImageUtils.h"
#include "UnrealClient.h"
#include "DynamicRHI.h"
#include "RHI.h"
#include "PipelineStateCache.h"
#include "PSOPrecacheComponent.h"
#include "SceneView.h"
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
    bool AwaitingGpuReadback=false;
    double GpuReadbackDeadline=0;
    int32 ReadyWaitFrames=0,RenderedWarmup=0;
    double ReadinessStartedAt=0,LastReadinessPoll=0,ReadyWaitSeconds=0,ScreenshotDeadline=0;
    bool ReadinessWasReady=false;
    TSharedPtr<FJsonObject> CaptureReadiness;
#if !WITH_EDITOR
    struct FPendingReadback
    {
        TSharedPtr<FNiagaraDataSetReadback,ESPMode::ThreadSafe> Data;
        TSharedPtr<FJsonObject> Emitter;
    };
    TArray<FPendingReadback> GpuReadbacks;
#endif
    TSharedRef<FJsonObject> State=MakeShared<FJsonObject>();
    void SaveState()
    {
        FString S;FJsonSerializer::Serialize(State,TJsonWriterFactory<>::Create(&S));
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(Metadata),true);
        FFileHelper::SaveStringToFile(S,*Metadata,FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
    }
    void Fail(const FString& Message)
    {State->SetBoolField(TEXT("ok"),false);State->SetStringField(TEXT("error"),Message);SaveState();Finished=true;FPlatformMisc::RequestExitWithStatus(false,3);}
    template<typename V> static TArray<TSharedPtr<FJsonValue>> XYZ(const V& Value)
    {
        return {MakeShared<FJsonValueNumber>(Value.X),MakeShared<FJsonValueNumber>(Value.Y),MakeShared<FJsonValueNumber>(Value.Z)};
    }
    TSharedRef<FJsonObject> CpuPositions(const FNiagaraEmitterInstance& E)
    {
        auto Result=MakeShared<FJsonObject>();
        Result->SetStringField(TEXT("coordinateSpace"),TEXT("simulation"));
        Result->SetBoolField(TEXT("localSpace"),E.IsLocalSpace());
        const auto& Data=E.GetParticleData();const auto* Buffer=Data.GetCurrentData();
        FName Attribute(TEXT("Position"));FNiagaraDataSetAccessor<FNiagaraPosition> Accessor(Data,Attribute);
        if(!Accessor.IsValid()){Attribute=TEXT("Particles.Position");Accessor.Init(Data,Attribute);}
        const auto Reader=Accessor.GetReader(Data);const bool Valid=Buffer&&Reader.IsValid();
        Result->SetStringField(TEXT("attribute"),Attribute.ToString());Result->SetBoolField(TEXT("attributeValid"),Valid);
        const int32 Num=Buffer?Buffer->GetNumInstances():0;Result->SetNumberField(TEXT("datasetCount"),Num);
        int32 Finite=0;FVector3f Min(TNumericLimits<float>::Max()),Max(-TNumericLimits<float>::Max());
        Result->SetField(TEXT("first"),MakeShared<FJsonValueNull>());Result->SetField(TEXT("last"),MakeShared<FJsonValueNull>());
        if(Valid)for(int32 I=0;I<Num;++I)
        {
            const auto P=Reader.Get(I);if(!FMath::IsFinite(P.X)||!FMath::IsFinite(P.Y)||!FMath::IsFinite(P.Z))continue;
            ++Finite;Min=Min.ComponentMin(P);Max=Max.ComponentMax(P);
            if(I==0)Result->SetArrayField(TEXT("first"),XYZ(P));
            if(I==Num-1)Result->SetArrayField(TEXT("last"),XYZ(P));
        }
        Result->SetNumberField(TEXT("finiteCount"),Finite);
        Result->SetNumberField(TEXT("nonFiniteCount"),Valid?Num-Finite:0);
        if(Finite){Result->SetArrayField(TEXT("min"),XYZ(Min));Result->SetArrayField(TEXT("max"),XYZ(Max));}
        return Result;
    }
    void DescribeCamera()
    {
        if(!GEngine||!GEngine->GameViewport||!GEngine->GameViewport->Viewport)return;
        auto* World=GEngine->GameViewport->GetWorld();auto* Player=World?World->GetFirstPlayerController():nullptr;
        if(!Player||!Player->PlayerCameraManager)return;
        const auto& View=Player->PlayerCameraManager->GetCameraCacheView();auto Info=MakeShared<FJsonObject>();
        Info->SetStringField(TEXT("source"),TEXT("PlayerCameraManager.GetCameraCacheView"));
        Info->SetArrayField(TEXT("location"),XYZ(View.Location));
        Info->SetArrayField(TEXT("rotationPitchYawRoll"),XYZ(FVector(View.Rotation.Pitch,View.Rotation.Yaw,View.Rotation.Roll)));
        Info->SetNumberField(TEXT("fov"),Player->PlayerCameraManager->GetFOVAngle());
        Info->SetNumberField(TEXT("cachedFov"),View.FOV);Info->SetNumberField(TEXT("aspectRatio"),View.AspectRatio);
        Info->SetBoolField(TEXT("constrainAspectRatio"),View.bConstrainAspectRatio!=0);
        const auto Size=GEngine->GameViewport->Viewport->GetSizeXY();
        Info->SetNumberField(TEXT("viewportWidth"),Size.X);Info->SetNumberField(TEXT("viewportHeight"),Size.Y);
        if(auto* LocalPlayer=Player->GetLocalPlayer())
        {
            const auto Constraint=View.AspectRatioAxisConstraint.Get(LocalPlayer->AspectRatioAxisConstraint.GetValue());
            Info->SetNumberField(TEXT("aspectRatioAxisConstraint"),int32(Constraint));
            FSceneViewProjectionData Projection;
            if(LocalPlayer->GetProjectionData(GEngine->GameViewport->Viewport,Projection))
            {
                const double X=Projection.ProjectionMatrix.M[0][0],Y=Projection.ProjectionMatrix.M[1][1];
                Info->SetNumberField(TEXT("projectionM00"),X);Info->SetNumberField(TEXT("projectionM11"),Y);
                if(Projection.IsPerspectiveProjection()&&FMath::Abs(X)>SMALL_NUMBER&&FMath::Abs(Y)>SMALL_NUMBER)
                {
                    Info->SetNumberField(TEXT("projectionHorizontalFov"),FMath::RadiansToDegrees(2.0*FMath::Atan(1.0/FMath::Abs(X))));
                    Info->SetNumberField(TEXT("projectionVerticalFov"),FMath::RadiansToDegrees(2.0*FMath::Atan(1.0/FMath::Abs(Y))));
                }
                const auto Rect=Projection.GetConstrainedViewRect();
                Info->SetNumberField(TEXT("viewWidth"),Rect.Width());Info->SetNumberField(TEXT("viewHeight"),Rect.Height());
            }
        }
        State->SetObjectField(TEXT("camera"),Info);
    }
    bool Prepare(UWorld* World)
    {
        const auto ViewportSize=GEngine->GameViewport->Viewport->GetSizeXY();
        if(ViewportSize.X<1||ViewportSize.Y<1)return false;
        float CameraAspect=float(ViewportSize.X)/float(ViewportSize.Y);
        const bool AspectOverride=FParse::Value(FCommandLine::Get(),TEXT("NiagaraCameraAspect="),CameraAspect);
        if(!FMath::IsFinite(CameraAspect)||CameraAspect<1.0f/64.0f||CameraAspect>64.0f)
        {Fail(TEXT("NiagaraCameraAspect must be finite and between 1/64 and 64"));return false;}
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
        // UE defaults the camera to 16:9 and maintains vertical FOV. Matching
        // the actual viewport avoids silently narrowing a square preview's FOV.
        Cam->SetAspectRatio(CameraAspect);
        State->SetNumberField(TEXT("configuredCameraAspect"),CameraAspect);
        State->SetStringField(TEXT("cameraAspectSource"),AspectOverride?TEXT("command_line_override"):TEXT("viewport_dimensions"));
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
        TArray<TSharedPtr<FJsonValue>> Emitters;int32 EstimatedTotal=0,CpuTotal=0,GpuEmitters=0;
        for(const auto& E:S->GetEmitters())
        {
            auto J=MakeShared<FJsonObject>();J->SetStringField(TEXT("name"),E->GetEmitterHandle().GetName().ToString());
            const bool Gpu=E->GetSimTarget()==ENiagaraSimTarget::GPUComputeSim;
            const int32 Count=E->GetNumParticles();EstimatedTotal+=Count;
            J->SetStringField(TEXT("simTarget"),Gpu?TEXT("GPUComputeSim"):TEXT("CPUSim"));
            J->SetNumberField(TEXT("simTargetRaw"),int32(E->GetSimTarget()));
            J->SetBoolField(TEXT("gpuContextExists"),E->GetGPUContext()!=nullptr);
            J->SetNumberField(TEXT("estimatedParticles"),Count);
            J->SetBoolField(TEXT("particleCountExact"),!Gpu);
            J->SetStringField(TEXT("particleCountSource"),Gpu?TEXT("unmeasured_gpu_estimate"):TEXT("cpu_dataset"));
            if(Gpu){++GpuEmitters;J->SetField(TEXT("particles"),MakeShared<FJsonValueNull>());}
            else {CpuTotal+=Count;J->SetNumberField(TEXT("particles"),Count);J->SetObjectField(TEXT("cpuPositions"),CpuPositions(E.Get()));}
            TArray<TSharedPtr<FJsonValue>> Renderers;int32 Index=0;
            while(const auto* Renderer=E->GetRenderer(Index))
            {
                auto R=MakeShared<FJsonObject>();R->SetNumberField(TEXT("index"),Index++);
                R->SetStringField(TEXT("class"),Renderer->GetClass()->GetName());
                R->SetBoolField(TEXT("enabled"),Renderer->GetIsEnabled());
                TArray<UMaterialInterface*> Materials;Renderer->GetUsedMaterials(&E.Get(),Materials);
                TArray<TSharedPtr<FJsonValue>> Paths;
                for(const auto* Material:Materials)if(Material)Paths.Add(MakeShared<FJsonValueString>(Material->GetPathName()));
                R->SetArrayField(TEXT("materials"),Paths);Renderers.Add(MakeShared<FJsonValueObject>(R));
            }
            J->SetArrayField(TEXT("renderers"),Renderers);
            J->SetNumberField(TEXT("executionState"),int32(E->GetExecutionState()));Emitters.Add(MakeShared<FJsonValueObject>(J));
        }
        State->SetArrayField(TEXT("emitters"),Emitters);
        State->SetBoolField(TEXT("containsGpuEmitters"),GpuEmitters>0);
        State->SetNumberField(TEXT("gpuEmitterCount"),GpuEmitters);
        State->SetNumberField(TEXT("estimatedParticleCount"),EstimatedTotal);
        State->SetNumberField(TEXT("cpuParticleCount"),CpuTotal);
        State->SetBoolField(TEXT("particleCountExact"),GpuEmitters==0);
        if(GpuEmitters)State->SetField(TEXT("particleCount"),MakeShared<FJsonValueNull>());
        else State->SetNumberField(TEXT("particleCount"),CpuTotal);
    }
    void Complete()
    {
        State->SetBoolField(TEXT("ok"),true);SaveState();Finished=true;
        FPlatformMisc::RequestExitWithStatus(false,0);
    }
    TSharedRef<FJsonObject> ReadinessSnapshot() const
    {
        auto Info=MakeShared<FJsonObject>();
        const bool Active=Component&&Component->IsActive();
        const bool Registered=Component&&Component->IsRegistered();
        const bool RenderState=Component&&Component->IsRenderStateCreated();
        const bool Proxy=Component&&Component->GetSceneProxy()!=nullptr;
        const bool Pending=Component&&Component->IsPSOPrecaching();
        const auto Execution=Component?Component->GetExecutionState():ENiagaraExecutionState::Complete;
        Info->SetBoolField(TEXT("componentActive"),Active);
        Info->SetBoolField(TEXT("componentRegistered"),Registered);
        Info->SetBoolField(TEXT("renderStateCreated"),RenderState);
        Info->SetBoolField(TEXT("sceneProxyExists"),Proxy);
        Info->SetNumberField(TEXT("systemExecutionState"),int32(Execution));
        Info->SetBoolField(TEXT("psoPending"),Pending);
        if(auto* V=IConsoleManager::Get().FindConsoleVariable(TEXT("r.PSOPrecaching")))
            Info->SetNumberField(TEXT("psoPrecachingCVar"),V->GetInt());
        Info->SetBoolField(TEXT("psoPrecachingEnabled"),PipelineStateCache::IsPSOPrecachingEnabled());
        Info->SetNumberField(TEXT("psoProxyCreationStrategy"),int32(GetPSOPrecacheProxyCreationStrategy()));
        // Global counters are diagnostic only: unrelated PSOs must not delay this capture.
        Info->SetNumberField(TEXT("globalActivePrecacheRequests"),PipelineStateCache::NumActivePrecacheRequests());
        Info->SetNumberField(TEXT("globalActivePipelinePrecompileTasks"),PipelineStateCache::GetNumActivePipelinePrecompileTasks());
        Info->SetBoolField(TEXT("renderReady"),Active&&Registered&&RenderState&&Proxy&&!Pending&&Execution<ENiagaraExecutionState::Complete);
        return Info;
    }
    bool PollCaptureReadiness()
    {
        const double Now=FPlatformTime::Seconds();const auto Snapshot=ReadinessSnapshot();
        const bool Ready=Snapshot->GetBoolField(TEXT("renderReady"));
        if(!CaptureReadiness.IsValid())
        {
            CaptureReadiness=MakeShared<FJsonObject>();State->SetObjectField(TEXT("captureReadiness"),CaptureReadiness);
            CaptureReadiness->SetStringField(TEXT("policy"),TEXT("component_scene_proxy_and_pso"));
            CaptureReadiness->SetNumberField(TEXT("timeoutSeconds"),60);
            CaptureReadiness->SetObjectField(TEXT("initial"),Snapshot);
            CaptureReadiness->SetBoolField(TEXT("psoPendingObserved"),false);
            CaptureReadiness->SetNumberField(TEXT("globalActivePrecacheRequestsPeak"),0);
        }
        else
        {
            if(!ReadinessWasReady)ReadyWaitSeconds+=Now-LastReadinessPoll;
            if(!Ready)++ReadyWaitFrames;
        }
        LastReadinessPoll=Now;ReadinessWasReady=Ready;
        CaptureReadiness->SetObjectField(TEXT("latest"),Snapshot);
        CaptureReadiness->SetBoolField(TEXT("psoPendingObserved"),CaptureReadiness->GetBoolField(TEXT("psoPendingObserved"))||Snapshot->GetBoolField(TEXT("psoPending")));
        CaptureReadiness->SetNumberField(TEXT("globalActivePrecacheRequestsPeak"),FMath::Max(CaptureReadiness->GetNumberField(TEXT("globalActivePrecacheRequestsPeak")),Snapshot->GetNumberField(TEXT("globalActivePrecacheRequests"))));
        CaptureReadiness->SetNumberField(TEXT("waitWallSeconds"),ReadyWaitSeconds);
        CaptureReadiness->SetNumberField(TEXT("waitFrames"),ReadyWaitFrames);
        CaptureReadiness->SetNumberField(TEXT("elapsedSeconds"),Now-ReadinessStartedAt);
        CaptureReadiness->SetStringField(TEXT("phase"),Ready?TEXT("warming_up"):TEXT("waiting_render_ready"));
        return Ready;
    }
    void PollGpuReadbacks()
    {
#if !WITH_EDITOR
        for(const auto& Pending:GpuReadbacks)if(!Pending.Data->IsReady())
        {
            if(FPlatformTime::Seconds()>GpuReadbackDeadline)Fail(TEXT("GPU particle readback timed out after screenshot capture"));
            return;
        }
        int32 GpuTotal=0;
        for(const auto& Pending:GpuReadbacks)
        {
            const auto* Buffer=Pending.Data->GetDataSet().GetCurrentData();
            const int32 Count=Buffer?Buffer->GetNumInstances():0;GpuTotal+=Count;
            Pending.Emitter->SetNumberField(TEXT("particles"),Count);
            Pending.Emitter->SetBoolField(TEXT("particleCountExact"),true);
            Pending.Emitter->SetStringField(TEXT("particleCountSource"),TEXT("gpu_buffer_readback_after_screenshot"));
        }
        State->SetNumberField(TEXT("gpuParticleCount"),GpuTotal);
        State->SetNumberField(TEXT("particleCount"),GpuTotal+State->GetNumberField(TEXT("cpuParticleCount")));
        State->SetBoolField(TEXT("particleCountExact"),true);
        State->SetBoolField(TEXT("gpuReadbackCompleted"),true);
        GpuReadbacks.Empty();AwaitingGpuReadback=false;Complete();
#endif
    }
    void BeginGpuReadbacks()
    {
        if(!State->GetBoolField(TEXT("containsGpuEmitters"))){Complete();return;}
#if !WITH_EDITOR
        auto C=Component->GetSystemInstanceController();auto* S=C->GetSoloSystemInstance();
        if(!S->GetComputeDispatchInterface()){Fail(TEXT("GPU simulation has no native compute dispatch interface"));return;}
        const auto& Emitters=State->GetArrayField(TEXT("emitters"));int32 Index=0;
        for(const auto& E:S->GetEmitters())
        {
            const auto J=Emitters[Index++]->AsObject();
            if(E->GetSimTarget()!=ENiagaraSimTarget::GPUComputeSim)continue;
            if(!E->GetGPUContext()){Fail(TEXT("GPU emitter has no native compute execution context"));return;}
            FPendingReadback Pending;Pending.Emitter=J;
            Pending.Data=MakeShared<FNiagaraDataSetReadback,ESPMode::ThreadSafe>();
            Pending.Data->EnqueueReadback(&E.Get());GpuReadbacks.Add(MoveTemp(Pending));
        }
        // The image has already been captured and saved. Diagnostic buffer copies
        // cannot change its pixels. Poll later frames; never block GT on GPU idle.
        State->SetBoolField(TEXT("gpuReadbackAfterScreenshot"),true);
        State->SetBoolField(TEXT("gpuReadbackCompleted"),false);
        GpuReadbackDeadline=FPlatformTime::Seconds()+30.0;AwaitingGpuReadback=true;
#else
        // FNiagaraDataSetReadback is not exported from the modular editor DLL.
        State->SetStringField(TEXT("gpuReadbackUnavailableReason"),TEXT("requires packaged monolithic runtime"));
        Complete();
#endif
    }
    void Frame()
    {
        if(Finished)return;
        if(AwaitingGpuReadback){PollGpuReadbacks();return;}
        if(Requested)
        {
            if(FPlatformTime::Seconds()>ScreenshotDeadline)
            {CaptureReadiness->SetStringField(TEXT("phase"),TEXT("screenshot_timeout"));Fail(TEXT("Screenshot capture timed out"));}
            return;
        }
        if(!Paused&&++Wait>SimFrames+1800){Fail(TEXT("Preview initialization or simulation timed out"));return;}
        if(!GEngine||!GEngine->GameViewport||!GEngine->GameViewport->Viewport)return;
        auto* World=GEngine->GameViewport->GetWorld();if(!World||!World->HasBegunPlay())return;
        if(!Component){Prepare(World);return;}
        if(!Paused)
        {
            if(++Frames<SimFrames)return;
            DescribeSimulation();Component->SetPaused(true);Paused=true;
            ReadinessStartedAt=FPlatformTime::Seconds();PollCaptureReadiness();
            CaptureReadiness->SetNumberField(TEXT("warmupFramesRendered"),0);
            return; // The first warmup frame must actually render after the pause.
        }
        // Keep ticking the native engine while its component finishes asynchronous
        // PSO/proxy work. Never block the game thread or advance the frozen simulation.
        const bool WasReady=ReadinessWasReady;
        const bool Ready=PollCaptureReadiness();
        if(!Ready||!WasReady)RenderedWarmup=0;
        else ++RenderedWarmup;
        CaptureReadiness->SetNumberField(TEXT("warmupFramesRendered"),RenderedWarmup);
        if(FPlatformTime::Seconds()-ReadinessStartedAt>60.0)
        {CaptureReadiness->SetStringField(TEXT("phase"),TEXT("readiness_timeout"));Fail(TEXT("capture_readiness_timeout"));return;}
        if(!Ready||RenderedWarmup<Warmup)return;
        CaptureReadiness->SetStringField(TEXT("phase"),TEXT("screenshot_requested"));
        ScreenshotDeadline=FPlatformTime::Seconds()+30.0;
        Requested=true;FScreenshotRequest::RequestScreenshot(Output,false,false);
    }
    void Captured(int32 Width,int32 Height,const TArray<FColor>& Pixels)
    {
        if(Finished)return;
        if(CaptureReadiness.IsValid())
        {
            CaptureReadiness->SetStringField(TEXT("phase"),TEXT("screenshot_captured"));
            CaptureReadiness->SetObjectField(TEXT("latest"),ReadinessSnapshot());
        }
        int64 Nonzero=0;uint8 Max=0;
        for(const auto& P:Pixels){const auto V=FMath::Max3(P.R,P.G,P.B);Max=FMath::Max(Max,V);Nonzero+=V>0;}
        State->SetNumberField(TEXT("maxRGB"),Max);State->SetNumberField(TEXT("nonZeroPixels"),Nonzero);
        State->SetNumberField(TEXT("width"),Width);State->SetNumberField(TEXT("height"),Height);
        DescribeCamera();
        State->SetNumberField(TEXT("simFrames"),SimFrames);State->SetNumberField(TEXT("warmupFrames"),Warmup);
        State->SetBoolField(TEXT("sceneProxyExists"),Component&&Component->GetSceneProxy()!=nullptr);
        if(auto* AA=IConsoleManager::Get().FindConsoleVariable(TEXT("r.AntiAliasingMethod")))State->SetNumberField(TEXT("antiAliasingMethod"),AA->GetInt());
        if(!Nonzero){Fail(TEXT("black_frame"));return;}
        TArray64<uint8> PNG;FImageUtils::PNGCompressImageArray(Width,Height,Pixels,PNG);
        IFileManager::Get().MakeDirectory(*FPaths::GetPath(Output),true);
        if(!FFileHelper::SaveArrayToFile(PNG,*Output)){Fail(TEXT("Image write failed"));return;}
        State->SetBoolField(TEXT("imageSaved"),true);
        DescribeSimulation();BeginGpuReadbacks();
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
        State->SetNumberField(TEXT("simFrames"),SimFrames);State->SetNumberField(TEXT("warmupFrames"),Warmup);
        FApp::SetFixedDeltaTime(1.0/60.0);FApp::SetUseFixedTimeStep(true);
        FrameHandle=FCoreDelegates::OnEndFrame.AddRaw(this,&FNiagaraStandaloneModule::Frame);
        CaptureHandle=UGameViewportClient::OnScreenshotCaptured().AddRaw(this,&FNiagaraStandaloneModule::Captured);
    }
    void ShutdownModule() override
    {FCoreDelegates::OnEndFrame.Remove(FrameHandle);UGameViewportClient::OnScreenshotCaptured().Remove(CaptureHandle);}
};
IMPLEMENT_PRIMARY_GAME_MODULE(FNiagaraStandaloneModule, NiagaraStandalone, "NiagaraStandalone");
