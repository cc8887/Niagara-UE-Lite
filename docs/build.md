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
