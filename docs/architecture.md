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

The native APIs are CreateNiagaraSystem/AddEmitter/AddModule,
SetStackInputData/SetRendererData, RequestCompile/WaitForCompilationComplete,
UPackage::SavePackage and the UE Cook commandlet. The external-edit API is
marked experimental by Epic, so compatibility is pinned to the engine build.

`ue-niagara-snapshot/1` contains authored topology, typed parameter values,
renderer properties and static dependency evidence. `ue-niagara-recipe/1`
replays declared creation/edit operations using native module/template assets.
They do not replace compiled Niagara bytecode/shaders and do not promise
cross-engine rendering or serialization of every arbitrary Niagara graph.
The native `.uasset` remains the full-fidelity editable file.

CPU particle simulation and a CPU Vulkan renderer are separate choices.
The initial demonstration uses a deterministic CPU-sim sprite emitter, which
renders on D3D12 or Vulkan. GPU-sim emitters, fluids, mesh/ribbon renderers,
custom plugins and scene-dependent data interfaces require additional tests.

The preview fixes simulation timestep at 1/60 second, advances to the requested
frame, pauses the component, then warms temporal AA and captures the native
viewport. Metadata reports simulation age/particle counts, image statistics,
RHI and whether editor modules were loaded. Asset compilation alone is not
simulation or image acceptance.

References:

- [Epic Niagara external edit API](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/NiagaraEditor/UNiagaraExternalEditUtilities)
- [Epic Niagara component API](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Plugins/Niagara/UNiagaraComponent)
- [Epic Niagara system factory](https://dev.epicgames.com/documentation/unreal-engine/API/Plugins/NiagaraEditor/UNiagaraSystemFactoryNew)

Engine tools remain governed by Epic's terms. Generated full-backend bundles
are kept outside Git and should use the already established private delivery
workflow; the source repository does not contain Engine binaries.
