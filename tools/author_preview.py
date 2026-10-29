"""Offline map creation using native UE; runs in the bundled editor backend."""
import unreal as ue

path='/Game/NiagaraPreview/Preview'
if not ue.EditorAssetLibrary.does_asset_exist(path):
    level=ue.get_editor_subsystem(ue.LevelEditorSubsystem)
    if not level.new_level(path):
        raise RuntimeError('Unable to create preview map')
    if not level.save_current_level():
        raise RuntimeError('Unable to save preview map')
ue.log('NIAGARA_PREVIEW_MAP_READY')
