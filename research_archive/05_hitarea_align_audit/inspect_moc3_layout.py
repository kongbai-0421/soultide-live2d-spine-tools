import json
import math
import struct
from pathlib import Path
from PIL import Image, ImageDraw

out_dir = Path(r".\_scratch\hitbox_check")
out_dir.mkdir(parents=True, exist_ok=True)

print("=== 1. Decode exact Live2D .moc3 Keyform0 Positions ===", flush=True)
mb = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", mb, 64)
cnt_info = struct.unpack_from("<16I", mb, ptrs[0])
print("CountInfo[0..15]:", cnt_info)
# Compute section byte sizes
for i in range(32, 50):
    sz = ptrs[i + 1] - ptrs[i]
    print(f"sec[{i:2d}] off={ptrs[i]:7d} sz={sz:6d} (/4={sz//4:5d}) sample={struct.unpack_from('<4i', mb, ptrs[i])}")
for i in range(69, 80):
    sz = ptrs[i + 1] - ptrs[i]
    print(f"sec[{i:2d}] off={ptrs[i]:7d} sz={sz:6d} (/4={sz//4:5d}) sample_i={struct.unpack_from('<4i', mb, ptrs[i])} sample_f={tuple(round(x,2) for x in struct.unpack_from('<4f', mb, ptrs[i]))}")
