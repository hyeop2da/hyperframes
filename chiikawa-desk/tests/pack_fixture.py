"""시험용 가짜 포차코 팩: 먹작귀 컷을 복사해 pochacco_* 이름으로 만든다(실제 포차코 그림은 저장소에 없다)."""
import json
import shutil
from pathlib import Path

import pack_map as pm

HERE = Path(__file__).resolve().parent.parent
POSES = HERE / "frames" / "poses"


def make_pack(dest, species="pochacco"):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    meta = json.loads((POSES / "manifest.json").read_text(encoding="utf-8"))
    src_idle = [f"chiikawa_idle{i:02d}" for i in range(1, 6)] + ["chiikawa_base", "chiikawa_cheer", "chiikawa_rest", "chiikawa_focus"]
    poses, names = {}, {}

    def add(name, src):
        shutil.copy(POSES / f"{src}.png", dest / f"{name}.png")
        poses[name] = meta["poses"][src]

    for pose in ("base", "focus", "rest", "cheer"):
        add(f"{species}_{pose}", f"chiikawa_{pose}")
    typing = []
    for i, (_, busy) in enumerate(pm.TYPING_CELLS, 1):
        add(f"{species}_type{i:02d}", f"chiikawa_type{i:02d}")
        typing.append({"name": f"{species}_type{i:02d}", "busy": busy})
    idle = []
    for i, cell in enumerate(pm.IDLE_CELLS, 1):
        n = f"{species}_idle{pm.idle(cell):02d}"
        add(n, src_idle[i % len(src_idle)])
        idle.append(n)
    tea = [f"{species}_idle{pm.idle(c):02d}" if c != pm.POSE_CELLS["rest"] else f"{species}_rest" for c in pm.TEA_CELLS]
    manifest = {"canvas": meta["canvas"], "baseline": meta["baseline"], "scale": 1.0, "poses": poses,
                "typing": {species: typing}, "idle": {species: idle}, "tea": {species: tea}}
    (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return dest
