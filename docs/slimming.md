# Standalone package slimming

The production profile excludes Chromium (CEF), optional Vulkan tools/layers,
external debug symbols and static libraries. Windows also excludes ARM64
binaries and D3D12 SDK debug layers, retaining the x64 D3D12 core. Linux retains
its Vulkan loader; removing diagnostic layers does not replace Vulkan rendering.

All operations use a new output tree. Do not run strip, remove dependencies, or
replace modules in the source engine or an already published kit.

## CEF dependency boundary

Windows uses the existing native DLLs. Their Chromium entrypoints are delay
imports; the supported unattended authoring/Cook flow is qualified without the
CEF files. This does not qualify browser UI or arbitrary editor workflows.

Linux's original backend has this hard dependency chain:

```text
UnrealEditor-Cmd -> UnrealEd -> MaterialBaking -> MainFrame -> WebBrowser -> libcef.so
```

`tools/build_nocef_backend.py` recompiles the actual WebBrowser and CEF3Utils
sources with `WITH_CEF3=0`. It derives private compiler/linker response files
from the matching engine build, textually includes its shared definitions/PCH
header, and retains all other original ABI/compiler flags. The CEF-enabled
binary PCH is not reused. No engine source or output is changed. CEF libraries
are omitted from the new link command, not removed by patching an existing ELF.

The original matching UE `.modules` BuildId remains unchanged. The rebuilt
ELF linker build IDs identify new binaries; they are not the UE module BuildId.
The helper checks native module registration, SONAME, dynamic dependencies and
undefined CEF symbols. Runtime acceptance is still required after those checks.

```sh
python3 tools/build_nocef_backend.py --engine <matching-engine> --work <new-build-folder>
python3 tools/slim_package.py --source <verified-kit> --out <new-stage> --overrides <new-build-folder>/overrides --strip-tool <matching-llvm-objcopy> --private-root <matching-engine>
```

The rebuild helper currently requires the matching UE 5.8.1 Linux unity build
response files and compiler. It is not a general engine-version migration tool.

## Symbols and duplicate libraries

Linux copies are processed with the matching SDK's `llvm-objcopy --strip-unneeded`
(or a compatible strip executable). Before/after checks
require every `SHF_ALLOC` section, including dynamic symbols, relocations and
loader-visible data, to retain its name, type, flags, virtual address, size,
alignment and content. Source files and original binaries are preserved.
External `.pdb`, `.debug`, `.sym`, `.a`, `.lib` and object files are excluded.

GNU BFD strip can normalize an ELF init-array section's entry size from zero
to eight without changing its loaded bytes. This workflow does not relax the
section checks for that case: use the matching LLVM tool, which preserved the
original metadata in qualification.

Library hashes are calculated after stripping and build-path redaction. Linux
keeps all SONAME/alias paths as hardlinks to one stored copy; the tar archive
preserves these links. `verify_archive.py` verifies both each path's content and
the extracted hardlink relationships. Symbol stripping and duplicate removal
overlap, so their individual byte estimates must not simply be added together.

On Windows, a small set of DLLs is identical between the backend and internal
runtime template. The kit stores each once in the backend and records the
runtime path in `runtime-template-links.json`. During Cook, the CLI validates
size/SHA256 and copies those files into the exported preview. An exported
runtime contains ordinary files and does not refer back to the kit. The native
launcher and its bundled Python dependencies do not need a bootstrap step.

Windows staging does not need an overrides directory:

```sh
python tools/slim_package.py --source <verified-kit> --out <new-stage>
```

The script freezes a new package file list before tests. It refreshes scripts,
examples and documents from the current source checkout. Only that list is
sealed, so native test logs/workspaces cannot enter the archive.

## Qualification and size reporting

```sh
python tools/acceptance_slim.py --root <new-stage> --workspace <new-workspace> --out <new-evidence>
```

For Linux software Vulkan, add `--cpu-vulkan`. This exercises real creation,
input editing, explicit save, independent-process reload, restoration, Cook,
GPU Sprite, CPU Ribbon and CPU Mesh at 30/60 frames. Runtime metadata and PNG
content are checked; visual inspection is recorded separately. Linux llvmpipe
testing qualifies GPUComputeSim on a software device, not a physical Linux GPU.

Seal using `tools/package_standalone.py --seal` and the normal build-path
settings, then freshly extract and run `tools/verify_archive.py`. Re-run native
acceptance from the extracted kit, and move an exported runtime to a separate
directory to check its independence from the authoring package.

Report compressed archive bytes, logical payload bytes and stored payload
bytes separately. `payloadBytes` includes each manifest path's file length;
`storedPayloadBytes` counts shared hardlink storage once. Both exclude the
manifest's own bytes. Archive size is the actual completed ZIP/tar.gz size.
Before/after figures must compare the same platform and scope; keeping two
hardlinked names does not reduce their summed logical file lengths.

Release metadata contains the measured sizes and SHA256. This profile retains
the headless UnrealEd/NiagaraEditor and shader/Cook backend. The generated
Shipping preview continues to run without loading editor modules.
