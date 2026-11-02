# Existing Niagara assets as editable building blocks

This describes the earlier composition prototype. For current empty-asset
creation, standalone Emitters, extra stacks and packaging boundaries, see
[template-free-authoring.md](template-free-authoring.md).

The general authoring work extends the native CLI beyond the bundled demonstration
recipes. Emitter and module asset paths are not an allowlist. Assets must be
uncooked and compatible with UE 5.8.1 and the installed plugins. This does not
create new module scripts, edit their internal graphs, or author HLSL.

## Discover first

Run these commands in an updated standalone kit:

```sh
./niagara-cli --workspace work catalog --kind emitters --limit 5000
./niagara-cli --workspace work catalog --kind modules --search Gravity
./niagara-cli --workspace work catalog --kind dynamic-inputs --search Random
./niagara-cli --workspace work catalog --kind renderers
./niagara-cli --workspace work catalog --kind data-interfaces
./niagara-cli --workspace work schema --kind module \
  --asset /Niagara/Modules/Update/Forces/GravityForce.GravityForce
```

Windows uses `niagara-cli.exe`. Catalogs describe assets/classes available in that
kit and workspace; a catalog entry is not a runtime qualification. `--root`,
`--search`, `--offset`, and `--limit` restrict asset enumeration. Renderer and DI
catalogs enumerate loaded concrete classes. Script catalogs load matching script
assets to check native usage.

Use a new workspace with an updated kit: existing workspaces contain a copy of
the native worker binary and are not automatically upgraded. On Windows choose
a short workspace path; UE's filesystem DDC root has a 119-character limit.

## Compose, configure, save

```sh
./niagara-cli --workspace work create --asset /Game/Effects/Composition \
  --recipe examples/general-composition.json
./niagara-cli --workspace work schema --kind instance \
  --asset /Game/Effects/Composition --emitter Confetti \
  --script ParticleUpdateScript --module GravityForce
./niagara-cli --workspace work schema --kind input \
  --asset /Game/Effects/Composition --emitter Confetti \
  --script ParticleUpdateScript --module GravityForce --inputs Gravity
```

Use the instance's native function name from `read` or `schema`; repeated modules
can receive different function names. Instance queries also return node GUID and
module index. Input schemas expose the current type, enum entries, metadata,
current value, dynamic chain and available native dynamic-input suggestions.
After changing a static switch, query again: the visible input set can change.

Recipe operations additionally include:

| Operation | Fields |
| --- | --- |
| `add-emitter` | `emitter`, existing `template` asset |
| `remove-emitter` | `emitter` |
| `rename-emitter`, `duplicate-emitter` | `emitter`, new `name` |
| `add-module` | `emitter`, `script`, existing `asset`; optional `after` function name |
| `remove-module` | `emitter`, `script`, `module` |
| `move-module` | `emitter`, `script`, `module`, final zero-based `index` in that stack |
| `module-enabled` | same module reference, boolean `value` |
| `input` | module reference, `input` or nested `inputs` array, `type`, `value` |
| `reset-input` | module reference and `input` or `inputs` |
| `set-user` | `name` starting with `User.`, concrete `type`, `value` |
| `remove-user` | `name` |
| `add-renderer` | `emitter`, concrete installed renderer `class` |
| `renderer-properties` | `emitter`, `renderer` index, native `properties` object |

Existing system/emitter property and renderer removal operations remain available.
`add-module` appends unless `after` identifies an existing module. `move-module`
uses UE's native graph move and preserves the node identity and attached inputs.
It does not recreate the module. Native inherited/required-module restrictions
apply. Each operation gets a fresh data-only edit context so structural changes
do not leave subsequent operations using stale stack references.

Typed input values:

| `type` | `value` |
| --- | --- |
| `float`, `int`, `bool` | JSON scalar |
| `vec2`, `vec3`, `color` | array of 2, 3, 4 numbers |
| `enum` | exact qualified entry returned by input schema |
| `struct` | reflected property object; also supply `struct` type path |
| `linked` | parameter name, e.g. `User.Gravity`; type comes from the input |
| `dynamic-input` | existing DynamicInput script asset path |
| `data-interface` | editable properties of the input's actual DI class |
| `object` | compatible existing texture/mesh/other asset path |

For example, a nested dynamic input uses
`"inputs": ["SpawnRate", "Range"]`. Configure the parent dynamic input first,
then query it and set its nested fields. A Data Interface is configured through
its actual native property schema, including resource references supported by
that class. This is not a replacement for a world, actor, skeletal component or
simulation-stage setup required by scene-dependent interfaces.

`set-user` supports concrete scalar/vector/color/struct values and object assets
(supply the expected `class` path). DI and enum user-default creation are not yet
covered by this bridge; do not confuse module input support with user-default
support. Changing an existing user's type requires explicit removal first.

```sh
./niagara-cli --workspace work edit --asset /Game/Effects/Composition --recipe edits.json
./niagara-cli --workspace work read --asset /Game/Effects/Composition --out reloaded.json
./niagara-cli --workspace work cook --asset /Game/Effects/Composition --package preview
./niagara-cli render --asset /Game/Effects/Composition --package preview --out effect.png
```

Successful create/edit saves the native `.uasset`; edit backs up the previous
package. A failed operation does not save the system, although the process can
have made temporary in-memory changes. `read` starts a separate backend process.
Cook uses native UE tools and rendering uses the existing native Shipping runtime.

## Import existing assets

```sh
./niagara-cli --workspace work import-assets --source incoming/Content
```

Supply a Content-root directory containing compatible native packages and their
dependency closure. Relative package paths are preserved under `/Game`; sidecars
are copied with their packages. Existing destination files are refused, traversal
is rejected, and copied files are rolled back if loading fails. Native loading
does not prove that every scene-dependent behavior will work. Plugin-mounted
assets must retain their plugin mount and require a corresponding plugin pack;
copying them to `/Game` does not rewrite their references.

## Compatibility boundary

The current external-edit API exposes the six standard System/Emitter/Particle
Spawn/Update stacks. This bridge does not yet provide creation and editing of
Event Handler or Simulation Stage stacks. It preserves the native assets and
their graph data. New third-party native classes require matching backend **and**
runtime binaries; importing a `.uasset` cannot install C++ classes.

The slim profile was qualified on a small renderer fixture set. General authoring
needs dependency checks and optional plugin/resource packs. For example,
`WindForce` references a Physics Field DI supplied by `ChaosNiagara`; the minimal
Niagara-only project does not enable that plugin. A successful static-off compile
does not qualify using that DI at runtime. Broad authoring support takes priority
over retaining the smallest demonstration-only package.

## Developer build

`tools/patch_ue58_general_authoring.py` adds DLL visibility to existing native
reference getters and stack utilities in an isolated matching source copy.
No reflected layouts are changed. Recompile NiagaraEditor and the project worker
together. `tools/build_general_authoring_linux.py` recompiles the two affected
original UBT unity units from a complete isolated NiagaraEditor source copy and
links against the original final dependency set. These are developer build tools,
not tools required on an end user's machine.

This source work is not included in preview.5. Consult its validation evidence
before describing a newer package as qualified or publishing it.
