# Commandlet editor service profile

The standalone backend still contains UnrealEd and NiagaraEditor. This profile
removes MainFrame, Persona and independently unneeded editor/target-platform
libraries while preserving native Niagara graph edits, package serialization,
texture import, material creation, Cook and Shipping rendering.

Every frontend backend invocation includes `-NiagaraLiteBackend`. It selects
non-visual services in the matching source-patched UE 5.8.1 modules. Running the
bundled backend as a general interactive Unreal Editor is unsupported.

## Source changes

`patch_ue58_editor_backend.py` implements four narrowly scoped changes:

* UnrealEd: replace the default editor-module sweep with explicit services when
  that function is invoked in this commandlet profile. Other initialization
  paths still exist; this is not a complete editor module allowlist.
* LevelEditor: keep non-visual extensibility, command-list and Outliner services;
  skip level window, viewport, toolbar and tab initialization. Niagara's
  post-engine registration needs the Outliner settings even with no windows.
* MeshUtilities: compile out the Persona-only toolbar entry. Mesh building,
  reduction and other required services remain available.
* Blutility: skip editor utility startup/UI initialization and matching teardown
  for this profile. A native debugger trace identified EditorUtilitySubsystem
  initialization as an additional unconditional MainFrame loader.

The initial attempt to skip all LevelEditor startup asserted in Niagara's
post-engine Outliner registration. This was repaired by preserving its data
services. A MainFrame-free startup must also exclude the Blutility initialization
path; suppressing only LevelEditor's MainFrame call is insufficient.

The frontend no longer needs EditorScriptingUtilities. Texture operations use
AssetRegistry, native import factories and EditorLoadingAndSavingUtils. Preview
world creation is a native `UWorld::CreateWorld` / `UPackage::SavePackage`
operation behind Cook. It does not require LevelEditorSubsystem or a Python map
authoring script. Existing preview maps are loaded and validated rather than
silently replaced; existing destination textures remain protected.

## Rebuild

Use matching source, generated headers, original objects/import libraries and
toolchains. Preserve engine version, public APIs, serialized type ownership and
ABI settings. Outputs of these developer helpers are unqualified build products,
not ready-to-publish binaries. Compilation logs can contain local paths.

Windows can start from a matching installed engine using
`build_editor_backend_windows.py --engine <Engine> --project <standalone.uproject>
--work <new-short-root>`. It creates independent copies, keeps unmodified modules
precompiled, rebuilds the selected modules from source, and builds the updated
native commandlet. The installed engine and source project remain inputs.
Expect substantial temporary build space and compilation time.

Linux can use `build_editor_backend_linux.py --engine <Engine> --work <new-root>`.
It recompiles affected original UBT unity units, reuses unchanged matching
objects, and links new libraries outside Engine. The original first-pass
`.link.rsp` does not contain all final dependencies: preserve the reference
library's final imports as UBT's FixDependencies stage does. Do not distribute
an intermediate library with missing DT_NEEDED entries. The updated project
commandlet must also be compiled using `tools/build.py` or an equivalent
isolated build with the original matching responses and generated code.

In the qualified Linux profile, MaterialBaking also needs a native relink to
remove its unused declared MainFrame import. Use `relink_editor_module_linux.py
--module MaterialBaking --omit MainFrame` with matching Engine/work arguments.
The linker must resolve every symbol without MainFrame (`--no-undefined`).
This does not remove the need to test actual dynamic loads.

## Package dependency pass

Use `prune_editor_modules.py --source <verified-profile-kit> --out <new-kit>
--report <audit.json>`. The source must have a freshly sealed manifest after
native overrides and frontend changes. Original libraries and previous releases
are preserved. PE imports/delay imports or ELF DT_NEEDED edges block unsafe
removals; module manifests are updated alongside the retained libraries.

The profile also excludes other platforms' target modules and shader formats.
Windows keeps Windows D3D12/SM6 and VectorVM; Linux keeps Linux Vulkan/SM6 and
VectorVM. Shared compiler/texture libraries remain when required by retained
programs. This package profile does not expose cross-platform Cook from one kit.

Sequencer, GraphEditor, NiagaraEditor and the required UnrealEd services remain.
They still contain linked code needed by the current backend. SessionFrontend
is retained where NiagaraEditor imports it; DerivedDataEditor and ZenEditor are
retained where LevelEditor imports them. This release does not claim to have
completed a compiler/data versus graph/timeline-widget split.

Optional platform DDC remains separate. A compatible existing cache seed can be
reused, but qualify the base without any seed and a freshly extracted package
with the matching optional archive installed before workspace initialization.
Report base and base-plus-DDC download sizes separately.

## Qualification

Require native create/edit/save/independent-process reload, image and compatible
uncooked texture import, native material creation/binding, and uncached Cook.
Move only the newly copied preview-map fixture out of a fresh test workspace
before Cook, to prove that the native world creation/save path works.

Inspect GPU Sprite, CPU Ribbon and CPU Mesh PNGs at two simulation times, plus a
textured sprite render. Verify exact native particle counts, native RHI, no
editor modules in Shipping, successful process exits, no missing modules,
assertions, ensures or native errors, and no MainFrame dynamic loads. Observe
the bundled shader compiler processes during the empty-cache test. Repeat from
final extracted archives and inspect the actual images. Distinguish llvmpipe
GPUComputeSim from validation on a physical Linux GPU.
