"""Collect portable on-disk package dependency evidence inside the bundled UE backend.

Run with UnrealEditor-Cmd -run=pythonscript -script=<this-file>. Supply a JSON
request and output via NIAGARA_DEPENDENCY_REQUEST/NIAGARA_DEPENDENCY_RESPONSE;
NIAGARA_ASSET_REQUEST/NIAGARA_ASSET_RESPONSE are compatible aliases. A request
may contain extra_roots with package, object or content-folder paths.
This worker inventories assets; it never deletes or saves a native package.
"""
from collections import defaultdict, deque
import hashlib
import json
import os
from pathlib import Path
import re
import unreal as ue


PACKAGE_SUFFIXES = {'.uasset', '.umap'}
SIDECAR_SUFFIXES = ('.uexp', '.ubulk', '.uptnl', '.m.ubulk')
CANDIDATE_FOLDERS = ('VREditor', 'Tutorial', 'FbxEditorAutomation', 'MapTemplates', 'StarterContent')
NATIVE_ROOTS = (
    ('/Engine/VREditor/ViewportInteractionAssetContainerData', True,
     'Source/Editor/ViewportInteraction/Private/ViewportWorldInteraction.cpp', (104, 3173, 3174)),
    ('/Engine/VREditor/VREditorAssetContainerData', False,
     'Source/Editor/VREditor/Private/VREditorMode.cpp', (87,)),
    ('/Engine/VREditor/TransformGizmo/PlaneTranslationHandle', False,
     'Source/Editor/ViewportInteraction/Private/Gizmo/VIStretchGizmoHandle.cpp', (20,)),
    ('/Engine/VREditor/TransformGizmo/BoundingBoxCorner', False,
     'Source/Editor/ViewportInteraction/Private/Gizmo/VIStretchGizmoHandle.cpp', (27,)),
    ('/Engine/VREditor/TransformGizmo/BoundingBoxEdge', False,
     'Source/Editor/ViewportInteraction/Private/Gizmo/VIStretchGizmoHandle.cpp', (34,)),
    ('/Engine/VREditor/TransformGizmo/SM_Sequencer_Node', False,
     'Source/Editor/ComponentVisualizers/Private/Manipulator.cpp', (26,)),
    ('/Engine/VREditor/TransformGizmo/Main', False,
     'Source/Editor/ComponentVisualizers/Private/Manipulator.cpp', (30,)),
    ('/Engine/MapTemplates/Sky/SunsetAmbientCubemap', False,
     'Source/Editor/AdvancedPreviewScene/Private/AdvancedPreviewScene.cpp', (79,)),
    ('/Engine/MapTemplates/Sky/DaylightAmbientCubemap', False,
     'Source/Editor/UnrealEd/Private/ThumbnailManager.cpp', (58,)),
)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def physical_path(value):
    return Path(ue.Paths.convert_relative_path_to_full(str(value))).resolve()


def package_root(value):
    require(isinstance(value, str) and value.startswith('/') and '\\' not in value,
            'Extra roots must be native package, object or content-folder paths')
    value = value.rstrip('/').split('.', 1)[0]
    require(value and all(part not in ('', '.', '..') for part in value[1:].split('/'))
            and ':' not in value and "'" not in value and '"' not in value,
            'Invalid native extra root')
    return value


def dependency_options(hard):
    options = ue.AssetRegistryDependencyOptions()
    for key, value in {
        'include_hard_package_references': hard,
        'include_soft_package_references': not hard,
        'include_game_package_references': True,
        'include_editor_only_package_references': True,
        'include_searchable_names': False,
        'include_hard_management_references': False,
        'include_soft_management_references': False,
    }.items():
        options.set_editor_property(key, value)
    return options


