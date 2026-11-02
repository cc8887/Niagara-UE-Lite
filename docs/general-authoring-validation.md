# General authoring candidate validation

This is local development-candidate evidence, not a claim that preview.5 already
contains these changes or that every Niagara plugin/module is qualified.

| Check | Windows | Linux |
| --- | --- | --- |
| UE version | 5.8.1, CL 56057345 | 5.8.1, CL 56057345 |
| New-workspace composition suite | 27 public CLI calls passed | 27 public CLI calls passed |
| Renderer | Native D3D12 / SM6 | Native Vulkan / SM6 |
| Adapter | NVIDIA GeForce RTX 5080 | llvmpipe, LLVM 19.1.7; Mesa 26.1.6 |
| Native screenshot | 512 x 512 PNG, process exit 0 | 512 x 512 PNG, process exit 0 |
| Particle count | 149 | 149 |
| Maximum RGB | 255 | 255 |
| Runtime editor modules | UnrealEd and NiagaraEditor absent | UnrealEd and NiagaraEditor absent |
| Final-workspace native errors / ensures / missing-class warnings | 0 | 0 |

Both images were visually inspected: scattered Confetti particles surround the
bright stationary sprite cluster from the Minimal emitter. This is a native
composition demonstration, not an artistic effect or qualification of Linux
physical GPUs. GPU Sprite, Ribbon and Mesh's prior fixture validation remains
separate from this new composition fixture.

The suite uses existing **ConfettiBurst** and **Minimal** emitter assets and native
SpawnRate, GravityForce and SolveForcesAndVelocity modules. It validates:

- Catalog discovery for emitters, modules, dynamic inputs, renderers and DIs.
- Creation, native module addition, User parameter binding and compilation.
- Module move and restoration, preserving node GUID and all reported inputs.
- Emitter duplication, rename and removal in one recipe.
- A FixedSeedRandomFloat dynamic input and nested Seed / Range configuration.
- FloatFromCurve's DI property changes, saved and read back in another process.
- Qualified enum-name input write and reload, respecting native visibility.
- An invalid destination index failing while leaving the `.uasset` hash unchanged.
- Importing a compatible `.uasset` through a Content root, preserving `/Game`
  package identity, and loading it in a separate workspace.
- Native Cook/Pak generation and actual pure-runtime rendering.

An additional three-call fixture on each platform creates a separate System,
adds **WorldAlignedTextureSample** to the GPU Confetti stack, configures its Texture
DI with an existing Texture2D asset, then reloads the input and checks the exact
asset reference. User Texture2D defaults also saved successfully on both platforms.
These extra checks establish native asset-reference persistence; they do not
measure that texture's visual contribution or qualify every DI class.

The Windows harness initially nested its auxiliary import workspace too deeply,
exceeding UE's 119-character filesystem DDC-root limit. The import step and later
steps were rerun with a short sibling workspace; original failed evidence was
retained. The public CLI now reports this Windows path constraint before starting
the backend. The final successful report explicitly records the harness correction.

The Linux reference distribution omitted 34 Niagara packages that exist in the
matching Windows distribution. All 1,123 common packages had identical SHA256;
the missing packages added **5,192,724 bytes**. Matching uncooked content was
restored before qualification. `tools/merge_niagara_resources.py` reproduces this
audit and optional copy, refuses differing existing assets, and does not modify
the reference engine. Do not rewrite plugin package mounts when supplementing.

Candidate archives exclude DDC, generated scratch data and external debug/static
symbols. Newly rebuilt ELF libraries were stripped, and private source/build paths
were redacted before generating new manifests. The archive sealing pass checked
file contents for those private paths. Optional DDC was present during the main
composition suite; this is not a new cold-cache performance measurement.

| Candidate | Compressed bytes | SHA256 |
| --- | ---: | --- |
| Windows general-authoring ZIP | 1,115,508,955 | `3a418463df02575a8400c44a13e683652c9a7c802285aa1c038364d9b50a6232` |
| Linux general-authoring TAR.GZ | 983,336,935 | `4ac7e809a4786277c873c54a6b0755ab4f0b20f63e9377370a1eec2845628ae2` |

The source, profile and end-user interfaces still include a headless editor/Cook
backend. New custom-module graph/HLSL authoring, Event Handler / Simulation Stage
stack editing and arbitrary third-party C++ plugin installation are outside this
candidate's tested boundary. See [general-authoring.md](general-authoring.md).
