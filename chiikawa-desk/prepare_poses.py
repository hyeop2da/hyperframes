#!/usr/bin/env python3
"""먼작귀 3종 × 4포즈(기본/집중/휴식/응원) 시트 → 개별 투명 PNG.

입력 : sprite_sheet_poses.png  (4열 × 3행, 행 = 치이카와/하치와레/우사기, 열 = 기본/집중/휴식/응원)
출력 : frames/poses/<캐릭터>_<포즈>.png  + frames/poses/manifest.json

* 격자로 자르지 않고 투영으로 덩어리를 찾아 자른다(귀·응원선·김이 잘리지 않도록).
* 모든 포즈를 같은 캔버스에 '발끝 기준선·몸통 가로 중심'으로 맞춘다.
* 기존 치이카와(frames/r01_c01.png)와 머리 폭을 맞춰 크기를 보정한다.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SHEET = HERE / "sprite_sheet_poses.png"
LEGACY_REF = HERE / "frames" / "r01_c01.png"
OUT = HERE / "frames" / "poses"

CHARS = ["chiikawa", "hachiware", "usagi"]
POSES = ["base", "focus", "rest", "cheer"]
GAP = 8            # 이 폭 이상 비어 있으면 서로 다른 덩어리
ALPHA_MIN = 20
MARGIN = 6


def bands(flags, gap=GAP):
    out, start, last = [], None, None
    for i, on in enumerate(flags):
        if on:
            if start is None:
                start = i
            last = i
        elif start is not None and i - last > gap:
            out.append((start, last + 1))
            start = None
    if start is not None:
        out.append((start, last + 1))
    return out


def bbox(a, thr=8):
    ys, xs = np.nonzero(a > thr)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def head_width(a):
    """머리 부근(키의 12~40%) 가로 폭 — 포즈 효과선이 없는 '기본' 포즈에서 잰다."""
    x0, y0, x1, y1 = bbox(a)
    h = y1 - y0
    best = 0
    for y in range(y0 + int(h * 0.12), y0 + int(h * 0.40)):
        xs = np.nonzero(a[y] > 40)[0]
        if len(xs):
            best = max(best, int(xs[-1] - xs[0] + 1))
    return best


def main() -> int:
    if not SHEET.exists():
        print(f"[안내] {SHEET.name} 가 없어 포즈 분리를 건너뜁니다.")
        return 0
    rgba = np.array(Image.open(SHEET).convert("RGBA"))
    alpha = rgba[:, :, 3]
    rows = bands((alpha > ALPHA_MIN).any(axis=1))
    if len(rows) != len(CHARS):
        print(f"[오류] 행 {len(CHARS)}개를 예상했지만 {len(rows)}개: {rows}")
        return 1

    crops = {}
    for ci, (y0, y1) in enumerate(rows):
        cols = bands((alpha[y0:y1] > ALPHA_MIN).any(axis=0))
        if len(cols) != len(POSES):
            print(f"[오류] {CHARS[ci]} 행: 덩어리 {len(POSES)}개를 예상했지만 {len(cols)}개: {cols}")
            return 1
        for pi, (x0, x1) in enumerate(cols):
            crops[(CHARS[ci], POSES[pi])] = rgba[y0:y1, x0:x1]

    # 기존 치이카와와 머리 폭 맞추기
    base = crops[("chiikawa", "base")]
    factor = 1.0
    if LEGACY_REF.exists():
        ref = np.array(Image.open(LEGACY_REF))[:, :, 3]
        factor = head_width(ref) / head_width(base[:, :, 3])
    print(f"크기 보정 배율: {factor:.3f}")

    scaled = {}
    for key, arr in crops.items():
        im = Image.fromarray(arr, "RGBA").convert("RGBa")          # 알파 곱 상태로 리사이즈(번짐 방지)
        im = im.resize((max(1, round(arr.shape[1] * factor)), max(1, round(arr.shape[0] * factor))), Image.LANCZOS)
        scaled[key] = np.array(im.convert("RGBA"))

    # 프레임별: 투명 여백을 잘라내고 몸통 중심(아래 60% 질량 중심)과 발끝을 구한다
    trimmed = {}
    for key, a in scaled.items():
        x0, y0, x1, y1 = bbox(a[:, :, 3])
        a = a[y0:y1, x0:x1]
        al = a[:, :, 3]
        h = a.shape[0]
        ys, xs = np.nonzero(al[int(h * 0.40):] > 128)
        trimmed[key] = (a, float(xs.mean()) if len(xs) else a.shape[1] / 2)

    half = max(max(cx, a.shape[1] - cx) for a, cx in trimmed.values())
    height = max(a.shape[0] for a, _ in trimmed.values())
    W = int(round(half * 2)) + 2 * MARGIN
    H = height + MARGIN + 2
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"canvas": [W, H], "baseline": H - 2, "scale": round(factor, 4), "poses": {}}
    for (ch, pose), (a, cx) in trimmed.items():
        ox = int(round(W / 2 - cx))
        oy = (H - 2) - a.shape[0]
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.alpha_composite(Image.fromarray(a, "RGBA"), (ox, oy))
        canvas.save(OUT / f"{ch}_{pose}.png", optimize=True)
        manifest["poses"][f"{ch}_{pose}"] = {"bbox": [ox, oy, ox + a.shape[1], oy + a.shape[0]]}
        print(f"{ch:10s} {pose:6s} → {W}x{H}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 확인용 미리보기(밝은 배경 + 기준선)
    prev = Image.new("RGBA", (W * 4, H * 3), (206, 224, 238, 255))
    from PIL import ImageDraw
    d = ImageDraw.Draw(prev)
    for ci, ch in enumerate(CHARS):
        for pi, pose in enumerate(POSES):
            prev.alpha_composite(Image.open(OUT / f"{ch}_{pose}.png"), (pi * W, ci * H))
        d.line([(0, ci * H + H - 2), (W * 4, ci * H + H - 2)], fill=(255, 80, 80, 255), width=1)
        for pi in range(4):
            d.line([(pi * W + W // 2, ci * H), (pi * W + W // 2, ci * H + H)], fill=(80, 120, 255, 120), width=1)
    prev.convert("RGB").save(OUT / "_preview.png")
    print("완료 →", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
