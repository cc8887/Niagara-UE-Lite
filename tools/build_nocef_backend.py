#!/usr/bin/env python3
"""Rebuild Linux WebBrowser/CEF3Utils without Chromium in an isolated output tree.

Requires matching, already-built UE source and its UBT response files. This does
not edit engine source, its build products, or the package. It uses native
WITH_CEF3=0 compilation, not ELF dependency removal. Browser functionality is
intentionally unavailable; this backend is for unattended Niagara authoring.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time


MODULES = ("CEF3Utils", "WebBrowser")

# This helper accepts the qualified UBT unity-response format only. An unknown
# option is not forwarded to a compiler/linker that could write into Engine.
COMPILE_FLAGS = {
    "-nostdinc++", "-fno-math-errno", "-fno-rtti", "-mssse3", "-fPIC", "-c", "-pipe",
    "-msse4.2", "-fdiagnostics-absolute-paths", "-fdiagnostics-color", "-fno-delete-null-pointer-checks",
    "-O3", "-fexceptions", "-gdwarf-4", "-ggnu-pubnames", "-fvisibility-ms-compat",
    "-fvisibility-inlines-hidden", "-fpch-validate-input-files-content",
}
COMPILE_VALUES = {
    "--driver-mode", "-gz", "-fbinutils-version", "-ftls-model", "--sysroot",
    "-ftabstop", "-fdiagnostics-color", "-ffp-contract", "-std",
}
LINK_FLAGS = {"-fdiagnostics-absolute-paths", "-fdiagnostics-color", "-rdynamic", "-shared", "-nodefaultlibs"}
LINK_VALUES = {"-fdiagnostics-color", "--driver-mode", "-fuse-ld", "-gz", "--sysroot"}
LD_FLAGS = {"--gdb-index", "--disable-new-dtags", "--as-needed", "--build-id", "--start-group", "--end-group"}
LD_VALUES = {"-rpath", "-rpath-link", "--hash-style", "--build-id", "--unresolved-symbols", "-soname"}


def argument_path(value, cwd):
    path = Path(value)
    return path.resolve() if path.is_absolute() else (cwd / path).resolve()


def guard_response(lines, kind, cwd, expected_output, *, dependency=None,
                   object_response=None, unity_source=None, shared_response=None,
                   allow_pch=False, work=None):
    """Reject unhandled response forms before executing any native command."""
    counts = {"output": 0, "dependency": 0, "objectResponse": 0,
              "unitySource": 0, "unityObject": 0, "include": 0, "pch": 0, "shared": 0}

    def matches(value, expected, label, writing=False):
        actual = argument_path(value, cwd)
        if expected is None or actual != expected.resolve():
            raise ValueError(f"Unexpected {kind} {label} path")
        if writing and work is not None and not actual.is_relative_to(work.resolve()):
            raise ValueError(f"{kind} output escapes isolated work directory")

    def ld_option(token):
        # Clang splits every comma after -Wl,. Do not let an allowed rpath
        # hide a second, unvalidated linker output option.
        return "," not in token and (token in LD_FLAGS or
                                     ("=" in token and token.split("=", 1)[0] in LD_VALUES))

    for line in lines:
        if not line.strip():
            continue
        tokens = shlex.split(line)
        if not tokens:
            raise ValueError(f"Empty {kind} response argument")
        flag = tokens[0]
        if kind in ("compile", "link") and flag == "-o":
            if len(tokens) != 2 or not line.startswith("-o "):
                raise ValueError(f"Unsupported {kind} output syntax")
            matches(tokens[1], expected_output, "output", True)
            counts["output"] += 1
            continue
        if kind in ("compile", "shared"):
            # UBT emits exactly one combined line: -MD -MF"path". Standalone
            # -MF, attached -o, -MMD and other output forms are not supported.
            if flag == "-MD":
                if kind == "shared" or len(tokens) != 2 or not line.startswith('-MD -MF"') or not tokens[1].startswith("-MF"):
                    raise ValueError("Unsupported dependency-output syntax")
                matches(tokens[1][3:], dependency, "dependency output", True)
                counts["dependency"] += 1
                continue
            if flag in ("-include", "-include-pch", "-target", "-x"):
                if len(tokens) != 2 or not line.startswith(flag + " "):
                    raise ValueError("Unsupported compile argument syntax")
                if kind == "shared" and flag.startswith("-include"):
                    raise ValueError("Unexpected forced include in shared response")
                if flag == "-include":
                    counts["include"] += 1
                if flag == "-include-pch":
                    if not allow_pch:
                        raise ValueError("Binary PCH survived response transformation")
                    counts["pch"] += 1
                continue
            if tokens == ["-Xclang", "-fno-pch-timestamp"] and allow_pch:
                continue
            if len(tokens) == 1:
                if flag.startswith("@") and kind == "compile":
                    matches(flag[1:], shared_response, "shared response")
                    guard_response(shared_response.read_text().splitlines(), "shared", cwd, None)
                    counts["shared"] += 1
                    continue
                if flag in COMPILE_FLAGS or ("=" in flag and flag.split("=", 1)[0] in COMPILE_VALUES):
                    continue
                if flag.startswith(("-D", "-I", "-isystem")):
                    continue
                if flag.startswith("-W") and not flag.startswith(("-Wl,", "-Wp,", "-Wa,")):
                    continue
                if kind == "compile" and not flag.startswith(("-", "@")) and flag.endswith(".cpp"):
                    matches(flag, unity_source, "unity source")
                    counts["unitySource"] += 1
                    continue
        elif kind == "link":
            if flag == "-target" and len(tokens) == 2:
                continue
            if len(tokens) == 1:
                if flag.startswith("-Wl,@"):
                    matches(flag[len("-Wl,@"):], object_response, "object response")
                    counts["objectResponse"] += 1
                    continue
                if flag.startswith("-Wl,") and ld_option(flag[len("-Wl,"):]):
                    continue
                if flag in LINK_FLAGS or ("=" in flag and flag.split("=", 1)[0] in LINK_VALUES):
                    continue
                if flag.startswith(("-L", "-B", "-l")):
                    continue
                if not flag.startswith(("-", "@")) and flag.endswith(".a"):
                    continue
        elif kind == "objects" and len(tokens) == 1:
            if ld_option(flag) or flag.startswith("-L"):
                continue
            if not flag.startswith(("-", "@")) and flag.endswith(".cpp.o"):
                if not line.endswith('.cpp.o"'):
                    raise ValueError("Unsupported unity-object response syntax")
                matches(flag, expected_output, "unity object")
                counts["unityObject"] += 1
                continue
            if not flag.startswith(("-", "@")) and flag.endswith(".a"):
                continue
        raise ValueError(f"Unrecognized {kind} response argument; refusing native execution")
    if kind == "compile" and (counts["output"] != 1 or counts["dependency"] != 1
                              or counts["include"] != 1 or counts["unitySource"] != 1
                              or counts["pch"] != int(allow_pch) or counts["shared"] != 1):
        raise ValueError("Expected one compile output, dependency output, include and unity source")
    if kind == "link" and (counts["output"] != 1 or counts["objectResponse"] != 1):
        raise ValueError("Expected one link output and object response")
    if kind == "objects" and counts["unityObject"] != 1:
        raise ValueError("Expected exactly one native unity object")
    return counts


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def quoted(path):
    return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def execute(command, cwd, log, timeout):
    started = time.monotonic()
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(command, cwd=cwd, stdout=output,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); inspect {log}")
    return round(time.monotonic() - started, 3)


def readelf(path, option):
    result = subprocess.run(["readelf", "--wide", option, str(path)],
                            text=True, capture_output=True, check=True)
    return result.stdout


def resolve_quoted_argument(line, source_root):
    argument = shlex.split(line)[-1]
    path = Path(argument)
    return path if path.is_absolute() else (source_root / path).resolve()


def build_module(module, args, engine, work, compiler):
    source_root = engine / "Source"
    original = (engine / "Intermediate/Build/Linux/x64/UnrealEditor/Development"
                / module)
    output = work / module
    output.mkdir(parents=True, exist_ok=False)
    object_path = output / f"Module.{module}.cpp.o"
    destination = (work / "overrides/backend/Engine/Binaries/Linux"
                   / f"libUnrealEditor-{module}.so")
    destination.parent.mkdir(parents=True, exist_ok=True)

    compile_original = original / f"Module.{module}.cpp.o.rsp"
    linker_original = original / f"libUnrealEditor-{module}.so.link.rsp"
    objects_original = original / f"libUnrealEditor-{module}.so.rsp"
    compile_lines = compile_original.read_text().splitlines()
    linker_lines = linker_original.read_text().splitlines()
    original_object_lines = objects_original.read_text().splitlines()
    unity_source = original / f"Module.{module}.cpp"
    original_object = original / f"Module.{module}.cpp.o"
    shared_response = original / f"{module}.Shared.rsp"
    guard_response(compile_lines, "compile", source_root, original_object,
                   dependency=original / f"Module.{module}.cpp.d",
                   unity_source=unity_source, shared_response=shared_response, allow_pch=True)
    guard_response(linker_lines, "link", source_root,
                   engine / "Binaries/Linux" / destination.name, object_response=objects_original)
    guard_response(original_object_lines, "objects", source_root, original_object)
    pch = resolve_quoted_argument(next(line for line in compile_lines
                                      if line.startswith("-include-pch ")),
                                  source_root)
    pch_header = Path(str(pch).removesuffix(".gch"))
    definitions = original / f"Definitions.{module}.h"
    definition_text = definitions.read_text()
    shared_name = re.search(r'#include "([^"]+)"', definition_text).group(1)
    shared_definitions = pch_header.parent / shared_name
    if not shared_definitions.is_file():
        raise RuntimeError(f"Shared definitions missing for {module}")
    if not re.search(r"^#define WITH_CEF3 1$", shared_definitions.read_text(), re.M):
        raise RuntimeError(f"Expected WITH_CEF3=1 reference configuration for {module}")

    # Textually include the original PCH after changing CEF, preserving all other
    # original feature/API/ABI definitions. Never load a CEF-enabled binary PCH.
    force_include = output / "Definitions.NoCEF.h"
    write(force_include, "\n".join([
        "#pragma once", f"#include {quoted(shared_definitions)}",
        "#undef WITH_CEF3", "#define WITH_CEF3 0",
        f"#include {quoted(pch_header)}", f"#include {quoted(definitions)}",
        "#if WITH_CEF3", '#error "CEF must remain disabled"', "#endif", "",
    ]))
    transformed = []
    for line in compile_lines:
        if line.startswith("-include-pch ") or line in (
                "-Xclang -fno-pch-timestamp", "-fpch-validate-input-files-content"):
            continue
        if line.startswith("-include "):
            line = "-include " + quoted(force_include)
        elif line.startswith("-o "):
            line = "-o " + quoted(object_path)
        elif line.startswith("-MD "):
            line = "-MD -MF" + quoted(output / "dependencies.d")
        transformed.append(line)
    compile_rsp = output / "compile.rsp"
    guard_response(transformed, "compile", source_root, object_path,
                   dependency=output / "dependencies.d", unity_source=unity_source,
                   shared_response=shared_response, work=work)
    write(compile_rsp, "\n".join(transformed) + "\n")

    # Recreate linker input using the freshly compiled object. These removals
    # affect the link command only; no existing ELF is patched in place.
    object_lines = []
    for line in original_object_lines:
        if "/CEF3/" in line or "libcef_dll_wrapper" in line:
            continue
        if line.endswith('.cpp.o"'):
            line = quoted(object_path)
        object_lines.append(line)
    objects_rsp = output / "objects.rsp"
    guard_response(object_lines, "objects", source_root, object_path)
    write(objects_rsp, "\n".join(object_lines) + "\n")
    link_lines = []
    for line in linker_lines:
        if line in ("-lcef", "-lUnrealEditor-CEF3Utils"):
            continue
        if line.startswith("-o "):
            line = "-o " + quoted(destination)
        elif line.startswith("-Wl,@"):
            line = "-Wl,@" + quoted(objects_rsp)
        link_lines.append(line)
    link_rsp = output / "link.rsp"
    guard_response(link_lines, "link", source_root, destination, object_response=objects_rsp, work=work)
    write(link_rsp, "\n".join(link_lines) + "\n")
    print(f"{module}: compiling WITH_CEF3=0", flush=True)
    compile_seconds = execute([str(compiler), "@" + str(compile_rsp)], source_root,
                              output / "compile.log", args.timeout)
    print(f"{module}: linking", flush=True)
    link_seconds = execute([str(compiler), "@" + str(link_rsp)], source_root,
                           output / "link.log", args.timeout)
    dynamic = readelf(destination, "--dynamic")
    symbols = readelf(destination, "--dyn-syms")
    needed = re.findall(r"\(NEEDED\).*?\[(.*?)\]", dynamic)
    if any("cef" in name.lower() for name in needed):
        raise RuntimeError(f"CEF dependency survived in {module}: {needed}")
    undefined_cef = [line for line in symbols.splitlines()
                     if " UND " in line and re.search(r"\bcef_|CEF3Utils|Cef[A-Z]", line)]
    if undefined_cef:
        raise RuntimeError(f"Undefined CEF symbols survived in {module}")
    # UE 5.8 can register via a static FModuleInitializerEntry instead of an
    # exported InitializeModule function. Check the reference binary's scheme.
    original_symbols = readelf(engine / "Binaries/Linux" / destination.name,
                               "--dyn-syms")
    registration = ("FModuleInitializerEntry" if "FModuleInitializerEntry" in original_symbols
                    else "InitializeModule")
    if registration not in symbols:
        raise RuntimeError(f"UE module registration missing from {module}")
    soname = re.findall(r"\(SONAME\).*?\[(.*?)\]", dynamic)
    if soname != [destination.name]:
        raise RuntimeError(f"Unexpected SONAME for {module}: {soname}")
    inputs = [compile_original, linker_original, objects_original, shared_response, definitions,
              shared_definitions, pch_header, original / f"Module.{module}.cpp"]
    return {
        "module": module, "withCEF3": False,
        "output": str(destination.relative_to(work)),
        "bytes": destination.stat().st_size, "sha256": digest(destination),
        "soname": soname[0], "needed": needed, "undefinedCEFSymbols": [],
        "registrationMechanism": registration,
        "compileSeconds": compile_seconds, "linkSeconds": link_seconds,
        "referenceInputs": [{"path": str(path.relative_to(engine)),
                              "sha256": digest(path)} for path in inputs],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True,
                        help="Matching UE Engine directory with original UBT rsp files")
    parser.add_argument("--work", type=Path, required=True,
                        help="New isolated build directory outside Engine")
    parser.add_argument("--compiler", type=Path,
                        help="Matching clang++; default inferred from original sysroot")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This response-file rebuild helper currently supports Linux only")
    engine, work = args.engine.resolve(), args.work.resolve()
    if engine == work or engine in work.parents or work in engine.parents:
        parser.error("Engine and work paths must not contain one another")
    if work.exists():
        parser.error("Work directory must not already exist; preserve earlier evidence")
    if not (engine / "Source/Runtime/WebBrowser").is_dir():
        parser.error("Matching WebBrowser source is unavailable")
    reference_modules = engine / "Binaries/Linux/UnrealEditor.modules"
    reference_build_id = json.loads(reference_modules.read_text())["BuildId"]
    rsp = (engine / "Intermediate/Build/Linux/x64/UnrealEditor/Development/CEF3Utils"
           / "Module.CEF3Utils.cpp.o.rsp").read_text()
    sysroot = re.search(r'^--sysroot="([^"]+)"$', rsp, re.M).group(1)
    compiler = args.compiler or Path(sysroot) / "bin/clang++"
    if not compiler.is_file():
        parser.error("Cannot locate matching compiler; supply --compiler")
    work.mkdir(parents=True)
    started = time.monotonic()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(build_module, module, args, engine, work, compiler)
                       for module in MODULES]
            results = [future.result() for future in futures]
        if json.loads(reference_modules.read_text())["BuildId"] != reference_build_id:
            raise RuntimeError("Reference engine BuildId changed during this build")
        report = {
            "schema": "niagara-nocef-rebuild/1", "ok": True, "platform": "Linux",
            "ueModuleBuildId": reference_build_id,
            "method": "Native source compilation with WITH_CEF3=0, original ABI flags, textual PCH",
            "engineOutputsModified": False, "elfPatched": False,
            "packageModulesManifestAction": "Keep the matching original UnrealEditor.modules unchanged",
            "elfBuildIdNote": "The new ELF linker build IDs identify new binaries; these are distinct from UE module BuildId",
            "browserFunctionalityAvailable": False,
            "modules": results, "wallSeconds": round(time.monotonic() - started, 3),
        }
        write(work / "report.json", json.dumps(report, indent=2) + "\n")
        print(json.dumps({"ok": True, "modules": len(results),
                          "wallSeconds": report["wallSeconds"]}), flush=True)
    except Exception as error:
        write(work / "failure.json", json.dumps({"ok": False, "error": str(error)}, indent=2))
        raise


if __name__ == "__main__":
    main()
