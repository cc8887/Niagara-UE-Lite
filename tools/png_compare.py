"""Small dependency-free decoder for UE's noninterlaced 8-bit RGB/RGBA PNGs."""
import struct,zlib
from pathlib import Path


def decode(path):
    data=Path(path).read_bytes()
    if data[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Not PNG')
    at=8;compressed=[];header=None
    while at<len(data):
        size=struct.unpack_from('>I',data,at)[0];kind=data[at+4:at+8];chunk=data[at+8:at+8+size];at+=size+12
        if kind==b'IHDR':header=struct.unpack('>IIBBBBB',chunk)
        elif kind==b'IDAT':compressed.append(chunk)
        elif kind==b'IEND':break
    width,height,depth,color,compression,filtering,interlace=header
    if depth!=8 or color not in (2,6) or compression or filtering or interlace:raise ValueError('Unsupported PNG encoding')
    channels=3 if color==2 else 4;stride=width*channels;raw=zlib.decompress(b''.join(compressed));rows=[];last=bytearray(stride);offset=0
    for y in range(height):
        mode=raw[offset];row=bytearray(raw[offset+1:offset+1+stride]);offset+=stride+1
        if mode not in range(5):raise ValueError('Invalid PNG filter')
        if mode:
            for i,x in enumerate(row):
                left=row[i-channels] if i>=channels else 0;above=last[i];corner=last[i-channels] if i>=channels else 0
                if mode==1:predict=left
                elif mode==2:predict=above
                elif mode==3:predict=(left+above)//2
                else:
                    p=left+above-corner;dist=(abs(p-left),abs(p-above),abs(p-corner));predict=(left,above,corner)[dist.index(min(dist))]
                row[i]=(x+predict)&255
        rows.append(bytes(row));last=row
    return width,height,channels,b''.join(rows)


def difference(first,second):
    a,b=decode(first),decode(second)
    if a[:3]!=b[:3]:raise AssertionError('PNG dimensions/format differ')
    total=0;maximum=0;changed=0;pixels=set();channels=a[2]
    for i,(x,y) in enumerate(zip(a[3],b[3])):
        d=abs(x-y)
        if d:total+=d;maximum=max(maximum,d);changed+=1;pixels.add(i//channels)
    return {'changedPixels':len(pixels),'maxChannelDifference':maximum,'meanAbsoluteChannelDifference':total/len(a[3]),'channels':len(a[3]),'decodedPixelsIdentical':changed==0}
