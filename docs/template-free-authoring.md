# Template-free native authoring

The product exposes native editing primitives rather than a table of effects.
`create` makes an empty System. `create --asset-kind emitter` makes an independent
Emitter asset. `add-emitter` without `asset` creates an empty emitter with no
parent, modules or renderers; `asset` optionally reuses a compatible existing
Emitter. An AI supplies the composition through operations, not an effect name.
This interface ships in preview.6; preview.5 used the older preset-based demos.

## Discover, author, inspect

Run `api` for operation names and required fields, then use `catalog` and `schema`
to discover assets and native properties. Catalog kinds include modules, emitters,
dynamic-inputs, renderers, data-interfaces, stage-classes, materials, textures,
meshes, and assets (with `--class`). Results come from the native registry and
loaded classes; module and emitter paths are not a fixed allowlist.

```sh
./niagara-cli api
./niagara-cli --workspace work create --asset /Game/Effects/MySystem
./niagara-cli --workspace work create --asset-kind emitter --asset /Game/Effects/MyEmitter
./niagara-cli --workspace work catalog --kind modules --search Spawn
./niagara-cli --workspace work schema --kind module --asset DISCOVERED_OBJECT_PATH
./niagara-cli --workspace work schema --kind input --asset /Game/Effects/MySystem \
  --emitter Primary --script ParticleSpawnScript --module MODULE_NAME --input INPUT_NAME
./niagara-cli --workspace work edit --asset /Game/Effects/MySystem --recipe operations.json
./niagara-cli --workspace work read --asset /Game/Effects/MySystem --out snapshot.json
```

A minimal `operations.json` can add an empty emitter:

```json
{"schema":"ue-niagara-recipe/1","operations":[{"op":"add-emitter","emitter":"Primary"}]}
```

This intentionally produces no particles. Discover modules and configure spawn,
initial attributes, updates, a Renderer and its material explicitly. A newly
constructed Renderer can have a null material; successful simulation then does
not imply a visible effect. Names such as `Particles`, `User`, `Emitter`, `Module`
and `Engine` are native reserved namespaces and cannot name an emitter.

## Native operation coverage

| Area | Implemented interface |
| --- | --- |
| Assets | Empty System and standalone Emitter creation, read/edit/save/reload, compatible uncooked asset import, native compile diagnostics |
| Emitters | Add empty or reuse asset, duplicate, remove, rename, enable, native property configuration |
| Module stack | Discover existing Module Scripts, add/remove/reorder/enable, native per-instance input schema |
| Inputs | Literal scalar/vector/position/color, enum/struct, links, dynamic inputs, object references, data interfaces, inline HLSL input expressions, reset |
| Parameters | User parameters; generic native Set Parameters modules and attribute assignments |
| Extra stacks | CPU Event Handler CRUD; GPU Simulation Stage CRUD, order/enable/properties, distinct usage GUID identity |
| Renderers | Discover classes, create/remove/configure native Renderer objects, assign material and mesh assets |
| Resources | Texture import, compatible existing-asset import, discover/reference texture/material/mesh assets; no material creation |
| Output | Compile, targeted offline Cook with dependency closure, native UE simulation/rendering, PNG and runtime metadata |

Use `schema --kind stacks` for usage IDs and `schema --kind stage` for properties.
Event and Simulation stack operations require `usageId` to distinguish multiple
stacks with the same usage. Module operations use native module name/GUID from
the snapshot; identities must not be guessed from display labels.

`asset-properties` edits fields exposed by native asset property schema;
`emitter-properties` targets versioned emitter simulation properties.
Independent Emitter editing infers the emitter context, whereas System editing
must specify it when an operation targets an emitter.

`--compile-policy require-valid` is the default. `allow-errors` saves incomplete
authoring with explicit native compilation diagnostics; `defer` skips the compile
request. Neither option relaxes Cook or rendering success requirements.

`native-python --file script.py --params params.json` is an escape hatch using
the bundled native `unreal` API. It supplies `params` and accepts a JSON-serializable
global `result`; scripts own their save/transaction behavior. Only reflected
APIs are accessible, and some fields are protected. This is not full editor parity.

## Cook and packaging

Cook selects the requested root asset plus native dependencies and the preview
world. Add `--include /Game/Effects/AnotherSystem` for additional roots. Unrelated
unfinished effects in the workspace are not included solely because they share
the Content directory. Native cooked output is UE-version and platform specific.

Default staging omits Niagara `DefaultAssets/Templates`, fixed example recipes
and project demo effects. It also rebuilds the runtime scaffold Pak to remove
previously cooked demo effects. Preview world infrastructure and reusable native
modules, materials and meshes remain. Optional reuse of user-supplied emitters
does not make templates a creation prerequisite.

## Verification and limits

`tools/acceptance_template_free.py` runs public commands in a fresh workspace
without template assets. Its three effect compositions are developer acceptance
fixtures, not product dispatch rules. It verifies empty creation, independent
Emitter save/reload, module discovery, generic assignments and expressions,
Cook and Sprite/Ribbon/Mesh output. Use `--authoring-only` to skip Cook/render;
that mode alone is not rendering acceptance.

Local Windows D3D12 and Linux Vulkan/llvmpipe tests built GPU Sprite, CPU Ribbon
and CPU Mesh systems from empty emitters with explicit resource bindings. Event
handlers and two distinct Simulation Stages were edited and reloaded on both
platforms. Event graph CRUD does not establish actual event delivery. The GPU
Sprite example executed stages; Linux llvmpipe is software execution of GPU
compute shaders, not physical Linux GPU qualification.
Actual verification boundaries and measurements are recorded in
[template-free-validation.md](template-free-validation.md).

This is not yet "almost every editor operation." Existing compatible assets
have no effect-name whitelist, but unsupported plugin classes need their plugins
and resource closure. Creating/editing internal custom Module Script graphs,
Stateless Emitter authoring, module version switching, and arbitrary world-bound
interfaces have not received full API implementation and end-to-end validation.
Inline HLSL input expressions do not provide an internal Module Script graph API.
Native UE compilation and simulation remain; there is no replacement Niagara VM.

Existing internal graphs, Scratch Pads, inheritance and editor object state can
now be transferred by the separate [native JSON document](json-round-trip.md)
interface. Restoring those graphs does not imply an API for constructing new
custom module graphs from individual JSON nodes.
