"""Create, Cook and render native GPU Sprite, Ribbon and Mesh samples in a kit."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess

EFFECTS = {
    'gpu': ('gpu-fountain.json', 'NiagaraSpriteRendererProperties', 'GPUComputeSim'),
    'ribbon': ('ribbon-beam.json', 'NiagaraRibbonRendererProperties', 'CPUSim'),
    'mesh': ('mesh-fountain.json', 'NiagaraMeshRendererProperties', 'CPUSim'),
}

def main():
    if not __debug__:
        raise RuntimeError('Acceptance checks require assertions; run without -O or PYTHONOPTIMIZE')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--cpu-vulkan', action='store_true')
    parser.add_argument('--effects', nargs='+', choices=EFFECTS, default=list(EFFECTS))
    parser.add_argument('--frames', nargs='+', type=int, default=[30, 60])
    parser.add_argument('--reuse-assets', action='store_true')
    parser.add_argument('--package', type=Path, help='Reuse an already Cooked package')
    args = parser.parse_args()
    root = args.root.resolve(); out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    launcher = root / ('niagara-cli.exe' if os.name == 'nt' else 'niagara-cli')
    prefix = [str(launcher), '--workspace', str(args.workspace.resolve()), '--timeout', '1800']
    report = {'ok': False, 'platform': 'Windows' if os.name == 'nt' else 'Linux',
              'cpuVulkanRequested': args.cpu_vulkan, 'cases': [], 'visualInspection': False}

    def run(name, *command):
        proc = subprocess.run(prefix + [str(x) for x in command], capture_output=True,
                              text=True, encoding='utf-8', errors='replace')
        (out / (name + '.cli.json')).write_text(proc.stdout, encoding='utf-8')
        (out / (name + '.stderr.log')).write_text(proc.stderr, encoding='utf-8')
        if proc.returncode:
            raise RuntimeError(name + ' failed with exit ' + str(proc.returncode))
        result = json.loads(proc.stdout)
        if not result.get('ok'): raise RuntimeError(name + ' did not succeed')
        return result

    assets = {effect: '/Game/RendererAcceptance/NS_' + effect.title() for effect in args.effects}
    try:
        for effect in args.effects:
            if not args.reuse_assets:
                run(effect + '-create', 'create', '--asset', assets[effect], '--recipe',
                    root / 'examples' / EFFECTS[effect][0])
            run(effect + '-reload', 'read', '--asset', assets[effect])
        package = args.package.resolve() if args.package else out / 'runtime'
        if not args.package:
            run('cook', 'cook', '--asset', assets[args.effects[0]], '--package', package)
        for effect in args.effects:
            for frame in args.frames:
                name = f'{effect}-{frame}'; image = out / (name + '.png')
                command = ['render', '--asset', assets[effect], '--package', package,
                           '--frames', str(frame), '--warmup', '16', '--width', '512',
                           '--height', '512', '--out', image]
                if args.cpu_vulkan: command.append('--cpu-vulkan')
                result = run(name, *command)
                assert result['runtimeExitCode'] == 0 and result['imageSaved']
                assert result['simFrames'] == frame and result['warmupFrames'] == 16
                assert abs(result['simulationAge'] - frame / 60.0) < 1.0 / 120.0
                assert result['rhi'] == ('D3D12' if os.name == 'nt' else 'Vulkan')
                assert abs(result['camera']['aspectRatio'] - result['width'] / result['height']) < 0.001
                assert abs(result['camera']['projectionHorizontalFov'] - 45.0) < 0.01
                assert result['systemReady'] and result['simulationValid'] and result['sceneProxyExists']
                assert result['captureReadiness']['phase'] == 'screenshot_captured'
                assert result['captureReadiness']['latest']['renderReady']
                assert not result['captureReadiness']['latest']['psoPending']
                assert result['captureReadiness']['warmupFramesRendered'] == 16
                assert result['maxRGB'] > 0 and result['nonZeroPixels'] > 0
                assert all(result[k] is False for k in ('withEditor', 'niagaraEditorLoaded', 'unrealEdLoaded'))
                assert result['particleCountExact'] and result['particleCount'] > 0
                emitters = result['emitters']
                assert emitters and all(e['simTarget'] == EFFECTS[effect][2] for e in emitters)
                if effect != 'gpu':
                    assert all(e['cpuPositions']['attributeValid'] and e['cpuPositions']['nonFiniteCount'] == 0
                               and e['cpuPositions']['finiteCount'] == e['particles'] for e in emitters)
                renderers = [r for e in emitters for r in e['renderers'] if r['enabled']]
                assert len(renderers) == 1 and renderers[0]['class'] == EFFECTS[effect][1]
                if effect == 'gpu':
                    assert result['containsGpuEmitters'] and result['gpuReadbackAfterScreenshot']
                    assert result['gpuReadbackCompleted'] and result['gpuParticleCount'] > 0
                    assert all(e['gpuContextExists'] and e['particleCountSource'] ==
                               'gpu_buffer_readback_after_screenshot' for e in emitters)
                report['cases'].append({'effect': effect, 'frame': frame, 'ok': True,
                                        'image': image.name, 'sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                                        'metadata': result})
        for effect in ('gpu', 'mesh'):
            samples = [c for c in report['cases'] if c['effect'] == effect]
            if len({c['frame'] for c in samples}) > 1:
                assert len({c['sha256'] for c in samples}) > 1, effect + ' did not change across simulation times'
        report['ok'] = True
    except (OSError, RuntimeError, AssertionError, KeyError, ValueError) as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
