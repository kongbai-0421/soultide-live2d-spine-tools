"""Lossless Spine 3.8.79 Binary (.skel.bytes) -> JSON decoder and multi-skeleton merger.

Designed for merging excess `bj_*` sub-spines (and interleaving static images + native/GPU FX)
into Composite Spine 3.8.79 JSON submodels while keeping original lossless PMA `.webp` atlas pages
bit-exact (zero texture re-encoding or UV drift).
"""

from __future__ import annotations

import copy
import math
import struct
from pathlib import Path
from typing import Any


_TRANSFORM_MODES = (
    "normal",
    "onlyTranslation",
    "noRotationOrReflection",
    "noScale",
    "noScaleOrReflection",
)
_BLEND_MODES = ("normal", "additive", "multiply", "screen")
_POS_MODES = ("fixed", "percent")
_SPACE_MODES = ("length", "fixed", "percent")
_ROT_MODES = ("tangent", "chain", "chainScale")


class _BinReader:
    def __init__(self, data: bytes) -> None:
        self.b = data
        self.p = 0

    def u8(self) -> int:
        v = self.b[self.p]
        self.p += 1
        return v

    def i8(self) -> int:
        v = struct.unpack_from(">b", self.b, self.p)[0]
        self.p += 1
        return v

    def u16(self) -> int:
        v = struct.unpack_from(">H", self.b, self.p)[0]
        self.p += 2
        return v

    def i32(self) -> int:
        v = struct.unpack_from(">i", self.b, self.p)[0]
        self.p += 4
        return v

    def u32(self) -> int:
        v = struct.unpack_from(">I", self.b, self.p)[0]
        self.p += 4
        return v

    def bool(self) -> bool:
        return self.u8() != 0

    def f32(self) -> float:
        v = struct.unpack_from(">f", self.b, self.p)[0]
        self.p += 4
        return v

    def varint(self, opt: bool = True) -> int:
        res = 0
        shift = 0
        while True:
            b = self.b[self.p]
            self.p += 1
            res |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        return res if opt else ((res >> 1) ^ -(res & 1))

    def str(self) -> str | None:
        ln = self.varint(True)
        if ln == 0:
            return None
        ln -= 1
        s = self.b[self.p : self.p + ln].decode("utf-8", "replace")
        self.p += ln
        return s

    def rgba_hex(self) -> str:
        val = self.u32()
        return f"{val:08x}"

    def rgb_hex(self, val: int) -> str:
        return f"{val & 0xFFFFFF:06x}"


def _r4(v: float) -> float:
    return round(float(v), 5)


def _read_vertices(r: _BinReader, vertex_count: int) -> list[float | int]:
    if not r.bool():
        return [_r4(r.f32()) for _ in range(vertex_count * 2)]
    out: list[float | int] = []
    for _ in range(vertex_count):
        bc = r.varint(True)
        out.append(bc)
        for _ in range(bc):
            out.append(r.varint(True))
            out.append(_r4(r.f32()))
            out.append(_r4(r.f32()))
            out.append(_r4(r.f32()))
    return out


def _read_curve(r: _BinReader, kf: dict[str, Any]) -> None:
    ct = r.u8()
    if ct == 1:
        kf["curve"] = "stepped"
    elif ct == 2:
        c1, c2, c3, c4 = r.f32(), r.f32(), r.f32(), r.f32()
        kf["curve"] = _r4(c1)
        if abs(c2) > 1e-6:
            kf["c2"] = _r4(c2)
        if abs(c3 - 1.0) > 1e-6:
            kf["c3"] = _r4(c3)
        if abs(c4 - 1.0) > 1e-6:
            kf["c4"] = _r4(c4)


