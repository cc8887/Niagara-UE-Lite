"""Offline UE 5.8.1/5.9.0 fix for UnrealPak's Windows-only extraction separator."""
from pathlib import Path
import argparse
import json
import os


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    engine=Path(os.environ['NIAGARA_BUILD_ENGINE'])
    version=json.loads((engine/'Build/Build.version').read_text())
    if tuple(version[k] for k in ('MajorVersion','MinorVersion','PatchVersion')) not in ((5,8,1),(5,9,0)):
        raise SystemExit('Matching UE 5.8.1 or 5.9.0 required')
    source=engine/'Source/Developer/PakFileUtilities/Private/PakFileUtilities.cpp'
    old='FString PakFilename = PakFileDirectory + "\\\\" + PakFileList[PakFileIndex];'
    new='FString PakFilename = FPaths::Combine(PakFileDirectory, PakFileList[PakFileIndex]);'
    text=source.read_text()
    if text.count(new)==3 and old not in text:
        print(json.dumps({'ok':True,'applied':True,'changed':False}));return
    if text.count(old)!=3 or new in text:raise SystemExit('Unexpected PakFileUtilities source; no writes made')
    if not args.apply:raise SystemExit('Linux extraction separator patch required; use --apply offline and rebuild UnrealPak')
    source.write_text(text.replace(old,new))
    print(json.dumps({'ok':True,'applied':True,'changed':True}))


if __name__=='__main__':main()
