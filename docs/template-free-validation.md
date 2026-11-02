# Template-free development verification — 2026-10-30

Matching UE 5.8.1 native binaries were built for Windows and Linux. These results
describe local development kits, not a new published Release. Both kits excluded
the native emitter-template directory. The project demo directory and bundled
fixed example recipes were removed; native UnrealPak also removed the two old
cooked Fountain files from each runtime scaffold.

| Check | Windows | Linux |
| --- | --- | --- |
| Fresh-workspace generic authoring acceptance | Passed | Passed |
| Empty emitter: no parent, modules or renderers | Passed | Passed |
| Standalone Emitter create/edit/save/reload/reuse | Passed | Passed |
| Editable root asset property save/reload | Passed | Passed |
| Two independent Simulation Stage stacks | Passed | Passed |
| Two CPU Event Handler stacks, edit/remove/reload | Passed | Passed |
| Native Python AssetTools duplicate/save | Passed | Passed, fresh reload also passed |
| Selected-root Cook and native rendering | Passed | Passed |

The native external editing bridge previously looked up extra stacks using a
zero usage GUID. Multiple stages/events could consequently resolve incorrectly.
The patch retains native usage IDs without changing reflected object layout;
snapshots and edits distinguish the two stacks. Linux rebuild tooling also
rewrites relative unity includes and compiler response source paths so patched
function bodies, not just exported headers, are compiled.

All rendering examples were authored from empty emitters using generic native
assignment/module/Renderer operations and explicit material/mesh bindings.
Native runtime metadata reports normal exit, nonblack pixels and exact counts:

| Example | Simulation | Windows D3D12/SM6 | Linux Vulkan/SM6 |
| --- | --- | --- | --- |
| Sprite with two stages | GPUComputeSim | 98 particles, maxRGB 255 | 98 particles, maxRGB 255 |
| Ribbon | CPUSim | 98 particles, maxRGB 240 | 98 particles, maxRGB 240 |
| Mesh | CPUSim | 31 particles, maxRGB 197 | 31 particles, maxRGB 197 |

Windows used RTX 5080. Linux used llvmpipe (LLVM 19.1.7), Mesa 26.1.6; this
qualifies software Vulkan execution, not a physical Linux GPU. Screenshots were
visually inspected: orange GPU sprites, cyan ribbon and small magenta mesh
instances. These are functional smoke scenes, not a particle-quality benchmark.

Event tests validate asset editing and stack identity; they do not prove event
delivery. The fresh-workspace acceptance runs used `--authoring-only`; rendering
was verified separately with selected-root Cook in populated native workspaces.
No custom internal Module Script graph or Stateless Emitter test was performed.

Developer reproduction: `tools/acceptance_template_free.py --root KIT
--workspace NEW_WORK --out NEW_EVIDENCE` runs the public authoring/Cook/render
flow. On Linux supply a compatible Vulkan SM6 driver and add `--cpu-vulkan` for
CPU-device rendering. The tool records step JSON, recipes, runtime logs and PNGs;
review those images before claiming visual acceptance.
