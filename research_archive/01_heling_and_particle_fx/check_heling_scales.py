import numpy as np
from PIL import Image
from pathlib import Path

d = Path(r".\_scratch\heling_orig_layers")
out = Path(r".\_scratch")

# Load the 3 raw sprites (at Unity 1.5x scale -> 2550x1700 matching cam=(4.5,-76.5) canvas=(2550,1700)!)
# Wait: check HeLing_S2_Background root scale!
import sys
sys.path.insert(0, r"E:\A灵魂潮汐\tools")
from soultide_common import CDN_ROOT, load_ab
env = load_ab(CDN_ROOT / "03_prefabs" / "art_prefabs.ab")
objs = {o.path_id: o for o in env.objects}
for o in env.objects:
    if o.type.name == "GameObject":
        tt = o.read_typetree()
        if tt.get("m_Name") == "HeLing_S2_Background":
            for c in tt.get("m_Component", []):
                co = objs.get(c["component"]["m_PathID"])
                if co and co.type.name in ("Transform", "RectTransform"):
                    tr = co.read_typetree()
                    if (tr.get("m_Father") or {}).get("m_PathID", 0) == 0:
                        print("ROOT scale:", tr.get("m_LocalScale"), "anch:", tr.get("m_AnchoredPosition"), "sizeDelta:", tr.get("m_SizeDelta"))
                        for ch in tr.get("m_Children", []):
                            ct = objs[ch["m_PathID"]].read_typetree()
                            cg = objs[ct["m_GameObject"]["m_PathID"]].read_typetree()
                            print("  CHILD:", cg["m_Name"], "scale:", ct.get("m_LocalScale"), "anch:", ct.get("m_AnchoredPosition"))
                            for ch2 in ct.get("m_Children", []):
                                ct2 = objs[ch2["m_PathID"]].read_typetree()
                                cg2 = objs[ct2["m_GameObject"]["m_PathID"]].read_typetree()
                                print("    GRANDCHILD:", cg2["m_Name"], "scale:", ct2.get("m_LocalScale"), "anch:", ct2.get("m_AnchoredPosition"), "sizeDelta:", ct2.get("m_SizeDelta"))
