# Existing material assets only

Starting with preview.7, material creation is outside this tool's API. The CLI
creation command and its backend branch were removed, including MaterialFactory,
material-expression graph construction, MaterialEditingLibrary calls and explicit
material recompilation. Texture import, compatible native asset import, material
catalog queries, Renderer resource bindings, JSON attachments and native Cook
remain supported. `capabilities` reports `materialAuthoring:false`.

Use a material authored in an external UE-compatible tool/project. Import its
uncooked asset and required dependencies using `import-assets`, or choose an
already bundled material. Set Renderer `Material` / `OverrideMaterials` through
the native property interface. Importing a texture does not automatically add
it to a material; its existing bindings/interfaces must consume that texture.

## Dependency boundary

The project worker never declared a direct MaterialEditor dependency. Its removed
Python creation branch accessed native engine/editor services already present in
UE. Deleting that branch cannot by itself remove every engine material module.
Native PE/ELF dependency evidence still connects MaterialEditor to Engine,
UnrealEd, NiagaraEditor and VirtualTexturingEditor; material utilities/baking also
have surviving consumers. Retain these shared services for native asset loading,
validation, compilation and Cook. No dummy symbol stubs or dependency-table edits
are used to hide missing native functionality.

The narrower packaging profile considers TextureEditor and MeshMergeUtilities
for removal only when no surviving native library imports them. Both static and
delay imports count on Windows; ELF DT_NEEDED counts on Linux. It updates the
matching `.modules` maps. Real texture import, source asset loading, Cook and
rendering must pass afterward because computed dynamic loads are not proven by
that static graph.

The same profile removes inactive ICU data copies and deployment presets.
Its data-version decision is derived from actual packaged Core binaries, not the
newest folder name: the qualified UE 5.8.1 backends use `icudt64l`. Preserve that
complete data root and its license; other data versions and All/CJK/EFIGS/English
deployment presets are not searched by those binaries at runtime. No locale is
removed from the active root. The separately cooked Shipping template is unchanged.

Run `package_profile.py --trim-material-authoring` against a verified matching
source kit. It emits per-platform material-profile evidence with removed paths,
byte counts, active ICU versions, blocked candidates and retained shared imports.
Archive compression sizes remain measured after sealing; logical bytes removed
must not be reported as compressed download savings.

## Preserved scope

Native material compilation during Cook is necessary for rendering existing UE
materials. It remains in the authoring backend. The Shipping output consumes
cooked shaders and does not gain material-authoring or editor dependencies.
The explicit native Python escape hatch still exposes whatever APIs the bundled
engine reflects; removing the product command is an API scope change, not a
security sandbox for arbitrary user scripts.
