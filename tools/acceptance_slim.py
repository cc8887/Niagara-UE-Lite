"""Verify a standalone kit through native edit/save/reload, Cook and rendered evidence."""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import re
import struct
import subprocess


EFFECTS = {
    'gpu': {'recipe': 'gpu-fountain.json', 'emitter': 'GPUFountain',
            'renderer': 'NiagaraSpriteRendererProperties', 'target': 'GPUComputeSim',
            'script': 'EmitterUpdateScript', 'module': 'SpawnRate', 'input': 'SpawnRate',
            'original': 240.0, 'changed': 300.0},
    'ribbon': {'recipe': 'ribbon-beam.json', 'emitter': 'RibbonBeam',
               'renderer': 'NiagaraRibbonRendererProperties', 'target': 'CPUSim',
               'script': 'ParticleSpawnScript', 'module': 'BeamWidth', 'input': 'Beam Width',
               'original': 12.0, 'changed': 18.0},
    'mesh': {'recipe': 'mesh-fountain.json', 'emitter': 'MeshFountain',
             'renderer': 'NiagaraMeshRendererProperties', 'target': 'CPUSim',
             'script': 'EmitterUpdateScript', 'module': 'SpawnRate', 'input': 'SpawnRate',
             'original': 40.0, 'changed': 55.0},
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def scalar_input(result, spec):
    """Read the exact native emitter/module/input and verify its reflected type."""
    emitters = [e for e in result['snapshot']['emitters']
                if e['topology']['emitterName'] == spec['emitter']]
    require(len(emitters) == 1, 'Expected exactly one matching native emitter')
    values = [i['value'] for m in emitters[0]['moduleInputs']
              if m['moduleName'] == spec['module'] for i in m['inputs']
              if i['name'] == spec['input']]
    require(len(values) == 1, 'Expected exactly one matching native input')
    value = values[0]
    require(value['isSet'] and value['type'] == '/Script/Niagara.NiagaraFloat',
            'Expected an authored native NiagaraFloat input')
    number = value['data']['value']
    require(type(number) in (int, float) and math.isfinite(number), 'Native input must be finite')
    return float(number)


def input_recipe(spec, value):
    return {'schema': 'ue-niagara-recipe/1', 'operations': [{
        'op': 'input', 'emitter': spec['emitter'], 'script': spec['script'],
        'module': spec['module'], 'input': spec['input'], 'type': 'float', 'value': value}]}


def check_render(result, spec, frame, image):
    require(result['runtimeExitCode'] == 0 and result['imageSaved'], 'Native image process failed')
    require(result['simFrames'] == frame and result['warmupFrames'] == 16, 'Wrong capture frame')
    require(abs(result['simulationAge'] - frame / 60.0) < 1.0 / 120.0, 'Wrong actual simulation age')
    require(result['rhi'] == ('D3D12' if os.name == 'nt' else 'Vulkan'), 'Wrong native RHI')
    require(result['width'] == result['height'] == 512, 'Wrong image size')
    require(abs(result['camera']['aspectRatio'] - 1.0) < 0.001, 'Wrong camera aspect')
    require(abs(result['camera']['projectionHorizontalFov'] - 45.0) < 0.01, 'Wrong actual camera FOV')
    require(result['systemReady'] and result['simulationValid'] and result['sceneProxyExists'],
            'Native system or renderer was not ready')
    ready = result['captureReadiness']
    require(ready['phase'] == 'screenshot_captured' and ready['latest']['renderReady']
            and not ready['latest']['psoPending'] and ready['warmupFramesRendered'] == 16,
            'Capture did not satisfy native component readiness')
    require(result['maxRGB'] > 0 and result['nonZeroPixels'] > 0, 'Black image')
    require(all(result[k] is False for k in ('withEditor', 'niagaraEditorLoaded', 'unrealEdLoaded')),
            'Preview loaded editor modules')
    require(result['particleCountExact'] and result['particleCount'] > 0, 'No exact live particle count')
    emitters = result['emitters']
    require(len(emitters) == 1 and emitters[0]['name'] == spec['emitter'], 'Unexpected runtime emitter')
    require(emitters[0]['simTarget'] == spec['target'], 'Wrong native simulation target')
    renderers = [r for e in emitters for r in e['renderers'] if r['enabled']]
    require(len(renderers) == 1 and renderers[0]['class'] == spec['renderer'], 'Wrong native renderer')
    if spec['target'] == 'GPUComputeSim':
        require(result['containsGpuEmitters'] and result['gpuReadbackAfterScreenshot']
                and result['gpuReadbackCompleted'] and result['gpuParticleCount'] > 0,
                'GPU simulation lacks completed post-screenshot readback')
        require(emitters[0]['gpuContextExists'] and emitters[0]['particleCountSource'] ==
                'gpu_buffer_readback_after_screenshot', 'GPU count lacks native readback provenance')
    else:
        positions = emitters[0]['cpuPositions']
        require(positions['attributeValid'] and positions['nonFiniteCount'] == 0
                and positions['finiteCount'] == emitters[0]['particles'], 'Invalid native CPU positions')
    data = image.read_bytes()
    require(data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24
            and struct.unpack('>II', data[16:24]) == (512, 512), 'Missing or invalid native PNG')
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path, help='Extracted standalone kit')
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path, help='New evidence directory')
    parser.add_argument('--cpu-vulkan', action='store_true')
    parser.add_argument('--reuse-assets', action='store_true', help='Skip create; still edit/save/reload and Cook')
    parser.add_argument('--effects', nargs='+', choices=EFFECTS, default=list(EFFECTS))
    parser.add_argument('--frames', nargs='+', type=int, default=[30, 60])
    parser.add_argument('--timeout', type=int, default=1800, help='Native CLI timeout per operation')
    args = parser.parse_args()
    if not 1 <= args.timeout <= 7200 or any(not 1 <= frame <= 36000 for frame in args.frames):
        parser.error('timeout must be 1..7200 and frames must be 1..36000')
    if len(set(args.effects)) != len(args.effects) or len(set(args.frames)) != len(args.frames):
        parser.error('effects and frames must not contain duplicates')
    if args.cpu_vulkan and os.name == 'nt':
        parser.error('--cpu-vulkan requires Linux')
    root = args.root.resolve(); workspace = args.workspace.resolve(); out = args.out.resolve()
    launcher = root / ('niagara-cli.exe' if os.name == 'nt' else 'niagara-cli')
    require(launcher.is_file(), 'Standalone launcher is missing')
    require(out != workspace and workspace not in out.parents and out not in workspace.parents,
            'Evidence and workspace must be separate directories')
    out.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'niagara-slim-acceptance/1', 'ok': False, 'completed': False,
              'platform': 'Windows' if os.name == 'nt' else 'Linux',
              'cpuVulkanRequested': args.cpu_vulkan, 'creationExecuted': not args.reuse_assets,
              'cookExecuted': False, 'publicLauncherUsed': True, 'environmentOverridesRemoved': True,
              'authoring': [], 'processes': [], 'renders': [], 'visualInspection': False}
    replacements = [(str(out), 'evidence'), (str(workspace), 'workspace'), (str(root), 'kit')]
    for key in ('USERPROFILE', 'HOME', 'TEMP', 'TMP'):
        if os.environ.get(key):
            replacements.append((str(Path(os.environ[key]).resolve()), 'host-' + key.lower()))
    variants = {}
    for source, label in replacements:
        for spelling in (source, source.replace('\\', '/'), source.replace('/', '\\')):
            variants[spelling] = label
            variants[spelling.replace('\\', '\\\\')] = label
    substitutions = sorted(variants.items(), key=lambda item: len(item[0]), reverse=True)

    def safe(value):
        if isinstance(value, dict):
            return {key: safe(item) for key, item in value.items()}
        if isinstance(value, list):
            return [safe(item) for item in value]
        if isinstance(value, str):
            for source, replacement in substitutions:
                value = value.replace(source, replacement)
            value = re.sub(r'(?<![\w])[A-Za-z]:[\\/][^\s\"\'<>]+', '<external-path>', value)
            return re.sub(r'/(?:home|Users|workspace|opt|mnt)/[^\s\"\'<>]+', '<external-path>', value)
        return value

    def write(name, value):
        (out / name).write_text(json.dumps(safe(value), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    env = os.environ.copy()
    for key in ('NIAGARA_LITE_ENGINE', 'NIAGARA_LITE_PROJECT', 'NIAGARA_LITE_RUNTIME_TEMPLATE'):
        env.pop(key, None)
    prefix = [str(launcher), '--workspace', str(workspace), '--timeout', str(args.timeout)]

    def run(name, *command):
        proc = subprocess.run(prefix + [str(part) for part in command], env=env,
                              capture_output=True, text=True, encoding='utf-8', errors='replace',
                              timeout=args.timeout * 12 + 120)
        (out / (name + '.stderr.log')).write_text(safe(proc.stderr), encoding='utf-8')
        try:
            result = json.loads(proc.stdout)
        except ValueError:
            (out / (name + '.stdout.log')).write_text(safe(proc.stdout), encoding='utf-8')
            raise RuntimeError(name + ': launcher did not produce JSON') from None
        require(isinstance(result, dict), name + ': launcher JSON must be an object')
        write(name + '.cli.json', result)
        report['processes'].append({'name': name, 'exitCode': proc.returncode,
                                    'ok': result.get('ok') is True, 'result': name + '.cli.json'})
        require(proc.returncode == 0 and result.get('ok') is True, name + ': native operation failed')
        return result

    def check_value(result, spec, expected):
        actual = scalar_input(result, spec)
        require(abs(actual - expected) < 0.0001, 'Native input value did not match expected edit')
        return actual

    assets = {effect: '/Game/RendererAcceptance/NS_' + effect.title() for effect in args.effects}
    try:
        for effect in args.effects:
            spec = EFFECTS[effect]; asset = assets[effect]
            case = {'effect': effect, 'asset': asset, 'ok': False, 'restored': False,
                    'createdThisRun': not args.reuse_assets, 'module': spec['module'], 'input': spec['input']}
            report['authoring'].append(case)
            if not args.reuse_assets:
                created = run(effect + '-create', 'create', '--asset', asset, '--recipe', root / 'examples' / spec['recipe'])
                require(created.get('saved') is True, 'Created asset was not saved')
            baseline = run(effect + '-baseline', 'read', '--asset', asset)
            case['originalValue'] = check_value(baseline, spec, spec['original'])
            asset_file = workspace / 'Content' / Path(asset.removeprefix('/Game/')).with_suffix('.uasset')
            baseline_hash = hashlib.sha256(asset_file.read_bytes()).hexdigest()
            edit_file = effect + '-edit.recipe.json'; restore_file = effect + '-restore.recipe.json'
            write(edit_file, input_recipe(spec, spec['changed']))
            write(restore_file, input_recipe(spec, spec['original']))
            edit_error = None
            try:
                edited = run(effect + '-edit', 'edit', '--asset', asset, '--recipe', out / edit_file)
                require(edited.get('saved') is True and bool(edited.get('backup')), 'Edit did not save a backed-up native package')
                case['editedValue'] = check_value(edited, spec, spec['changed'])
                require(hashlib.sha256(asset_file.read_bytes()).hexdigest() != baseline_hash,
                        'Editing the input did not change native package bytes')
                saved = run(effect + '-save', 'save', '--asset', asset)
                require(saved.get('saved') is True, 'Explicit native save failed')
                case['savedValue'] = check_value(saved, spec, spec['changed'])
                reloaded = run(effect + '-reload-edited', 'read', '--asset', asset)
                case['reloadedValue'] = check_value(reloaded, spec, spec['changed'])
                case['crossProcessSaveReload'] = True
            except (OSError, RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as exc:
                edit_error = exc
            try:
                restored = run(effect + '-restore', 'edit', '--asset', asset, '--recipe', out / restore_file)
                check_value(restored, spec, spec['original'])
                saved = run(effect + '-save-restored', 'save', '--asset', asset)
                require(saved.get('saved') is True, 'Explicit restore save failed')
                final = run(effect + '-reload-restored', 'read', '--asset', asset)
                case['restoredValue'] = check_value(final, spec, spec['original'])
                case['restored'] = True
            except (OSError, RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as exc:
                if edit_error:
                    case['editError'] = safe(str(edit_error))
                raise RuntimeError(effect + ': restoring the original input failed') from exc
            if edit_error:
                raise edit_error
            case['ok'] = True
        package = out / 'runtime'
        cooked = run('cook', 'cook', '--asset', assets[args.effects[0]], '--package', package)
        require(cooked['payloadBytes'] > 0 and (package / 'package-manifest.json').is_file(), 'Cook produced no package')
        report['cookExecuted'] = True; report['runtimePackage'] = 'runtime'
        for effect in args.effects:
            for frame in args.frames:
                name = f'{effect}-{frame}'; image = out / (name + '.png')
                command = ['render', '--asset', assets[effect], '--package', package,
                           '--frames', str(frame), '--warmup', '16', '--width', '512', '--height', '512', '--out', image]
                if args.cpu_vulkan:
                    command.append('--cpu-vulkan')
                result = run(name, *command)
                digest = check_render(result, EFFECTS[effect], frame, image)
                write(image.name + '.json', result)
                report['renders'].append({'effect': effect, 'frame': frame, 'ok': True, 'image': image.name,
                                          'metadata': image.name + '.json', 'sha256': digest})
        for effect in ('gpu', 'mesh'):
            samples = [sample for sample in report['renders'] if sample['effect'] == effect]
            if len(samples) > 1:
                require(len({sample['sha256'] for sample in samples}) > 1, effect + ': image did not change with simulation time')
        report['ok'] = True
    except (OSError, RuntimeError, KeyError, ValueError, subprocess.TimeoutExpired) as exc:
        report['error'] = safe(type(exc).__name__ + ': ' + str(exc))
    finally:
        # UE writes runtime logs/metadata beside each PNG. Sanitize those text
        # artifacts only; preserve native PNG bytes and the cooked package.
        for path in out.iterdir():
            try:
                if path.name.endswith('.runtime.log'):
                    path.write_text(safe(path.read_text(encoding='utf-8-sig', errors='replace')), encoding='utf-8')
                elif path.name.endswith('.png.json'):
                    write(path.name, json.loads(path.read_text(encoding='utf-8-sig')))
            except (OSError, ValueError):
                report['ok'] = False; report['error'] = 'Could not sanitize runtime artifact: ' + path.name
        report['completed'] = True
        write('report.json', report)
    print(json.dumps(safe(report), indent=2, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