def execute(request):
    require(isinstance(request, dict), 'Inventory request must be a JSON object')
    extras = request.get('extra_roots', [])
    require(isinstance(extras, list), 'extra_roots must be an array')
    extras = sorted(set(package_root(value) for value in extras))
    engine = physical_path(ue.Paths.engine_dir())
    source_manifest = engine.parents[1] / 'package-manifest.json'
    manifest_exists = source_manifest.is_file()
    manifest_data = source_manifest.read_bytes() if manifest_exists else None
    manifest = json.loads(manifest_data.decode('utf-8-sig')) if manifest_exists else {}
    project_content = physical_path(ue.Paths.project_content_dir())
    engine_content = physical_path(ue.Paths.engine_content_dir())
    plugins = physical_path(ue.Paths.engine_plugins_dir())
    mounts = {'/Game': (project_content, 'Project/Content'),
              '/Engine': (engine_content, 'backend/Engine/Content')}
    for descriptor in sorted(plugins.rglob('*.uplugin')):
        content = descriptor.parent / 'Content'
        if not content.is_dir():
            continue
        name = '/' + descriptor.stem
        require(name not in mounts, 'Duplicate native content mount')
        require(content.resolve().is_relative_to(engine), 'Plugin content escapes the packaged engine')
        mounts[name] = (content.resolve(), 'backend/Engine/' + content.relative_to(engine).as_posix())
    require('/Niagara' in mounts, 'Bundled Niagara content mount is missing')

    # Enumerating on-disk packages independently prevents an incomplete registry
    # scan from silently dropping Project or Niagara roots.
    package_files = {}; non_package_counts = {}
    for mount, (folder, portable) in sorted(mounts.items()):
        require(folder.is_dir(), 'Required native content directory is missing')
        other_count = 0
        for file in sorted(folder.rglob('*')):
            if not file.is_file():
                continue
            require(file.resolve().is_relative_to(folder), 'Content file escapes its mount')
            if file.suffix.lower() not in PACKAGE_SUFFIXES:
                other_count += 1
                continue
            relative = file.relative_to(folder)
            package = mount + '/' + relative.with_suffix('').as_posix()
            require(package not in package_files, 'Ambiguous native package filename')
            members = [{'path': portable + '/' + relative.as_posix(), 'bytes': file.stat().st_size}]
            for suffix in SIDECAR_SUFFIXES:
                sidecar = file.with_suffix(suffix)
                if sidecar.is_file():
                    require(sidecar.resolve().is_relative_to(folder), 'Package sidecar escapes its mount')
                    members.append({'path': portable + '/' + sidecar.relative_to(folder).as_posix(),
                                    'bytes': sidecar.stat().st_size})
            package_files[package] = members
        non_package_counts[mount] = other_count

    registry = ue.AssetRegistryHelpers.get_asset_registry()
    registry.search_all_assets(True)
    registry.scan_paths_synchronous(['/Game', '/Niagara', '/Engine'], True, True)
    assets = defaultdict(list)
    for data in registry.get_all_assets(True):
        package = str(data.package_name)
        full_name = ue.AssetRegistryHelpers.get_full_name(data)
        class_name, object_path = full_name.split(' ', 1)
        assets[package].append({'objectPath': object_path, 'class': class_name})
    roots = {package for package in package_files
             if package.startswith('/Game/') or package.startswith('/Niagara/')}
    require(any(package.startswith('/Niagara/') for package in roots), 'No Niagara root packages found')
    native_roots = []
    for package, mandatory, source, lines in NATIVE_ROOTS:
        present = package in package_files
        native_roots.append({'package': package, 'mandatory': mandatory,
                             'existsInBundledContent': present, 'includedAsRoot': present,
                             'provenance': {'kind': 'Native C++ hardcoded asset load',
                                            'source': source, 'lines': list(lines)}})
        require(present or not mandatory, 'Mandatory native startup asset is missing: ' + package)
        if present:
            roots.add(package)
    extra_matches = []
    for extra in extras:
        matches = sorted(package for package in package_files
                         if package == extra or package.startswith(extra + '/'))
        require(matches, 'Extra root does not resolve to a bundled package or content folder: ' + extra)
        roots.update(matches)
        extra_matches.append({'root': extra, 'packages': matches})
    unregistered_roots = sorted(roots.difference(assets))
    require(not unregistered_roots, 'Registry did not enumerate all on-disk root packages: ' +
            ', '.join(unregistered_roots[:12]))

    queue = deque(sorted(roots)); visited = set(); edges = []; native = set(); missing = []
    hard = dependency_options(True); soft = dependency_options(False)
    while queue:
        package = queue.popleft()
        if package in visited:
            continue
        visited.add(package)
        if package.startswith('/Script/'):
            native.add(package)
            continue
        if package not in assets:
            reason = 'existing_file_not_in_registry' if package in package_files else 'no_bundled_package_or_registry_entry'
            missing.append({'package': package, 'reason': reason})
            continue
        for kind, options in (('hard', hard), ('soft', soft)):
            dependencies = registry.get_dependencies(package, options)
            require(dependencies is not None, 'AssetRegistry failed to query a registered package: ' + package)
            for dependency in sorted(set(str(value) for value in dependencies)):
                require(dependency.startswith('/'), 'AssetRegistry returned a non-package dependency')
                edges.append({'from': package, 'to': dependency, 'kind': kind})
                if dependency not in visited:
                    queue.append(dependency)
    missing_existing = [item for item in missing if item['reason'] == 'existing_file_not_in_registry']
    require(not missing_existing, 'An existing dependency package could not be scanned by AssetRegistry')

    records = []
    registry_only = []
    for package in sorted(visited - native):
        files = package_files.get(package, [])
        if package in assets and not files:
            registry_only.append(package)
        records.append({'package': package, 'root': package in roots,
                        'assets': sorted(assets.get(package, []), key=lambda item: item['objectPath']),
                        'files': files})
    candidate_evidence = []
    for folder in CANDIDATE_FOLDERS:
        prefix = '/Engine/' + folder + '/'
        all_packages = sorted(package for package in package_files if package.startswith(prefix))
        candidate_evidence.append({'folder': '/Engine/' + folder,
                                   'onDiskPackages': len(all_packages),
                                   'referencedPackages': [p for p in all_packages if p in visited],
                                   'unreferencedPackages': [p for p in all_packages if p not in visited]})
    return {
        'schema': 'niagara-asset-dependency-inventory/1', 'ok': True,
        'sourceManifestStatus': 'present' if manifest_exists else 'missing',
        'sourceManifestSha256': hashlib.sha256(manifest_data).hexdigest() if manifest_exists else None,
        'sourcePlatform': manifest.get('platform'),
        'engineVersion': ue.SystemLibrary.get_engine_version(),
        'method': 'Native AssetRegistry on-disk hard and soft package dependency traversal',
        'packages': sorted(visited), 'rootPackages': sorted(roots),
        'requiredRootMounts': ['/Game', '/Niagara'], 'extraRoots': extra_matches,
        'nativeRootPolicyVersion': 1, 'nativeRoots': native_roots,
        'mandatoryNativeRootCoverageComplete': True,
        'missingNativeRoots': [item['package'] for item in native_roots if not item['existsInBundledContent']],
        'records': records, 'edges': sorted(edges, key=lambda edge: (edge['from'], edge['kind'], edge['to'])),
        'nativeScriptPackages': sorted(native), 'missingDependencies': sorted(missing, key=lambda item: item['package']),
        'registryPackagesWithoutBundledFileMapping': registry_only,
        'registeredRootCoverageComplete': True, 'existingDependencyRegistryCoverageComplete': True,
        'allReferencedFilesMapped': not missing and not registry_only and
                                    all(item['existsInBundledContent'] for item in native_roots),
        'mounts': [{'packageRoot': name, 'contentRoot': value[1]} for name, value in sorted(mounts.items())],
        'counts': {'roots': len(roots), 'closurePackages': len(visited), 'edges': len(edges),
                   'hardEdges': sum(edge['kind'] == 'hard' for edge in edges),
                   'softEdges': sum(edge['kind'] == 'soft' for edge in edges),
                   'mappedFiles': sum(len(item['files']) for item in records),
                   'missingDependencies': len(missing), 'registryOnlyPackages': len(registry_only),
                   'nativeRoots': len(native_roots),
                   'presentNativeRoots': sum(item['existsInBundledContent'] for item in native_roots)},
        'conservativeCandidateEvidence': candidate_evidence,
        'retentionPolicy': {
            'preserveAllProjectContent': True, 'preserveAllNiagaraContent': True,
            'preserveReferencedEnginePackagesAndSidecars': True,
            'removalCandidates': ['/Engine/' + folder for folder in CANDIDATE_FOLDERS],
            'candidateCondition': 'Only existing .uasset/.umap packages absent from this recorded closure; no deletion by this worker',
            'preserveOtherEngineContent': True,
            'preserveNonPackageResources': ['Slate', 'Internationalization', 'ICU', 'Fonts', 'Config', 'Shaders', 'native binaries and libraries'],
            'nonPackageResourcesRequireExplicitFileRules': True,
            'nonPackageFileCountsByMount': non_package_counts,
        },
        'limitations': [
            'This is the closure recorded in the on-disk AssetRegistry, including editor-only package references.',
            'The explicitly listed native C++ asset loads are added as roots with source provenance and traversed recursively.',
            'Other native string loads, configuration loads and computed runtime asset paths are not proven by this graph.',
            'All Project and Niagara content is retained; other Engine content outside the named conservative candidates is retained.',
            'Arbitrary future assets may need additional Engine content. Supply extra_roots before curation or an expanded resource pack.',
            'Script packages are native-module dependencies, not removable content files. Missing packages remain explicit evidence.',
        ],
    }