def spine38_binary_to_json(raw: bytes) -> dict[str, Any]:
    """Decode Spine 3.8.79 binary `.skel.bytes` into an exact Spine 3.8.79 JSON dict."""
    r = _BinReader(raw)
    sk_hash = r.str() or ""
    version = r.str() or "3.8.79"
    bx, by, bw, bh = r.f32(), r.f32(), r.f32(), r.f32()
    noness = r.bool()
    fps = 30.0
    images = ""
    audio = ""
    if noness:
        fps = r.f32()
        images = r.str() or ""
        audio = r.str() or ""

    str_cnt = r.varint(True)
    strings: list[str | None] = [None] + [r.str() for _ in range(str_cnt)]

    def sref() -> str | None:
        idx = r.varint(True)
        return strings[idx] if 0 <= idx < len(strings) else None

    # Bones
    bones: list[dict[str, Any]] = []
    bone_names: list[str] = []
    n_bones = r.varint(True)
    for i in range(n_bones):
        nm = r.str() or f"bone_{i}"
        bone_names.append(nm)
        b: dict[str, Any] = {"name": nm}
        if i > 0:
            par = r.varint(True)
            b["parent"] = bone_names[par]
        rot = r.f32()
        x = r.f32()
        y = r.f32()
        sx = r.f32()
        sy = r.f32()
        shx = r.f32()
        shy = r.f32()
        blen = r.f32()
        tmode = r.varint(True)
        skin_req = r.bool()
        if noness:
            _col = r.u32()
        if abs(blen) > 1e-5:
            b["length"] = _r4(blen)
        if tmode != 0 and 0 <= tmode < len(_TRANSFORM_MODES):
            b["transform"] = _TRANSFORM_MODES[tmode]
        if skin_req:
            b["skin"] = True
        if abs(x) > 1e-5:
            b["x"] = _r4(x)
        if abs(y) > 1e-5:
            b["y"] = _r4(y)
        if abs(rot) > 1e-5:
            b["rotation"] = _r4(rot)
        if abs(sx - 1.0) > 1e-5:
            b["scaleX"] = _r4(sx)
        if abs(sy - 1.0) > 1e-5:
            b["scaleY"] = _r4(sy)
        if abs(shx) > 1e-5:
            b["shearX"] = _r4(shx)
        if abs(shy) > 1e-5:
            b["shearY"] = _r4(shy)
        bones.append(b)

    # Slots
    slots: list[dict[str, Any]] = []
    slot_names: list[str] = []
    for i in range(r.varint(True)):
        sn = r.str() or f"slot_{i}"
        slot_names.append(sn)
        bi = r.varint(True)
        col = r.rgba_hex()
        dark = r.i32()
        att = sref()
        blend = r.varint(True)
        s: dict[str, Any] = {"name": sn, "bone": bone_names[bi]}
        if col != "ffffffff":
            s["color"] = col
        if dark != -1:
            s["dark"] = r.rgb_hex(dark)
        if att is not None:
            s["attachment"] = att
        if blend != 0 and 0 <= blend < len(_BLEND_MODES):
            s["blend"] = _BLEND_MODES[blend]
        slots.append(s)

    # IK Constraints
    ik_list: list[dict[str, Any]] = []
    ik_names: list[str] = []
    for i in range(r.varint(True)):
        nm = r.str() or f"ik_{i}"
        ik_names.append(nm)
        order = r.varint(True)
        skin_req = r.bool()
        ibones = [bone_names[r.varint(True)] for _ in range(r.varint(True))]
        target = bone_names[r.varint(True)]
        mix = r.f32()
        softness = r.f32()
        bend = r.i8()
        compress = r.bool()
        stretch = r.bool()
        uniform = r.bool()
        rec: dict[str, Any] = {
            "name": nm,
            "order": order,
            "bones": ibones,
            "target": target,
        }
        if skin_req:
            rec["skin"] = True
        if abs(mix - 1.0) > 1e-5:
            rec["mix"] = _r4(mix)
        if abs(softness) > 1e-5:
            rec["softness"] = _r4(softness)
        if bend < 0:
            rec["bendPositive"] = False
        if compress:
            rec["compress"] = True
        if stretch:
            rec["stretch"] = True
        if uniform:
            rec["uniform"] = True
        ik_list.append(rec)

    # Transform Constraints
    tf_list: list[dict[str, Any]] = []
    tf_names: list[str] = []
    for i in range(r.varint(True)):
        nm = r.str() or f"tf_{i}"
        tf_names.append(nm)
        order = r.varint(True)
        skin_req = r.bool()
        tbones = [bone_names[r.varint(True)] for _ in range(r.varint(True))]
        target = bone_names[r.varint(True)]
        local = r.bool()
        relative = r.bool()
        off_rot = r.f32()
        off_x = r.f32()
        off_y = r.f32()
        off_sx = r.f32()
        off_sy = r.f32()
        off_shy = r.f32()
        rmix = r.f32()
        tmix = r.f32()
        smix = r.f32()
        shmix = r.f32()
        rec = {
            "name": nm,
            "order": order,
            "bones": tbones,
            "target": target,
            "rotateMix": _r4(rmix),
            "translateMix": _r4(tmix),
            "scaleMix": _r4(smix),
            "shearMix": _r4(shmix),
        }
        if skin_req:
            rec["skin"] = True
        if local:
            rec["local"] = True
        if relative:
            rec["relative"] = True
        if abs(off_rot) > 1e-5:
            rec["rotation"] = _r4(off_rot)
        if abs(off_x) > 1e-5:
            rec["x"] = _r4(off_x)
        if abs(off_y) > 1e-5:
            rec["y"] = _r4(off_y)
        if abs(off_sx) > 1e-5:
            rec["scaleX"] = _r4(off_sx)
        if abs(off_sy) > 1e-5:
            rec["scaleY"] = _r4(off_sy)
        if abs(off_shy) > 1e-5:
            rec["shearY"] = _r4(off_shy)
        tf_list.append(rec)

    # Path Constraints
    path_list: list[dict[str, Any]] = []
    path_names: list[str] = []
    for i in range(r.varint(True)):
        nm = r.str() or f"path_{i}"
        path_names.append(nm)
        order = r.varint(True)
        skin_req = r.bool()
        pbones = [bone_names[r.varint(True)] for _ in range(r.varint(True))]
        target = slot_names[r.varint(True)]
        pmode = r.varint(True)
        smode = r.varint(True)
        rmode = r.varint(True)
        off_rot = r.f32()
        pos = r.f32()
        sp = r.f32()
        rmix = r.f32()
        tmix = r.f32()
        rec = {
            "name": nm,
            "order": order,
            "bones": pbones,
            "target": target,
            "positionMode": _POS_MODES[pmode],
            "spacingMode": _SPACE_MODES[smode],
            "rotateMode": _ROT_MODES[rmode],
            "rotation": _r4(off_rot),
            "position": _r4(pos),
            "spacing": _r4(sp),
            "rotateMix": _r4(rmix),
            "translateMix": _r4(tmix),
        }
        if skin_req:
            rec["skin"] = True
        path_list.append(rec)

    # Skins
    skins: list[dict[str, Any]] = []
    skin_names: list[str] = []

    def read_skin(is_default: bool) -> dict[str, Any] | None:
        if is_default:
            slot_cnt = r.varint(True)
            if slot_cnt == 0:
                return None
            sk_name = "default"
            sk_obj: dict[str, Any] = {"name": sk_name}
        else:
            sk_name = sref() or "skin"
            sk_obj = {"name": sk_name}
            sb = [bone_names[r.varint(True)] for _ in range(r.varint(True))]
            sik = [ik_names[r.varint(True)] for _ in range(r.varint(True))]
            stf = [tf_names[r.varint(True)] for _ in range(r.varint(True))]
            spth = [path_names[r.varint(True)] for _ in range(r.varint(True))]
            if sb:
                sk_obj["bones"] = sb
            if sik:
                sk_obj["ik"] = sik
            if stf:
                sk_obj["transform"] = stf
            if spth:
                sk_obj["path"] = spth
            slot_cnt = r.varint(True)

        atts: dict[str, dict[str, Any]] = {}
        for _ in range(slot_cnt):
            sidx = r.varint(True)
            sname = slot_names[sidx]
            s_atts = atts.setdefault(sname, {})
            for _ in range(r.varint(True)):
                att_key = sref() or ""
                real_name = sref() or att_key
                atype = r.u8()
                if atype == 0:  # region
                    path = sref()
                    rot = r.f32()
                    x = r.f32()
                    y = r.f32()
                    sx = r.f32()
                    sy = r.f32()
                    w = r.f32()
                    h = r.f32()
                    col = r.rgba_hex()
                    a: dict[str, Any] = {"width": _r4(w), "height": _r4(h)}
                    if real_name != att_key:
                        a["name"] = real_name
                    if path and path != real_name:
                        a["path"] = path
                    if abs(x) > 1e-5:
                        a["x"] = _r4(x)
                    if abs(y) > 1e-5:
                        a["y"] = _r4(y)
                    if abs(rot) > 1e-5:
                        a["rotation"] = _r4(rot)
                    if abs(sx - 1.0) > 1e-5:
                        a["scaleX"] = _r4(sx)
                    if abs(sy - 1.0) > 1e-5:
                        a["scaleY"] = _r4(sy)
                    if col != "ffffffff":
                        a["color"] = col
                    s_atts[att_key] = a
                elif atype == 1:  # boundingbox
                    vc = r.varint(True)
                    verts = _read_vertices(r, vc)
                    if noness:
                        _col = r.u32()
                    a = {"type": "boundingbox", "vertexCount": vc, "vertices": verts}
                    if real_name != att_key:
                        a["name"] = real_name
                    s_atts[att_key] = a
                elif atype == 2:  # mesh
                    path = sref()
                    col = r.rgba_hex()
                    vc = r.varint(True)
                    uvs = [_r4(r.f32()) for _ in range(vc * 2)]
                    tri_cnt = r.varint(True)
                    tris = [r.u16() for _ in range(tri_cnt)]
                    verts = _read_vertices(r, vc)
                    hull = r.varint(True)
                    edges = None
                    w = h = 0.0
                    if noness:
                        ec = r.varint(True)
                        edges = [r.u16() for _ in range(ec)]
                        w = r.f32()
                        h = r.f32()
                    a = {
                        "type": "mesh",
                        "uvs": uvs,
                        "triangles": tris,
                        "vertices": verts,
                        "hull": hull,
                    }
                    if real_name != att_key:
                        a["name"] = real_name
                    if path and path != real_name:
                        a["path"] = path
                    if col != "ffffffff":
                        a["color"] = col
                    if edges:
                        a["edges"] = edges
                    if w > 0:
                        a["width"] = _r4(w)
                    if h > 0:
                        a["height"] = _r4(h)
                    s_atts[att_key] = a
                elif atype == 3:  # linkedmesh
                    path = sref()
                    col = r.rgba_hex()
                    parent_skin = sref()
                    parent_att = sref()
                    deform = r.bool()
                    w = h = 0.0
                    if noness:
                        w = r.f32()
                        h = r.f32()
                    a = {"type": "linkedmesh", "parent": parent_att or "", "deform": deform}
                    if real_name != att_key:
                        a["name"] = real_name
                    if path and path != real_name:
                        a["path"] = path
                    if parent_skin:
                        a["skin"] = parent_skin
                    if col != "ffffffff":
                        a["color"] = col
                    if w > 0:
                        a["width"] = _r4(w)
                    if h > 0:
                        a["height"] = _r4(h)
                    s_atts[att_key] = a
                elif atype == 4:  # path
                    closed = r.bool()
                    const_spd = r.bool()
                    vc = r.varint(True)
                    verts = _read_vertices(r, vc)
                    lengths = [_r4(r.f32()) for _ in range(vc // 3)]
                    if noness:
                        _col = r.u32()
                    a = {
                        "type": "path",
                        "closed": closed,
                        "constantSpeed": const_spd,
                        "vertexCount": vc,
                        "vertices": verts,
                        "lengths": lengths,
                    }
                    if real_name != att_key:
                        a["name"] = real_name
                    s_atts[att_key] = a
                elif atype == 5:  # point
                    rot = r.f32()
                    x = r.f32()
                    y = r.f32()
                    if noness:
                        _col = r.u32()
                    a = {"type": "point", "x": _r4(x), "y": _r4(y), "rotation": _r4(rot)}
                    if real_name != att_key:
                        a["name"] = real_name
                    s_atts[att_key] = a
                elif atype == 6:  # clipping
                    end_idx = r.varint(True)
                    vc = r.varint(True)
                    verts = _read_vertices(r, vc)
                    if noness:
                        _col = r.u32()
                    a = {
                        "type": "clipping",
                        "end": slot_names[end_idx] if 0 <= end_idx < len(slot_names) else "",
                        "vertexCount": vc,
                        "vertices": verts,
                    }
                    if real_name != att_key:
                        a["name"] = real_name
                    s_atts[att_key] = a
                else:
                    raise ValueError(f"Unknown Spine 3.8 attachment type: {atype}")
        sk_obj["attachments"] = atts
        return sk_obj

    def_skin = read_skin(True)
    if def_skin is not None:
        skins.append(def_skin)
        skin_names.append("default")
    else:
        skins.append({"name": "default", "attachments": {}})
        skin_names.append("default")
    for _ in range(r.varint(True)):
        sk_o = read_skin(False)
        if sk_o is not None:
            skins.append(sk_o)
            skin_names.append(sk_o["name"])

    # Events
    events: dict[str, dict[str, Any]] = {}
    event_names: list[str] = []
    for _ in range(r.varint(True)):
        ename = sref() or ""
        event_names.append(ename)
        ei = r.varint(False)
        ef = r.f32()
        es = r.str() or ""
        ea = r.str() or ""
        ev: dict[str, Any] = {}
        if ei != 0:
            ev["int"] = ei
        if abs(ef) > 1e-6:
            ev["float"] = _r4(ef)
        if es:
            ev["string"] = es
        if ea:
            ev["audio"] = ea
            vol = r.f32()
            bal = r.f32()
            if abs(vol - 1.0) > 1e-5:
                ev["volume"] = _r4(vol)
            if abs(bal) > 1e-5:
                ev["balance"] = _r4(bal)
        events[ename] = ev

    # Animations
    animations: dict[str, dict[str, Any]] = {}
    n_anims = r.varint(True)
    for ai in range(n_anims):
        aname = r.str() or f"anim_{ai}"
        anim: dict[str, Any] = {}

        # Slot timelines
        sl_tls: dict[str, dict[str, Any]] = {}
        for _ in range(r.varint(True)):
            sname = slot_names[r.varint(True)]
            st_map = sl_tls.setdefault(sname, {})
            for _ in range(r.varint(True)):
                tt = r.u8()
                fc = r.varint(True)
                if tt == 0:  # attachment
                    kfs = [{"time": _r4(r.f32()), "name": sref()} for _ in range(fc)]
                    st_map["attachment"] = kfs
                elif tt == 1:  # color
                    kfs = []
                    for fi in range(fc):
                        kf: dict[str, Any] = {"time": _r4(r.f32()), "color": r.rgba_hex()}
                        if fi < fc - 1:
                            _read_curve(r, kf)
                        kfs.append(kf)
                    st_map["color"] = kfs
                elif tt == 2:  # twoColor
                    kfs = []
                    for fi in range(fc):
                        t_v = _r4(r.f32())
                        l_hex = r.rgba_hex()
                        d_val = r.i32()
                        kf = {"time": t_v, "light": l_hex, "dark": r.rgb_hex(d_val)}
                        if fi < fc - 1:
                            _read_curve(r, kf)
                        kfs.append(kf)
                    st_map["twoColor"] = kfs
                else:
                    raise ValueError(f"Unknown slot timeline type {tt}")
        if sl_tls:
            anim["slots"] = sl_tls

        # Bone timelines
        bn_tls: dict[str, dict[str, Any]] = {}
        for _ in range(r.varint(True)):
            bname = bone_names[r.varint(True)]
            bt_map = bn_tls.setdefault(bname, {})
            for _ in range(r.varint(True)):
                tt = r.u8()
                fc = r.varint(True)
                kfs = []
                for fi in range(fc):
                    t_v = _r4(r.f32())
                    if tt == 0:
                        kf = {"time": t_v, "angle": _r4(r.f32())}
                    elif tt in (1, 2, 3):
                        kf = {"time": t_v, "x": _r4(r.f32()), "y": _r4(r.f32())}
                    else:
                        raise ValueError(f"Unknown bone timeline type {tt}")
                    if fi < fc - 1:
                        _read_curve(r, kf)
                    kfs.append(kf)
                bt_map[("rotate", "translate", "scale", "shear")[tt]] = kfs
        if bn_tls:
            anim["bones"] = bn_tls

        # IK timelines
        ik_tls: dict[str, list[dict[str, Any]]] = {}
        for _ in range(r.varint(True)):
            ik_nm = ik_names[r.varint(True)]
            fc = r.varint(True)
            kfs = []
            for fi in range(fc):
                t_v = _r4(r.f32())
                mix = _r4(r.f32())
                soft = _r4(r.f32())
                bend = r.i8()
                comp = r.bool()
                stre = r.bool()
                kf = {"time": t_v, "mix": mix, "softness": soft, "bendPositive": bend >= 0, "compress": comp, "stretch": stre}
                if fi < fc - 1:
                    _read_curve(r, kf)
                kfs.append(kf)
            ik_tls[ik_nm] = kfs
        if ik_tls:
            anim["ik"] = ik_tls

        # Transform timelines
        tf_tls: dict[str, list[dict[str, Any]]] = {}
        for _ in range(r.varint(True)):
            tf_nm = tf_names[r.varint(True)]
            fc = r.varint(True)
            kfs = []
            for fi in range(fc):
                kf = {
                    "time": _r4(r.f32()),
                    "rotateMix": _r4(r.f32()),
                    "translateMix": _r4(r.f32()),
                    "scaleMix": _r4(r.f32()),
                    "shearMix": _r4(r.f32()),
                }
                if fi < fc - 1:
                    _read_curve(r, kf)
                kfs.append(kf)
            tf_tls[tf_nm] = kfs
        if tf_tls:
            anim["transform"] = tf_tls

        # Path timelines
        pth_tls: dict[str, dict[str, Any]] = {}
        for _ in range(r.varint(True)):
            p_nm = path_names[r.varint(True)]
            pm = pth_tls.setdefault(p_nm, {})
            for _ in range(r.varint(True)):
                tt = r.u8()
                fc = r.varint(True)
                kfs = []
                for fi in range(fc):
                    t_v = _r4(r.f32())
                    if tt == 0:
                        kf = {"time": t_v, "position": _r4(r.f32())}
                    elif tt == 1:
                        kf = {"time": t_v, "spacing": _r4(r.f32())}
                    elif tt == 2:
                        kf = {"time": t_v, "rotateMix": _r4(r.f32()), "translateMix": _r4(r.f32())}
                    else:
                        raise ValueError(f"Unknown path timeline type {tt}")
                    if fi < fc - 1:
                        _read_curve(r, kf)
                    kfs.append(kf)
                pm[("position", "spacing", "mix")[tt]] = kfs
        if pth_tls:
            anim["path"] = pth_tls

        # Deform timelines
        def_tls: dict[str, dict[str, dict[str, list[dict[str, Any]]]]] = {}
        for _ in range(r.varint(True)):
            sk_nm = skin_names[r.varint(True)]
            sk_m = def_tls.setdefault(sk_nm, {})
            for _ in range(r.varint(True)):
                sl_nm = slot_names[r.varint(True)]
                sl_m = sk_m.setdefault(sl_nm, {})
                for _ in range(r.varint(True)):
                    att_nm = sref() or ""
                    fc = r.varint(True)
                    kfs = []
                    for fi in range(fc):
                        t_v = _r4(r.f32())
                        end = r.varint(True)
                        kf = {"time": t_v}
                        if end > 0:
                            start = r.varint(True)
                            verts = [_r4(r.f32()) for _ in range(end)]
                            if start > 0:
                                kf["offset"] = start
                            kf["vertices"] = verts
                        if fi < fc - 1:
                            _read_curve(r, kf)
                        kfs.append(kf)
                    sl_m[att_nm] = kfs
        if def_tls:
            anim["deform"] = def_tls

        # DrawOrder timelines
        do_cnt = r.varint(True)
        if do_cnt > 0:
            do_kfs = []
            for _ in range(do_cnt):
                t_v = _r4(r.f32())
                offs = []
                for _ in range(r.varint(True)):
                    sidx = r.varint(True)
                    off = r.varint(True)
                    offs.append({"slot": slot_names[sidx], "offset": off})
                do_kfs.append({"time": t_v, "offsets": offs})
            anim["drawOrder"] = do_kfs

        # Event timelines
        ev_cnt = r.varint(True)
        if ev_cnt > 0:
            ev_kfs = []
            for _ in range(ev_cnt):
                t_v = _r4(r.f32())
                eidx = r.varint(True)
                ename = event_names[eidx]
                base_ev = events.get(ename, {})
                ei = r.varint(False)
                ef = r.f32()
                has_str = r.bool()
                es = r.str() if has_str else None
                kf = {"time": t_v, "name": ename}
                if ei != base_ev.get("int", 0):
                    kf["int"] = ei
                if abs(ef - base_ev.get("float", 0.0)) > 1e-6:
                    kf["float"] = _r4(ef)
                if has_str and es is not None:
                    kf["string"] = es
                if base_ev.get("audio"):
                    vol = r.f32()
                    bal = r.f32()
                    kf["volume"] = _r4(vol)
                    kf["balance"] = _r4(bal)
                ev_kfs.append(kf)
            anim["events"] = ev_kfs

        animations[aname] = anim

    if r.p != len(raw):
        raise ValueError(f"Spine 3.8 binary trailing/misaligned bytes: parsed={r.p} vs total={len(raw)}")

    sk_hdr: dict[str, Any] = {
        "hash": sk_hash,
        "spine": version or "3.8.79",
        "x": _r4(bx),
        "y": _r4(by),
        "width": _r4(bw),
        "height": _r4(bh),
    }
    if noness:
        if fps > 0:
            sk_hdr["fps"] = _r4(fps)
        if images:
            sk_hdr["images"] = images
        if audio:
            sk_hdr["audio"] = audio

    out: dict[str, Any] = {
        "skeleton": sk_hdr,
        "bones": bones,
        "slots": slots,
        "skins": skins,
        "animations": animations,
    }
    if ik_list:
        out["ik"] = ik_list
    if tf_list:
        out["transform"] = tf_list
    if path_list:
        out["path"] = path_list
    if events:
        out["events"] = events
    return out


def animation_duration(anim: dict[str, Any]) -> float:
    """Compute exact Spine 3.8 animation duration (max keyframe time across all timelines)."""
    dur = 0.0
    for sl_map in (anim.get("slots") or {}).values():
        for kfs in sl_map.values():
            if kfs:
                dur = max(dur, float(kfs[-1].get("time", 0.0)))
    for bn_map in (anim.get("bones") or {}).values():
        for kfs in bn_map.values():
            if kfs:
                dur = max(dur, float(kfs[-1].get("time", 0.0)))
    for kfs in (anim.get("ik") or {}).values():
        if kfs:
            dur = max(dur, float(kfs[-1].get("time", 0.0)))
    for kfs in (anim.get("transform") or {}).values():
        if kfs:
            dur = max(dur, float(kfs[-1].get("time", 0.0)))
    for p_map in (anim.get("path") or {}).values():
        for kfs in p_map.values():
            if kfs:
                dur = max(dur, float(kfs[-1].get("time", 0.0)))
    for sk_m in (anim.get("deform") or {}).values():
        for sl_m in sk_m.values():
            for kfs in sl_m.values():
                if kfs:
                    dur = max(dur, float(kfs[-1].get("time", 0.0)))
    for kfs in (anim.get("drawOrder") or []):
        dur = max(dur, float(kfs.get("time", 0.0)))
    for kfs in (anim.get("events") or []):
        dur = max(dur, float(kfs.get("time", 0.0)))
    return dur


def _tile_keyframes(kfs: list[dict[str, Any]], orig_dur: float, target_dur: float, is_stepped_type: bool = False) -> list[dict[str, Any]]:
    """Tile a looping timeline cleanly across [0, target_dur] with minimal speed adjustment."""
    if not kfs:
        return []
    if orig_dur <= 1e-4:
        return [dict(kfs[0], time=0.0)]
    reps = max(1, int(round(target_dur / orig_dur)))
    cycle_t = target_dur / reps
    scale = cycle_t / orig_dur

    out: list[dict[str, Any]] = []
    for rep in range(reps):
        base_t = rep * cycle_t
        for ki, kf in enumerate(kfs):
            t_new = round(base_t + float(kf.get("time", 0.0)) * scale, 4)
            # Avoid duplicate timestamp at cycle boundary when kfs has both t=0 and t=orig_dur
            if rep > 0 and ki == 0 and out and abs(t_new - float(out[-1].get("time", -1.0))) < 1e-3:
                # Overwrite boundary with cycle start state (preserves clean loop start & curve)
                out[-1] = dict(kf, time=t_new)
                continue
            nkf = dict(kf)
            nkf["time"] = t_new
            # If last keyframe of cycle < reps - 1 and doesn't reach orig_dur, make it stepped before next cycle's t=0
            if ki == len(kfs) - 1 and rep < reps - 1 and not is_stepped_type:
                if float(kf.get("time", 0.0)) < orig_dur - 1e-3:
                    nkf["curve"] = "stepped"
            out.append(nkf)
    if out and "curve" in out[-1]:
        out[-1].pop("curve", None)
    return out


def prefix_atlas_text(atlas_txt: str, region_prefix: str, page_rename_map: dict[str, str]) -> str:
    """Prefix every region name in a Spine .atlas.txt block and rewrite page image filenames."""
    out_lines: list[str] = []
    lines = atlas_txt.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        s = ln.strip()
        if not s:
            out_lines.append("")
            i += 1
            continue
        # Check if this line is a page filename (next line starts with size:)
        if i + 1 < n and lines[i + 1].strip().startswith("size:"):
            new_fn = page_rename_map.get(s, page_rename_map.get(s.lower(), s))
            out_lines.append(new_fn)
            i += 1
            # Copy page header lines (size, format, filter, repeat)
            while i < n and lines[i].strip() and ":" in lines[i] and not lines[i].startswith("  "):
                out_lines.append(lines[i])
                i += 1
            continue
        # Otherwise if not indented and no colon -> region name!
        if not ln.startswith(" ") and ":" not in s:
            out_lines.append(f"{region_prefix}{s}")
            i += 1
            continue
        out_lines.append(ln)
        i += 1
    return "\n".join(out_lines).strip()


def merge_spine38_into_composite(
    src_skel: dict[str, Any],
    prefix: str,
    anim_name: str,
    root_x: float,
    root_y: float,
    root_sx: float,
    root_sy: float,
    root_rot: float,
    target_dur: float,
    dst_bones: list[dict[str, Any]],
    dst_slots: list[dict[str, Any]],
    dst_skin_att: dict[str, dict[str, Any]],
    dst_ik: list[dict[str, Any]],
    dst_tf: list[dict[str, Any]],
    dst_path: list[dict[str, Any]],
    dst_anim: dict[str, Any],
    order_base: int = 0,
) -> int:
    """Merge a decoded Spine 3.8 JSON skeleton into a composite skeleton under a dedicated mount bone.

    All bones, slots, constraints, and atlas region references are prefixed with `prefix`,
    and the chosen animation is tiled cleanly across `[0, target_dur]`.
    Returns next available constraint `order_base`.
    """
    src_bones = src_skel.get("bones") or []
    src_slots = src_skel.get("slots") or []
    if not src_bones or not src_slots:
        return order_base

    # 1. Create mount bone under composite "root" carrying exact Unity->Spine world placement
    mount_bone = f"{prefix}mount"
    m_def: dict[str, Any] = {"name": mount_bone, "parent": "root"}
    if abs(root_x) > 1e-4:
        m_def["x"] = _r4(root_x)
    if abs(root_y) > 1e-4:
        m_def["y"] = _r4(root_y)
    if abs(root_rot) > 1e-3:
        m_def["rotation"] = _r4(root_rot)
    if abs(root_sx - 1.0) > 1e-5:
        m_def["scaleX"] = _r4(root_sx)
    if abs(root_sy - 1.0) > 1e-5:
        m_def["scaleY"] = _r4(root_sy)
    dst_bones.append(m_def)

    # Remap bones (track original index -> new index for weighted mesh vertices!)
    bone_idx_offset = len(dst_bones)
    for bi, sb in enumerate(src_bones):
        nb = copy.deepcopy(sb)
        nb["name"] = f"{prefix}{sb['name']}"
        if bi == 0 or "parent" not in sb:
            nb["parent"] = mount_bone
        else:
            nb["parent"] = f"{prefix}{sb['parent']}"
        dst_bones.append(nb)

    # Remap slots
    for ss in src_slots:
        ns = copy.deepcopy(ss)
        ns["name"] = f"{prefix}{ss['name']}"
        ns["bone"] = f"{prefix}{ss['bone']}"
        dst_slots.append(ns)

    # Remap constraints
    max_ord = order_base
    for ik in src_skel.get("ik") or []:
        nik = copy.deepcopy(ik)
        nik["name"] = f"{prefix}{ik['name']}"
        nik["order"] = order_base + int(ik.get("order", 0))
        max_ord = max(max_ord, nik["order"] + 1)
        nik["bones"] = [f"{prefix}{bn}" for bn in ik.get("bones") or []]
        nik["target"] = f"{prefix}{ik['target']}"
        dst_ik.append(nik)
    for tf in src_skel.get("transform") or []:
        ntf = copy.deepcopy(tf)
        ntf["name"] = f"{prefix}{tf['name']}"
        ntf["order"] = order_base + int(tf.get("order", 0))
        max_ord = max(max_ord, ntf["order"] + 1)
        ntf["bones"] = [f"{prefix}{bn}" for bn in tf.get("bones") or []]
        ntf["target"] = f"{prefix}{tf['target']}"
        dst_tf.append(ntf)
    for pt in src_skel.get("path") or []:
        npt = copy.deepcopy(pt)
        npt["name"] = f"{prefix}{pt['name']}"
        npt["order"] = order_base + int(pt.get("order", 0))
        max_ord = max(max_ord, npt["order"] + 1)
        npt["bones"] = [f"{prefix}{bn}" for bn in pt.get("bones") or []]
        npt["target"] = f"{prefix}{pt['target']}"
        dst_path.append(npt)

    # Remap default skin attachments (offsetting weighted vertex bone indices + prefixing region paths!)
    def _offset_weighted_verts(verts: list[Any], vc_expected: int) -> list[Any]:
        if len(verts) == vc_expected * 2:
            return list(verts)
        out: list[Any] = []
        i = 0
        n = len(verts)
        while i < n:
            bc = int(verts[i])
            out.append(bc)
            i += 1
            for _ in range(bc):
                out.append(int(verts[i]) + bone_idx_offset)
                out.append(verts[i + 1])
                out.append(verts[i + 2])
                out.append(verts[i + 3])
                i += 4
        return out

    src_def_skin = next((s for s in (src_skel.get("skins") or []) if s.get("name") == "default"), None)
    if src_def_skin is None and (src_skel.get("skins") or []):
        src_def_skin = src_skel["skins"][0]

    for sl_nm, att_map in ((src_def_skin or {}).get("attachments") or {}).items():
        new_sl = f"{prefix}{sl_nm}"
        out_map: dict[str, Any] = {}
        for att_key, a_def in att_map.items():
            na = copy.deepcopy(a_def)
            atype = na.get("type", "region")
            if atype in ("region", "mesh", "linkedmesh"):
                orig_path = na.get("path") or na.get("name") or att_key
                na["path"] = f"{prefix}{orig_path}"
            if atype == "mesh":
                vc = len(na.get("uvs") or []) // 2
                na["vertices"] = _offset_weighted_verts(na.get("vertices") or [], vc)
            elif atype in ("boundingbox", "path", "clipping"):
                vc = int(na.get("vertexCount", 0))
                na["vertices"] = _offset_weighted_verts(na.get("vertices") or [], vc)
                if atype == "clipping" and na.get("end"):
                    na["end"] = f"{prefix}{na['end']}"
            out_map[att_key] = na
        dst_skin_att[new_sl] = out_map

    # Remap and tile chosen animation into dst_anim
    anims = src_skel.get("animations") or {}
    src_anim = anims.get(anim_name)
    if src_anim is None:
        for fb in ("idle", "animation"):
            if fb in anims:
                src_anim = anims[fb]
                break
        if src_anim is None and anims:
            src_anim = next(iter(anims.values()))

    if src_anim:
        orig_dur = animation_duration(src_anim)
        if src_anim.get("slots"):
            dst_sl_a = dst_anim.setdefault("slots", {})
            for sl_nm, tl_map in src_anim["slots"].items():
                ntlm: dict[str, Any] = {}
                for tname, kfs in tl_map.items():
                    ntlm[tname] = _tile_keyframes(kfs, orig_dur, target_dur, is_stepped_type=(tname == "attachment"))
                dst_sl_a[f"{prefix}{sl_nm}"] = ntlm
        if src_anim.get("bones"):
            dst_bn_a = dst_anim.setdefault("bones", {})
            for bn_nm, tl_map in src_anim["bones"].items():
                ntlm = {}
                for tname, kfs in tl_map.items():
                    ntlm[tname] = _tile_keyframes(kfs, orig_dur, target_dur)
                dst_bn_a[f"{prefix}{bn_nm}"] = ntlm
        if src_anim.get("ik"):
            dst_ik_a = dst_anim.setdefault("ik", {})
            for nm, kfs in src_anim["ik"].items():
                dst_ik_a[f"{prefix}{nm}"] = _tile_keyframes(kfs, orig_dur, target_dur)
        if src_anim.get("transform"):
            dst_tf_a = dst_anim.setdefault("transform", {})
            for nm, kfs in src_anim["transform"].items():
                dst_tf_a[f"{prefix}{nm}"] = _tile_keyframes(kfs, orig_dur, target_dur)
        if src_anim.get("path"):
            dst_p_a = dst_anim.setdefault("path", {})
            for nm, tl_map in src_anim["path"].items():
                ntlm = {tn: _tile_keyframes(kfs, orig_dur, target_dur) for tn, kfs in tl_map.items()}
                dst_p_a[f"{prefix}{nm}"] = ntlm
        if src_anim.get("deform"):
            dst_def_a = dst_anim.setdefault("deform", {})
            for sk_nm, sl_map in src_anim["deform"].items():
                dst_sk = dst_def_a.setdefault("default", {})
                for sl_nm, att_map in sl_map.items():
                    dst_sl = dst_sk.setdefault(f"{prefix}{sl_nm}", {})
                    for att_nm, kfs in att_map.items():
                        dst_sl[att_nm] = _tile_keyframes(kfs, orig_dur, target_dur)

    return max_ord
