# Editor module separation assessment

Assessment date: 2026-10-30. Baseline: UE 5.8.1, preview.4, source
`077035df38c42b0b03c9b623cd145016e71a3754`.

This is a source and binary inventory assessment, not a rebuilt or qualified
smaller release. Sizes use decimal MB (1,000,000 bytes). Current releases remain
the qualified distributions.

This document records the preview.4 planning baseline. Subsequent implementation
uses the [commandlet service profile](editor-backend-profile.md); references to
the Python preview author and EditorScriptingUtilities below describe that
baseline, not the current native preview creation path.

## Measured occupancy

The Windows figures come from members of the actual published ZIP. Linux
uncompressed sizes come from its final archive inventory; gzip figures below
are separate gzip level-6 compression of the actual extracted libraries, not
exact marginal savings from deleting members of a shared tar.gz stream.

| Module | Windows payload MB | Windows ZIP MB | Linux payload MB | Linux gzip proxy MB |
|---|---:|---:|---:|---:|
| MainFrame | 1.050 | 0.386 | 1.073 | see group |
| Persona | 14.771 | 4.665 | 15.817 | see group |
| Sequencer | 11.614 | 4.332 | 12.550 | see group |
| GraphEditor | 4.313 | 1.451 | 4.542 | see group |
| Four-module total | **31.747** | **10.834** | **33.982** | **12.016** |

Only removing these four binaries would save less than 1% of the current
Windows base archive and roughly 1.2% of the Linux archive. It is not currently
safe to remove them. Shared dependencies must only be counted once.

A broader 34-module *candidate inventory* occupies 106.170 MB of Windows
payload / 36.533 MB of ZIP data, or 114.762 MB of Linux payload / 40.290 MB of
separate gzip data. This includes the four above and SequencerCore,
SequencerWidgets, MovieSceneTools, CurveEditor, LevelEditor, ContentBrowser,
ContentBrowserData, PropertyEditor, EditorWidgets, ToolMenus, ToolMenusEditor,
ToolWidgets, KismetWidgets, AnimationEditor, AnimationBlueprintEditor,
PhysicsAssetEditor, SkeletonEditor, SkeletalMeshEditor, StaticMeshEditor,
MaterialEditor, TextureEditor, VREditor, ViewportInteraction,
ComponentVisualizers, DetailCustomizations, PlacementMode,
WorkspaceMenuStructure, AssetTools, DataHierarchyEditor and UserAssetTagsEditor.

This inventory is not a safe deletion list. AssetTools and MaterialEditor in
particular currently provide services exposed by the CLI. Retained replacements
and new module glue reduce any gross saving. It is not an exclusive transitive
dependency closure, and no additional savings from its dependencies are assumed.

## Why headless switches do not remove the dependencies

The current native worker directly depends on NiagaraEditor and UnrealEd. In
this engine source:

* `Plugins/FX/Niagara/Source/NiagaraEditor/NiagaraEditor.Build.cs:27-39`
  declares Sequencer, GraphEditor and MainFrame dependencies. Sequencer is
  also a public dependency at line 93.
* `NiagaraEditor/Private/NiagaraEditorModule.cpp:1212` loads ContentBrowser
  during startup. Line 1539 loads Sequencer and registers editor tracks/channels.
  The same startup function registers the graph pin factory at line 1530 and
  indispensable compiler callbacks around lines 1591-1645.
* `Source/Editor/GraphEditor/GraphEditor.Build.cs:40` declares Persona.
  This build dependency alone does not prove a direct imported Persona symbol.
* `Source/Editor/UnrealEd/UnrealEd.Build.cs:147,156` declares GraphEditor and
  LevelEditor; MainFrame and Persona also appear in its dynamic-load list.
* `Source/Runtime/Engine/Engine.Build.cs:306-337` adds GraphEditor and
  MaterialEditor for editor-capable builds.

Static PE import and delay-import evidence in the current Windows payload shows:
GraphEditor has 24 importing libraries (including Engine, UnrealEd,
NiagaraEditor); Sequencer has 5 (including NiagaraEditor, MovieSceneTools,
UMGEditor and VREditor); Persona has 6 (including MeshUtilities and several
animation editors). MainFrame has no static importer in that scan, but native
source contains explicit dynamic loads. Zero PE imports is not removal proof.
These counts are Windows evidence, not an ELF dependency audit for Linux.
Import-symbol inspection additionally found 46 GraphEditor imports in Engine,
100 in UnrealEd, and 189 in NiagaraEditor; NiagaraEditor also imports 46
Sequencer symbols. These are actual symbol-level constraints, including
SGraphNode/SGraphPin UI symbols, rather than just Build.cs declarations.

