"""Shared SoulTide AssetBundle, AudioClip, Lua table, and I18N utilities."""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from typing import Any
import UnityPy

CDN_ROOT = Path(r"D:\A灵魂潮汐-本地化\服务器\offline_cdn\Android")
DECOMPILED_DIR = Path(
    r"D:\A灵魂潮汐-本地化\服务器\analysis\luajit-pipeline\baseline-20260813\decompiled-x64"
)


def load_ab(path: Path) -> UnityPy.Environment:
    """Load a SoulTide AssetBundle, stripping the 6-byte 'iqigam' header if present."""
    raw = path.read_bytes()
    payload = raw[6:] if raw.startswith(b"iqigam") else raw
    return UnityPy.load(io.BytesIO(payload))


def write_json(path: Path, data: Any) -> None:
    """Write UTF-8 JSON with clean formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_wav_bytes(clip_obj) -> bytes:
    """Decode an AudioClip object into RIFF WAVE bytes via UnityPy samples."""
    clip = clip_obj.read()
    samples = clip.samples
    if not samples:
        raise ValueError(f"AudioClip '{getattr(clip, 'm_Name', '?')}' produced no decoded samples")
    _, wav_bytes = next(iter(samples.items()))
    return bytes(wav_bytes)


def parse_lua_flat_table(path: Path) -> dict[int, str]:
    """Extract top-level `[id] = { ... }` raw body blocks from a decompiled Lua table."""
    txt = path.read_text(encoding="utf-8", errors="ignore")
    parts = re.split(r"\n\t\[(\d+)\] = \{", txt)
    out: dict[int, str] = {}
    for i in range(1, len(parts), 2):
        kid = int(parts[i])
        body = parts[i + 1].split("\n\t}")[0]
        out[kid] = body
    return out


class LuaTableRepo:
    """Read-only repository for SoulTide decompiled Lua config tables and I18N strings."""

    def __init__(self, decompiled_dir: Path = DECOMPILED_DIR) -> None:
        self.dir = decompiled_dir
        self._i18n_ranges: list[tuple[int, int, int]] | None = None
        self._i18n_shards: dict[int, dict[int, str]] = {}
        self._cv: dict[int, dict[str, Any]] | None = None
        self._sound: dict[int, str] | None = None
        self._actions: dict[int, dict[str, Any]] | None = None
        self._action_groups: dict[int, str] | None = None
        self._spine_ctrl: dict[int, str] | None = None
        self._spine_actions: dict[int, str] | None = None

    def get_i18n(self, i18n_id: int | None) -> str:
        """Resolve an I18N ID and normalize SoulTide line break markers."""
        if not i18n_id:
            return ""
        if self._i18n_ranges is None:
            route = (self.dir / "CfgI18NTable_Route.lua").read_text(encoding="utf-8", errors="ignore")
            self._i18n_ranges = [
                (int(a), int(b), int(c))
                for a, b, c in re.findall(r"\{\s*(\d+),\s*(\d+),\s*(\d+)\s*\}", route)
            ]
        shard = None
        for lo, hi, idx in self._i18n_ranges:
            if lo <= i18n_id <= hi:
                shard = idx
                break
        if shard is None:
            return ""
        if shard not in self._i18n_shards:
            txt = (self.dir / f"CfgI18NTable_{shard}.lua").read_text(encoding="utf-8", errors="ignore")
            pat = re.compile(
                r'\[(\d+)\]\s*=\s*\{\s*Id\s*=\s*\d+,\s*Str\s*=\s*"((?:[^"\\]|\\.)*)"',
                re.S,
            )
            self._i18n_shards[shard] = {int(m.group(1)): m.group(2) for m in pat.finditer(txt)}
        raw = self._i18n_shards[shard].get(i18n_id, "")
        raw = (
            raw.replace('\\"', '"')
            .replace("\\n", "\n")
            .replace("\\'", "'")
            .replace("\\\\", "\\")
        )
        return raw.replace("{$br}", "\n").strip()

    @property
    def cv_map(self) -> dict[int, dict[str, Any]]:
        if self._cv is None:
            self._cv = {}
            for p in sorted(self.dir.glob("CfgCVTable_*.lua")):
                if p.name.endswith("_Route.lua"):
                    continue
                for kid, body in parse_lua_flat_table(p).items():
                    sid = re.search(r"SoundID\s*=\s*(\d+)", body)
                    tt = re.search(r"TextTime\s*=\s*([\d.]+)", body)
                    tx = re.search(r"Text\s*=\s*getI18NValue\((\d+)\)", body)
                    self._cv[kid] = {
                        "sound_id": int(sid.group(1)) if sid else None,
                        "text_time": float(tt.group(1)) if tt else None,
                        "text_i18n": int(tx.group(1)) if tx else None,
                    }
        return self._cv

    @property
    def sound_map(self) -> dict[int, str]:
        if self._sound is None:
            self._sound = {}
            for p in sorted(self.dir.glob("CfgSoundTable_*.lua")):
                if p.name.endswith("_Route.lua"):
                    continue
                for kid, body in parse_lua_flat_table(p).items():
                    fn = re.search(r'FileName\s*=\s*"([^"]+)"', body)
                    if fn:
                        self._sound[kid] = fn.group(1)
        return self._sound

    @property
    def action_map(self) -> dict[int, dict[str, Any]]:
        if self._actions is None:
            self._actions = {}
            for p in sorted(self.dir.glob("CfgSoulActionTable_*.lua")):
                if p.name.endswith("_Route.lua"):
                    continue
                for kid, body in parse_lua_flat_table(p).items():
                    ba = re.search(r'BodyAction\s*=\s*"([^"]+)"', body)
                    cv = re.search(r'CV\s*=\s*"([^"]+)"', body)
                    an = re.search(r"ActionName\s*=\s*getI18NValue\((\d+)\)", body)
                    sid = re.search(r"SoulId\s*=\s*(\d+)", body)
                    face = re.search(r'FaceAction\s*=\s*"([^"]+)"', body)
                    self._actions[kid] = {
                        "id": kid,
                        "body_action": ba.group(1) if ba else "",
                        "face_action": face.group(1) if face else "",
                        "cv": int(cv.group(1)) if cv and cv.group(1).isdigit() else None,
                        "action_name_id": int(an.group(1)) if an else None,
                        "soul_id": int(sid.group(1)) if sid else None,
                    }
        return self._actions

    @property
    def action_groups(self) -> dict[int, str]:
        if self._action_groups is None:
            self._action_groups = {}
            for p in sorted(self.dir.glob("CfgSoulActionGroupTable_*.lua")):
                if p.name.endswith("_Route.lua"):
                    continue
                self._action_groups.update(parse_lua_flat_table(p))
        return self._action_groups

    @property
    def spine_control(self) -> dict[int, str]:
        if self._spine_ctrl is None:
            self._spine_ctrl = parse_lua_flat_table(self.dir / "CfgSoulSpineActionControlTable.lua")
        return self._spine_ctrl

    @property
    def spine_actions(self) -> dict[int, str]:
        if self._spine_actions is None:
            self._spine_actions = parse_lua_flat_table(self.dir / "CfgSoulSpineActionTable.lua")
        return self._spine_actions

    def resolve_cv(self, cv_id: int | None) -> dict[str, Any]:
        """Return sound filename (stem + relpath), text, and duration ms for a CV ID."""
        if not cv_id or cv_id not in self.cv_map:
            return {"sound_rel": "", "sound_stem": "", "text": "", "duration_ms": 4000}
        entry = self.cv_map[cv_id]
        snd_rel = self.sound_map.get(entry["sound_id"] or -1, "")
        txt = self.get_i18n(entry["text_i18n"])
        dur_s = entry["text_time"] or 4.0
        return {
            "sound_rel": snd_rel,
            "sound_stem": Path(snd_rel).stem if snd_rel else "",
            "text": txt,
            "duration_ms": max(3000, int(round(dur_s * 1000)) + 500),
        }
