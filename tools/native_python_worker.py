"""Run an explicit authoring script against the bundled native UE Python API.

The caller's script receives `params` and `unreal`; set `result` to a JSON value.
This is the same native scripting surface as editor Python, not a particle DSL.
Scripts own their explicit save operations and native transaction boundaries.
"""
import json,os,sys,traceback
from pathlib import Path
import unreal

response=Path(os.environ['NIAGARA_ASSET_RESPONSE'])
try:
    request=json.loads(Path(os.environ['NIAGARA_ASSET_REQUEST']).read_text(encoding='utf-8-sig'))
    script=Path(request['file']).resolve()
    if not script.is_file() or script.suffix.lower()!='.py':raise ValueError('Expected an explicit Python source file')
    namespace={'__name__':'__main__','__file__':str(script),'unreal':unreal,'params':request.get('params',{})}
    sys.path.insert(0,str(script.parent))
    exec(compile(script.read_text(encoding='utf-8-sig'),str(script),'exec'),namespace)
    value=namespace.get('result')
    # Validate JSON serialization before writing a successful response.
    payload=json.dumps({'ok':True,'result':value},ensure_ascii=False,indent=2)
except Exception as exc:
    response.parent.mkdir(parents=True,exist_ok=True)
    response.write_text(json.dumps({'ok':False,'error':type(exc).__name__+': '+str(exc),'traceback':traceback.format_exc()},ensure_ascii=False,indent=2),encoding='utf-8')
    raise
response.parent.mkdir(parents=True,exist_ok=True);response.write_text(payload,encoding='utf-8')
