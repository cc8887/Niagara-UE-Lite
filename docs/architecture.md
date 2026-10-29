# Native Niagara standalone boundary

The first target is UE 5.8.1 (CL 56057345), on Windows D3D12/SM6 and Linux
Vulkan/SM6. The material standalone design is reused; no Rive rendering or
third-party particle interpreter is involved.

| Layer | Native modules / purpose | Consumer installation |
| --- | --- | --- |
| CLI | Bundled Python, JSON requests and process management | None beyond the kit |
| Authoring bridge | NiagaraStandaloneEditor, NiagaraEditor, Niagara, NiagaraCore, UnrealEd, AssetTools, AssetRegistry, Json/JsonUtilities | Bundled |
| Native compilation/Cook | Niagara compiler, VectorVM/ShaderFormatVectorVM, ShaderCompileWorker, target shader formats, UnrealPak | Bundled |
| Preview | NiagaraStandalone Shipping, Niagara, NiagaraCore, NiagaraShader, NiagaraVertexFactories, Engine, Renderer, RHI | Copied cooked preview directory |

NiagaraEditor depends on GraphEditor, Slate, PropertyEditor, Sequencer,
MaterialEditor and other editor modules. A headless launcher does not remove
those binary dependencies. Eliminating UnrealEd would require a maintained
engine fork that separates graph authoring, compilation and saving; that is
not the architecture of this first package.

The native APIs are CreateNiagaraSystem/AddEmitter/AddModule/AddRenderer,
SetStackInputData/SetRendererData, RequestCompile/WaitForCompilationComplete,
UPackage::SavePackage and the UE Cook commandlet. The external-edit API is
marked experimental by Epic, so compatibility is pinned to the engine build.

The authoring bridge exposes `add-sprite-renderer`, `add-ribbon-renderer` and
`add-mesh-renderer`, each accepting an emitter name. `renderer-properties`
configures the native renderer at the specified index, and `remove-renderer`
removes it. The Ribbon and Mesh recipes replace their template renderer through
these APIs; they do not reconstruct particles with a separate renderer.

`ue-niagara-snapshot/1` contains authored topology, typed parameter values,
renderer properties and static dependency evidence. `ue-niagara-recipe/1`
replays declared creation/edit operations using native module/template assets.
They do not replace compiled Niagara bytecode/shaders and do not promise
cross-engine rendering or serialization of every arbitrary Niagara graph.
The native `.uasset` remains the full-fidelity editable file.

CPU particle simulation and a CPU Vulkan renderer are separate choices.
The original demonstration uses a deterministic CPU-sim sprite emitter.
Additional `demo --effect gpu|ribbon|mesh` entrypoints create GPU-sim Sprite,
CPU-sim Ribbon and CPU-sim Mesh systems respectively. `GPUComputeSim` selects
Niagara's compute-shader simulation path; a software Vulkan device such as
llvmpipe executes that path on the CPU and is not evidence of a physical GPU.
GPU-sim Ribbon/Mesh combinations, fluids, custom plugins and scene-dependent
data interfaces remain separate qualification targets. Platform-specific
rendering results belong in [renderer-validation.md](renderer-validation.md),
not in a capability claim inferred from successful compilation.

The recipes use the shared native `Fountain` and `DynamicBeam` templates.
Installed content catalogs can differ even between UE 5.8.1 builds; the recipes
avoid the `StaticBeam` and `UpwardMeshBurst` templates absent from the Linux
build. Mesh geometry and the Unlit Mesh/Ribbon materials are native Niagara
assets present in both builds. Native `.uasset` dependencies are still resolved
and compiled by the producer-side Cook pipeline.

The preview camera uses the viewport's aspect ratio. At a square 512-pixel
viewport, the configured 45-degree horizontal field of view therefore remains
45 degrees in the actual projection. Previously, the camera's default 16:9
aspect combined with `MaintainYFOV` reduced the actual horizontal field of view
to 26.231 degrees and cropped the Ribbon demonstration. The native runtime
accepts an optional `NiagaraCameraAspect` override for diagnostic A/B runs;
this is not a public CLI option. Camera metadata records the actual projection
so a configured field of view is not mistaken for the rendered one.

The preview fixes simulation timestep at 1/60 second, advances to the requested
`SimFrames`, and pauses the component. It then polls the component's scene
proxy and its own PSO precaching state without blocking the game thread.
The engine continues ticking while the particle simulation stays frozen.
Temporal warmup counts only consecutive fully ready rendered frames; losing
readiness resets that count. The native viewport screenshot is requested only
after this warmup completes. A 60-second limit covers readiness and warmup;
expiry records `capture_readiness_timeout` and readiness metadata rather than
capturing an unready component. Global PSO counters are diagnostic only and do
not gate the capture. Windows retains PSO precaching; the existing CPU Vulkan
profile disables it separately.

The initial Windows Ribbon black frame had no scene proxy despite live native
CPU particles. This confirmed that simulation readiness alone was insufficient
for capture. PSO deferral is one possible reason for a missing proxy, but its
causality was not isolated: warm repeat runs passed with PSO precaching both
enabled and disabled. The readiness gate handles the observed missing-proxy
condition without asserting that PSO compilation caused that particular run.

Metadata reports simulation age, simulation target, renderer class, image
statistics, RHI/adapter, capture readiness and whether editor modules were
loaded. CPU particle counts come from the native CPU dataset. GPU counts are read from a
native GPU buffer after the screenshot has been saved, with explicit count
provenance and completion fields. This readback cannot repair or replace the
already captured image; the CPU-side GPU particle estimate is not reported as
an exact count. Asset compilation alone is not simulation or image acceptance.

References:

- [Epic Niagara external edit API](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/NiagaraEditor/UNiagaraExternalEditUtilities)
- [Epic Niagara component API](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/Niagara/UNiagaraComponent)
- [Epic Niagara system factory](https://dev.epicgames.com/documentation/unreal-engine/API/Plugins/NiagaraEditor/UNiagaraSystemFactoryNew)

Engine tools remain governed by Epic's terms. Generated full-backend bundles
are kept outside Git and should use the already established private delivery
workflow; the source repository does not contain Engine binaries.
