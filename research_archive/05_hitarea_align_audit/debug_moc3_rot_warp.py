import math
import struct
from pathlib import Path
from PIL import Image, ImageDraw

out_dir = Path(r".\_scratch\hitbox_check")
mb = Path(r"E:\A灵魂潮汐\live2d\欧若拉\童话心绘\Aurora.moc3").read_bytes()
ptrs = struct.unpack_from("<100I", mb, 64)
cnt_info = struct.unpack_from("<16I", mb, ptrs[0])
n_def, n_warp, n_rot, n_draw = cnt_info[1], cnt_info[2], cnt_info[3], cnt_info[4]
n_art_kf, n_pos_f, n_uv_f = cnt_info[9], cnt_info[10], cnt_info[15]

def_types = struct.unpack_from(f"<{n_def}i", mb, ptrs[17])
def_spec_idx = struct.unpack_from(f"<{n_def}i", mb, ptrs[18])
def_parents = struct.unpack_from(f"<{n_def}i", mb, ptrs[16])

rot_kf_beg = struct.unpack_from(f"<{n_rot}i", mb, ptrs[26])
rot_x = struct.unpack_from("<1088f", mb, ptrs[63])
rot_y = struct.unpack_from("<1088f", mb, ptrs[64])
rot_ang = struct.unpack_from("<1088f", mb, ptrs[65])
rot_sx = struct.unpack_from("<1088f", mb, ptrs[68])

warp_kf_beg = struct.unpack_from(f"<{n_warp}i", mb, ptrs[20])
warp_cols = struct.unpack_from(f"<{n_warp}i", mb, ptrs[23])
warp_rows = struct.unpack_from(f"<{n_warp}i", mb, ptrs[24])
warp_pos_off = struct.unpack_from("<1056I", mb, ptrs[60])
all_pos_f = struct.unpack_from(f"<{n_pos_f}f", mb, ptrs[71])

draw_ids = [mb[ptrs[33]+i*64 : ptrs[33]+(i+1)*64].split(b"\x00",1)[0].decode("ascii","ignore") for i in range(n_draw)]
draw_kf_beg = struct.unpack_from(f"<{n_draw}I", mb, ptrs[35])
draw_parent = struct.unpack_from(f"<{n_draw}i", mb, ptrs[40])
v_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[43])
v_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[44])
idx_off = struct.unpack_from(f"<{n_draw}I", mb, ptrs[45])
idx_cnt = struct.unpack_from(f"<{n_draw}I", mb, ptrs[46])
kf_pos_idx = struct.unpack_from(f"<{n_art_kf}I", mb, ptrs[70])
uv_f = struct.unpack_from(f"<{n_uv_f}f", mb, ptrs[78])
tri_idxs = struct.unpack_from(f"<{len(mb[ptrs[79]:ptrs[80]])//2}H", mb, ptrs[79])

# Check Warp grid corners of Warp 0 (x,y of 4 corners) & RotDeformer sec[62..68] floats!
for s in range(62, 69):
    print(f"rot sec[{s}]: {tuple(round(x,3) for x in struct.unpack_from('<5f', mb, ptrs[s]))}")
# Wait: earlier rot_x[0]=0.019, rot_y[0]=0.009, rot_ang[0]=0.0003 -> notice sec[62]=0.0!
# What was [-766.1, -1161.8] at index 3 of rot_x?! Why was index 0 = 0.019 while index 1 = -244.78?!
# Let's check def 0..5 rot_kf_beg vs sec[25..31]!
for s in range(25, 32):
    print(f"rot_meta sec[{s}]: {struct.unpack_from('<6i', mb, ptrs[s])}")

# Wait! In moc3: sec[26]=kf_beg (0, 2, 11, 13...), sec[27]=kf_cnt! Look at sec[26..27]: earlier print had:
# sec[25] = keyformBindingSourcesOffsets, sec[26] = keyformBeginIndices (0, 2, 11, 13!), sec[27] = keyformCounts (2, 9, 2, 2!)!
# Earlier we read rot_x from sec[63] (`ptrs[63]`!), where sec[63]=baseX (or OriginX!), sec[64]=OriginY, sec[65]=Scale, sec[66]=Angle!
# Look at rot sec[63] index 0: 0.019 (`rot0` base?), sec[64] index 0: 0.009, sec[65] index 0: 0.0003, sec[68] index 0: 1.0!
# What about index 2 (`rot 1`): sec[63][2] = 0.0, sec[64][2] = -400.0, sec[65][2] = 1.0, sec[66][2] = 0.0!!
# SO sec[63]=OriginX, sec[64]=OriginY, sec[65]=OriginScale, sec[66]=OriginAngle, sec[67]=Opacity, sec[68]=Reflect/Scale!!
# We read rot_ang from sec[65] (which was OriginScale = 1.0 deg instead of sec[66] Angle = 0.0)!! Look how tiny that bug was!
# AND check WarpDeformer grid: sec[20]=kf_beg, sec[23]=rows, sec[24]=cols -> check 4 corners of warp 0:
p0 = warp_pos_off[warp_kf_beg[0]]
c0, r0 = warp_cols[0], warp_rows[0]
print(f"Warp0 grid {c0}x{r0} points ({(c0+1)*(r0+1)}):")
for rr in range(r0 + 1):
    row_pts = [(round(all_pos_f[p0 + 2*(rr*(c0+1)+cc)],1), round(all_pos_f[p0 + 2*(rr*(c0+1)+cc)+1],1)) for cc in range(c0+1)]
    print("  r", rr, row_pts)