`-NullRHI`, commandlet mode, or skipping UI registration at runtime can avoid
work but cannot eliminate symbols already linked into a DLL/SO. Compilation
units, dependencies, auto-load registrations and startup/shutdown paths must all
be separated, then the affected binaries rebuilt for both platforms.
The general distinction between declared build dependencies and explicit
runtime module loading is described in Epic's
[module documentation](https://dev.epicgames.com/documentation/en-us/unreal-engine/unreal-engine-modules).

## Proposed separation

Keep Niagara's serialized data, graph edits and compilation services in the
backend; move visual presentation and integration out of that build profile.
Any new profile switches below are proposed project changes, not existing UE
TargetRules options.

1. **Separate Niagara startup and compilation from UI.** Keep node/script source
   types, graph traversal, HLSL/VectorVM translation, parameter definitions,
   async compilation callbacks, factories and save hooks. Exclude toolkit
   windows, visual pins, menu registration, property customizations and
   Sequencer track editors in a dedicated no-UI build profile. Preserve the
   `/Script/NiagaraEditor` identity of serialized UClasses. Moving them to a
   new module without redirects/resaving can break existing .uasset files.

2. **Remove MainFrame, Persona and Sequencer integration.** Remove MainFrame
   calls from window/dialog-only paths, split animation UI out of generic graph
   and mesh services, and exclude Sequencer adapters rather than MovieScene
   runtime data. Keep skeletal mesh data/import/build capabilities needed by
   Niagara data interfaces and Mesh rendering. MeshUtilities is a measured
   Persona importer and requires attention. Existing external edit utilities
   use a data-only view model that skips SetupSequencer, but diagnostics can
   create a full view model: migrate those issue queries before promising the
   same diagnostic behavior. Runtime branches alone do not remove linkage.

3. **Separate graph data from graph widgets.** `UEdGraph`, pins, Niagara nodes,
   schema validation, stack topology edits and compiler traversal remain
   necessary. `SGraphEditor`, visual nodes and Slate pin factories can be
   excluded. Niagara's external edit API currently uses stack/view-model
   services extensively, so replacing it with raw property writes would lose
   important edit semantics. Extract those services with their notifications,
   static-switch handling and invalidation behavior intact. Engine, UnrealEd,
   Kismet/Blueprint and other retained importers must no longer reference the
   removed graph-widget symbols.

4. **Replace existing CLI UI-oriented service entry points.**
   `tools/author_preview.py` uses LevelEditorSubsystem to create/save the preview
   level. Replace it with native world/package creation and save services before
   removing LevelEditor. `tools/assets_worker.py` uses AssetTools for texture
   import, MaterialFactoryNew and MaterialEditingLibrary for sprite materials.
   Retain their non-UI services or port the current operations into native
   commandlets first. Preserve image formats, source-art path handling, shader
   compilation, texture binding and save/reload. Keep the Python backend until
   every existing Python operation has an equivalent replacement; Python removal
   is not included in the size estimate.

5. **Trim UnrealEd UI and follow the resulting resource closure.** Keep Cook
   commandlets, package loading/saving, editor-only serialization, importers,
   target formats, shader workers and DDC. Exclude unwanted level/VR/animation
   UI registration and its code references, rebuild, then remove newly
   unreachable libraries/resources. The previous native ViewportInteraction
   startup assertion must become a regression case: its assets may only be
   removed once the owning startup code is excluded. Do not simply delete the
   nine native resource roots retained in preview.4.

Preserve the cooked Shipping renderer and native RHI/Renderer/Niagara runtime.
Authoring changes must still produce native UE shaders and cooked assets; a new
JSON renderer is outside this design. Keep MovieScene/Tracks/LevelSequence when
required by retained asset types; removing the Sequencer editor does not imply
these runtime modules are unnecessary. Do not disable WITH_EDITORONLY_DATA or
all editor support merely to make linkage smaller.

## Budget and order

Start with the Niagara module split and MainFrame/animation/Sequencer adapters,
then the graph-widget split and LevelEditor/asset-service replacements. Do not
begin by rewriting all of UnrealEd.

The measured broad candidate inventory provides a gross anchor of approximately
36.5 MB Windows ZIP / 40.3 MB Linux gzip proxy. Additional reductions inside
NiagaraEditor (current payload 25.136 / 28.240 MB) and UnrealEd (35.519 / 43.372
MB) are possible, but most of their compiler/Cook/data code must remain.

An engineering planning range for a successful wider split is **25-50 MB less
Windows archive data and 30-60 MB less Linux archive data**, approximately
80-160 MB less installed payload, with strong uncertainty. This range allows
for retained/replacement services and partial trimming of the two large
modules. It is not the output of a compiled minimal module closure. Do not add
the four-module or 34-module totals to this range; they overlap.

Against preview.4 base archives of 1,149,693,839 / 1,001,322,197 bytes, this would
put a hypothetical base near **1.100-1.125 GB Windows / 0.941-0.971 GB Linux**.
Optional DDC is unchanged and its previously achieved split is not counted as
another saving. Larger reductions require a separate audit of third-party
libraries, target formats, engine resources and the duplicated preview payload;
this editor-module assessment does not establish those savings.

## Acceptance before publishing

Use matching UE 5.8.1 source and isolated build/staging outputs. The current
Editor target is not a minimal program target; changing its type or only
editing Build.cs cannot qualify a replacement. Maintain a separate explicit
backend profile and account for regenerated reflection/serialized types and
all dependent library ABI changes.

For each platform require imports/DT_NEEDED and module metadata audits, native
module-load traces, no-cache creation and Cook, edits followed by explicit
save and independent-process reload, adding/removing emitters/modules,
parameter/static-switch edits, compatible texture import, sprite material
creation and rebinding. Render GPU Sprite, CPU Ribbon and CPU Mesh at both
validation times; inspect native PNGs and particle-count metadata. Windows
uses D3D12/SM6; Linux uses Vulkan/SM6, recording whether its device is physical
or llvmpipe. Repeat from freshly extracted base packages, with and without
optional DDC. Measure final archives and logical/stored payload separately.

No release is updated on the basis of this assessment alone.
