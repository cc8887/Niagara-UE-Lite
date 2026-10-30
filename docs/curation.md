# Curated program and resource profile

The base standalone package contains the authoring/Cook backend, native rendering
template and required resources. Precomputed derived data is a separate optional
platform-specific download. Creating or editing a native asset does not require
an installed UE editor; the headless backend remains bundled.

## Optional DDC

Extract the matching `Niagara-UE-Lite-DDC-UE5.8.1-<platform>-x86_64` archive at the
standalone kit root. Its `cache/` directory must sit beside `Project/`,
`backend/` and `runtime-template/`. Install it before initializing a new workspace.
The existing CLI copies this seed into that workspace's local DerivedDataCache.

Without the optional archive, use the same CLI commands normally. The backend
generates derived data and shaders itself. First-time Cook can take considerably
longer; existing workspaces retain the cache they have already generated.
The optional archive is specific to its platform and release. Verify the
published SHA256 before extracting it. It contains no engine executables.

## Program allowlist

Backend program module families are restricted to `UnrealEditor`,
`ShaderCompileWorker` and `UnrealPak`. This removes modules belonging to separate
Frontend, Insights, MultiUser, Lightmass and ObjectPtrTool programs from the
Windows distribution. Shared third-party libraries and UnrealEditor modules are
retained unless their dependency removal is independently qualified. Static PE
imports and delay imports are evidence, but do not replace dynamic-load tests.

## Resource references

`tools/asset_dependency_inventory.py` runs inside the native packaged backend.
It inventories Project and Niagara assets and follows hard and soft package
dependencies. Explicit native startup roots cover the editor's fixed-path VR
interaction containers/gizmos and thumbnail/preview cubemaps, which are not
discovered from the Niagara asset graph alone. Each root records its source-code
provenance; its package dependencies are traversed by the same registry walk.
The resulting portable inventory is the input to
`tools/curate_package.py`; a failed or empty inventory is rejected.

The initial policy retains all Niagara content, Project content, generic engine
materials/functions, Slate, internationalization data and other engine resources.
Only unreferenced native assets in optional VR editor, tutorial, FBX automation,
map-template and StarterContent directories are candidates for exclusion. A
referenced asset in those directories stays in the package. Non-asset resources
are not discarded based on AssetRegistry results alone.

This is a qualified standalone asset/catalog profile. Future graphs that depend
on a stock engine asset omitted by this profile require supplying that asset and
its dependency closure. Arbitrary plugin/UI workflows remain outside the current
standalone interface. The full native `.uasset` remains the editable authority.

## Reproduction and qualification

Use a verified matching kit and a new output directory:

```sh
python tools/curate_package.py --source <verified-kit> --out <new-stage> --dependencies <native-inventory.json>
```

This creates a fixed base-package file list, a separate optional DDC archive and
an audit of removed programs/resources. All source and previously published
files are preserved. Native inventories and test logs belong outside Git.

Qualify the base package without `cache/` using native create, edit, explicit
save, independent-process reload, Cook and GPU Sprite/CPU Ribbon/CPU Mesh renders.
The first Cook also tests actual uncached shader compilation. After sealing,
freshly extract and verify the base manifest, confirm no seed is present, then
install the optional cache and repeat the edit/Cook/render suite in a new
workspace. Keep software Vulkan rendering separate from heavy cold-compilation
jobs to avoid CPU resource contention. Inspect actual PNGs and record the RHI
device; llvmpipe GPUComputeSim is not a physical Linux GPU qualification.

The first resource-only graph omitted a native ViewportInteraction container;
an actual create command asserted while loading its fixed Engine path. That
failure is retained in validation evidence. The native-root closure and a
curation input guard address this case; references to future dynamically
constructed asset paths still require independent qualification.

Compare base archive bytes, logical payload, stored payload and optional cache
archive bytes separately. The smaller base download trades first-use latency
for size; adding the optional cache back changes the total download comparison.
