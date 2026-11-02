# Build and qualification

Build inputs are supplied through environment variables. Do not add local
engine paths, credentials, archives or executables to Git.

- `NIAGARA_BUILD_ENGINE`: matching UE 5.8.1 Engine directory.
- `NIAGARA_BUILD_PROJECT`: optional absolute `.uproject` path in an isolated
  build directory. Copy RuntimeProject sources/config there first.
- Linux additionally needs the matching UE v26 clang 20.1.8 SDK through
  `LINUX_MULTIARCH_ROOT`. Windows needs the UE-supported MSVC/Windows SDK;
  launch from a Visual Studio developer shell for the small native CLI launcher.

The Linux CPU Vulkan and UnrealPak path fixes were carried forward from the
Material-UE-Lite implementation. Check before building; apply explicitly only
to the intended isolated UE source tree:

```sh
python3 tools/patch_ue58_cpu_vulkan.py --apply
python3 tools/patch_ue58_standalone.py --apply
python3 tools/build.py --archive /path/to/runtime-stage --jobs 8
```

Rebuild UnrealPak's PakFileUtilities module after applying its path fix. The
Windows installed engine does not need that Linux path fix. The CPU compatibility
engine switches retain the historical `MaterialRenderCpuVulkan` name; the new
CLI passes that switch together with its own CPU-runtime settings.

Packaging uses `NIAGARA_PACKAGE_ENGINE`, `NIAGARA_PACKAGE_PROJECT` (directory),
`NIAGARA_PACKAGE_RUNTIME` (the archived Windows/Linux subdirectory) and
`NIAGARA_PACKAGE_DIST`. Optional `NIAGARA_PACKAGE_LAUNCHER` supplies the Windows
`niagara-cli.exe`; `NIAGARA_PACKAGE_SEED_DDC` adds a qualified native file cache.
`NIAGARA_PACKAGE_PRIVATE_ROOTS` is a JSON array of additional build roots to audit.

```sh
python3 tools/package_standalone.py --stage-only
python3 tools/acceptance_authoring.py --root /path/to/kit --workspace /path/to/new-workspace --out /path/to/new-evidence
python3 tools/acceptance_textures.py --root /path/to/kit --workspace /path/to/new-texture-workspace --out /path/to/new-texture-evidence
python3 tools/package_standalone.py --seal
```

Staging freezes an explicit file list before validation. Sealing only packages
that list, so test workspaces, local logs and user assets cannot enter the kit.
The archive contains a per-file SHA256 manifest. Revalidate the final extracted
archive, including Cook and preview after the original build engine is hidden
or otherwise proven unused. Report visual and simulation evidence separately.

The portable frontend normally uses only `backend/Engine`, `Project` and
`runtime-template` beside itself. Developer-only overrides are
`NIAGARA_LITE_ENGINE`, `NIAGARA_LITE_PROJECT` and
`NIAGARA_LITE_RUNTIME_TEMPLATE`; clear them for standalone qualification.

The smaller production profile, Linux no-CEF module rebuild, symbol stripping,
library deduplication and edit/render acceptance are described in
[slimming.md](slimming.md). Rebuild or slim only into a new output tree; preserve
published bundles until the replacement passes extracted-package validation.

The source-patched commandlet service profile, editor-module dependency pass and
platform-specific rebuild helpers are described in
[editor-backend-profile.md](editor-backend-profile.md). Source compilation and
static closure checks do not replace extracted-package native qualification.

## Generic authoring and JSON document profile

`patch_ue58_general_authoring.py` exports the existing native stack-edit services.
`patch_ue58_stack_identity.py` preserves Event/Simulation Stage usage GUIDs in the
native bridge. Apply these only to a task-owned UE 5.8.1 source copy, rebuild
NiagaraEditor, and then rebuild the project worker. The Linux helpers
`build_general_authoring_linux.py --stack-identity` and
`build_authoring_worker_linux.py` reuse matching UBT responses outside the source
engine; the former rewrites both unity includes and response-file source paths.

For a previously qualified curated kit whose native workers were updated and
qualified, use `package_profile.py --source <kit> --out <new-stage>` to preserve
its curated module selection. Supply the matching LLVM objcopy using
`--strip-tool` on Linux, and repeat `--private-root` for local build prefixes.
It excludes optional DDC and effect presets, strips only distributable ELF copies,
deduplicates Linux libraries, removes old cooked fixture effects, refreshes the
portable frontend/docs and freezes a file list. Never use a test workspace as
the profile source.

Seal with `package_standalone.py --seal`. Set `NIAGARA_PACKAGE_SOURCE_COMMIT` and
`NIAGARA_PACKAGE_RELEASE` to record provenance. Qualify from the final extracted
archive using `acceptance_template_free.py`, `acceptance_document.py` and
`acceptance_document_edits.py`; include real Cook/render evidence. Optional DDC
remains a separate release asset. `audit_source.py --staged` rejects binary assets,
archives, host absolute paths and credential-like tokens before committing.
