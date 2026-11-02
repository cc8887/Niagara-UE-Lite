# JSON document verification — 2026-11-02

The native worker built on Windows and Linux against UE 5.8.1, changelist
56057345. These are local development kits, not an updated published Release.
Archive restoration was validated separately from JSON property overlay edits.
The final overlay worker invalidates script sources and forces compilation for
explicit edits; its edit/reload and failure tests passed on both platforms.

## Structural restoration

Each case exported an original asset, imported it into an independent workspace,
saved, reloaded in another process and re-exported it for comparison. Both
platforms passed the following cases:

| Case | Authored objects | Pin graphs | Compared properties |
| --- | ---: | ---: | ---: |
| GPU Sprite with two Simulation Stages | 123 | 55 | 2159 |
| CPU Ribbon | 80 | 30 | 1336 |
| CPU Mesh | 80 | 30 | 1337 |
| System referencing an actual local Scratch Pad module | 176 | 84 | 3051 |
| System with external parent Emitter and inherited snapshot | 132 | 54 | 2199 |
| Sprite using project material and texture attachments | 123 | 55 | 2159 |
| Standalone Emitter asset | 37 | 15 | 607 |

The inheritance document includes both System and parent Emitter packages.
The resource document includes the native material and texture with matching
file hashes. The standalone Emitter case retained all 37 native object bodies
identically on Windows; it also passed Linux restoration.

Comparison checks class, Outer, name, archetype, flags, package GUID/metadata,
reflected properties and complete exported pin graphs. It explicitly excludes
compiler-generated Graph change IDs, cached function change IDs and runtime
compiled-reference objects. Script native compiled/shader data can regenerate;
its nontransient reflected properties remain compared. Reports enumerate these
exclusions rather than claiming binary-identical packages.

## Paired behavior and rendering

Windows used RTX 5080 D3D12/SM6. Linux used Mesa 26.1.6 llvmpipe, LLVM 19.1.7,
Vulkan/SM6. Linux results are software Vulkan execution, not physical GPU
qualification. Fixed-seed scenes ran 60 frames with 16 warmup frames.

| Paired original/restored scene | Exact particles | Windows | Linux |
| --- | ---: | --- | --- |
| GPU Sprite | 98 | Repeat-render envelope passed | Repeat-render envelope passed |
| CPU Ribbon | 98 | PNG bytes identical | PNG bytes identical |
| CPU Mesh | 31 | PNG bytes identical | PNG bytes identical |
| GPU Sprite referencing Scratch Pad | 98 | Repeat-render envelope passed | Repeat-render envelope passed |
| Project material/texture Sprite | 98 | Repeat-render envelope passed | Structural/resource restoration checked; not paired-rendered |

GPU output is not claimed pixel-identical. On Windows the basic Sprite pair
differed in 338 pixels of 512x512, maximum channel delta 29 and mean absolute
channel delta 0.000912 on the 0–255 scale. Repeated renders of the same original
also differed, including maximum delta 29. Each non-identical pair therefore
ran two additional controls on both runtimes. The declared envelope allows at
most twice the observed control maximum plus one channel value, and twice the
maximum control mean (with a one-channel-value aggregate floor). Exact particle
counts are required independently. Reports retain all raw differences and
controls; this is a smoke acceptance envelope, not mathematical equivalence of
every possible particle history.

## Real edits and rejection behavior

Both platforms passed 10 checks with resource attachments: initialize; reject
corrupt native data, missing Outer, duplicate IDs, mismatched pin graphs, corrupt
resource hashes and resource path escape; import property edits; reload/re-export
those edits; reject collisions. Every rejected import left Content unchanged.

Successful edits changed node X position to 321, node comments, asset description
and package root metadata. The native-failure case installed resource files
before graph verification failed; CLI rollback removed those new resources.

## Cross-platform boundary

A Windows-exported Scratch Pad document imported, compiled and saved on Linux.
Its 177 object identities and all pin graphs matched after re-export. Full
property comparison still reported GPU Script `VersionData` and
`CachedScriptVMId` differences across platforms. This is partial portability
evidence, not full cross-platform semantic qualification. Same-platform
round-trip acceptance above passed separately on both platforms.

## Fixes needed during implementation

- Calling `PostLoad` on newly constructed objects without linker versions ran
  unwanted legacy migrations. Restore now uses current-build native archives.
- Package-wide live-object enumeration included orphaned graphs from parent
  merges. Export now retains the serialized reference/Outer/archetype closure.
- Nonpersistent memory archives included transient renderer binding caches.
  Both archive directions now use persistent serialization semantics.
- Native property overlays now issue edit notifications, invalidate script
  sources and request compilation instead of relying on old compile caches.

Reproduction tools: `tools/acceptance_document.py`,
`tools/acceptance_document_edits.py` and `tools/png_compare.py`. They write
documents, responses, logs, PNGs, render controls and structured reports outside
Git. Some long-running acceptance steps were retained with `--resume`; reports
distinguish measured evidence from source-only assessments.