def portable_error(error):
    text = str(error)
    text = re.sub(r'(?<![A-Za-z0-9_])[A-Za-z]:[\\/][^\s\"\'<>]+', '<host-path>', text)
    return re.sub(r'/(?:home|Users|workspace|opt|mnt|tmp|var)/[^\s\"\'<>]+', '<host-path>', text)


def main():
    output = os.environ.get('NIAGARA_DEPENDENCY_RESPONSE') or os.environ.get('NIAGARA_ASSET_RESPONSE')
    require(output, 'Set NIAGARA_DEPENDENCY_RESPONSE or NIAGARA_ASSET_RESPONSE')
    try:
        request_file = os.environ.get('NIAGARA_DEPENDENCY_REQUEST') or os.environ.get('NIAGARA_ASSET_REQUEST')
        request = json.loads(Path(request_file).read_text(encoding='utf-8-sig')) if request_file else {}
        result = execute(request)
    except Exception as exc:
        result = {'schema': 'niagara-asset-dependency-inventory/1', 'ok': False,
                  'errorType': type(exc).__name__, 'error': portable_error(exc)}
    response = Path(output); response.parent.mkdir(parents=True, exist_ok=True)
    response.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if not result['ok']:
        raise RuntimeError(result['error'])
    ue.log('NIAGARA_DEPENDENCY_INVENTORY_READY ' + json.dumps(result['counts']))


if __name__ == '__main__':
    main()
