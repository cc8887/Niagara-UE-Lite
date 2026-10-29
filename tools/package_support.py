"""Portable binary-copy helpers adapted from Material-UE-Lite standalone packaging."""
from pathlib import Path
SOURCE_PREFIXES=[]
SKIP={".debug",".sym",".pdb",".pyc",".target"}

def clean_vfs(data):
    for encoding,width in (('utf-8',1),('utf-16le',2),('utf-32le',4)):
        for marker in ('/UEVFS/Root;', 'Z:\\UEVFS\\Root;', 'Z:\\UEVFS\\LinuxSDK;'):
            offset = 0
            while True:
                start = data.find(marker.encode(encoding), offset)
                if start<0:break
                end=next((i for i in range(start,min(len(data),start+65536),width)
                          if data[i:i+width]==b'\0'*width),-1)
                if end<0:raise ValueError('Unterminated UE virtual source path')
                mapping=data[start:end];parts=mapping.split(';'.encode(encoding))
                if parts[-1]!=b'' or len(parts)%2!=1:
                    offset=end
                    continue
                for i in range(1,len(parts)-1,2):
                    parts[i]=('/'+'_'*(len(parts[i])//width-1)).encode(encoding)
                replacement=';'.encode(encoding).join(parts)
                assert len(replacement)==len(mapping)
                data=data[:start]+replacement+data[end:];offset=end
    return data


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    if data.startswith(b'\x7fELF') or data.startswith(b'MZ'):
        data = clean_vfs(data)
        # Absolute __FILE__ constants from the private game module are only
        # diagnostics. Preserve their byte lengths in the distributable.
        for prefix in SOURCE_PREFIXES:
            for encoding in ('utf-8','utf-16le','utf-32le'):
                old=prefix.encode(encoding)
                replacement=('/'+'_'*(len(prefix)-1)).encode(encoding)
                assert len(old)==len(replacement)
                data=data.replace(old,replacement)
    destination.write_bytes(data)
    destination.chmod(0o755 if source.stat().st_mode&0o111 else 0o644)


def tree(source, destination):
    for p in sorted(source.rglob('*')):
        if not p.is_file():continue
        rel = p.relative_to(source)
        if p.suffix in SKIP or any(x in rel.parts for x in ('Intermediate','Saved','Source','__pycache__','include')):continue
        if p.name.endswith('.a') or any(x.startswith('config-3.') for x in rel.parts):continue
        copy(p,destination/rel)
