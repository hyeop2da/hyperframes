#!/usr/bin/env python3
"""먼작귀 3종 프레임 만들기.

1) 12포즈 시트(sprite_sheet_poses.png, 4열×3행: 기본/집중/휴식/응원 × 치이카와/하치와레/우사기)
2) 키보드 치는 컷 — 두 장의 시트에서 캐릭터별로 모은다
     sprite_sheet_typing.png : 치이카와 (11·12행)
     sprite_sheet_hu.png     : 하치와레 (3·11·12행), 우사기 (6·11행)
출력 : frames/poses/<캐릭터>_<포즈>.png, frames/poses/<캐릭터>_type<NN>.png, manifest.json

* 격자로 자르지 않고 투영으로 덩어리를 찾아 자른다(귀·응원선·김·책상이 잘리지 않도록).
* 모든 컷을 같은 캔버스에 '발끝(책상 아래) 기준선 · 몸통 가로 중심'으로 맞춘다.
* 캐릭터별로 기본 포즈와 머리 폭을 맞춰 크기를 보정한다(기존 치이카와와도 일치).
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
POSE_SHEET = HERE / "sprite_sheet_poses.png"
TYPING_SHEET = HERE / "sprite_sheet_typing.png"
HU_SHEET = HERE / "sprite_sheet_hu.png"
LEGACY_REF = HERE / "frames" / "r01_c01.png"
OUT = HERE / "frames" / "poses"

def remove_stray(arr):
    """말풍선 그림에서 딸려 온 작은 조각(머리 위 '…' 점선, 1~3픽셀 먼지)을 지운다. 몸통(가장 큰 덩어리)은 그대로 둔다."""
    from collections import deque
    a = arr[:, :, 3] > 10
    h, w = a.shape
    seen = np.zeros((h, w), bool)
    comps = []
    for y in range(h):
        for x in range(w):
            if a[y, x] and not seen[y, x]:
                q, pts = deque([(y, x)]), []
                seen[y, x] = True
                while q:
                    cy, cx = q.popleft()
                    pts.append((cy, cx))
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and a[ny, nx] and not seen[ny, nx]:
                                seen[ny, nx] = True
                                q.append((ny, nx))
                comps.append(pts)
    if len(comps) < 2:
        return arr
    comps.sort(key=len, reverse=True)
    top = min(p[0] for p in comps[0])
    out = arr.copy()
    for pts in comps[1:]:
        if (len(pts) < 250 and max(p[0] for p in pts) < top) or len(pts) <= 3:
            for y, x in pts:
                out[y, x, 3] = 0
    return out


CHARS = ["chiikawa", "hachiware", "usagi"]
POSES = ["base", "focus", "rest", "cheer"]
GAP, ALPHA_MIN, MARGIN = 8, 20, 6
BG_MAX, BLANK_MAX, BLOB_GAP = 22, 20, 5

# 키보드 컷: (시트, 행(1부터), 열 목록(1부터), 바쁜 컷 여부 목록)  — 바쁜 컷 = 진동선·몸을 숙임·손동작 표시가 있는 컷
TYPING_SOURCES = {
    "chiikawa": [("typing", 11, [1, 2, 3, 4, 5, 6], [0, 0, 0, 1, 1, 1]), ("typing", 12, [1, 2], [1, 1])],
    "hachiware": [("hu", 3, [1, 2, 3, 4], [0, 0, 0, 0]), ("hu", 11, [1, 2], [0, 0]), ("hu", 12, [1, 2], [1, 1])],
    "usagi": [("hu", 6, [1, 2, 3, 4, 5, 6], [0, 0, 0, 0, 1, 1]), ("hu", 11, [3, 4, 5], [0, 0, 0])],
}

# 쉬는 동안의 동작에 쓸 컷: (출처, 행, 열 목록).  출처 'legacy' = 기존 치이카와 프레임(frames/rNN_cNN.png)
IDLE_SOURCES = {
    "chiikawa": [("legacy", 1, [1, 2, 3, 5]), ("legacy", 2, [2, 3, 4, 5, 6, 7])],
    "hachiware": [("hu", 1, [1, 2, 3, 4, 5, 6]), ("hu", 2, [1, 2, 3, 4, 5, 6])],
    "usagi": [("hu", 5, [1, 2, 3, 4, 5, 6]), ("hu", 4, [4, 5, 6])],
}


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
    """머리 폭: 키의 위쪽 60% 안에서 가장 넓은 가로 폭(책상·팔이 있어도 머리가 가장 넓다)."""
    x0, y0, x1, y1 = bbox(a)
    best = 0
    for y in range(y0, y0 + int((y1 - y0) * 0.60)):
        xs = np.nonzero(a[y] > 40)[0]
        if len(xs):
            best = max(best, int(xs[-1] - xs[0] + 1))
    return best


def flood_from_border(mask):
    reach = np.zeros_like(mask)
    reach[0, :], reach[-1, :], reach[:, 0], reach[:, -1] = mask[0, :], mask[-1, :], mask[:, 0], mask[:, -1]
    while True:
        g = reach.copy()
        g[1:, :] |= reach[:-1, :]
        g[:-1, :] |= reach[1:, :]
        g[:, 1:] |= reach[:, :-1]
        g[:, :-1] |= reach[:, 1:]
        g &= mask
        if g.sum() == reach.sum():
            return g
        reach = g


def black_to_alpha(cell):
    """검은 배경 시트: 칸 가장자리와 이어진 어두운 배경만 투명하게(윤곽선·눈동자는 보존)."""
    mx = cell.max(axis=2)
    bg = flood_from_border(mx <= BG_MAX)
    alpha = np.where(bg, 0, 255).astype(np.float32)
    ring = bg.copy()
    for _ in range(2):
        g = ring.copy()
        g[1:, :] |= ring[:-1, :]
        g[:-1, :] |= ring[1:, :]
        g[:, 1:] |= ring[:, :-1]
        g[:, :-1] |= ring[:, 1:]
        ring = g
    edge = ring & ~bg
    soft = np.clip((mx.astype(np.float32) - 6.0) / 42.0, 0.0, 1.0) * 255.0
    alpha[edge] = np.minimum(alpha[edge], soft[edge])
    return np.dstack([cell, alpha.astype(np.uint8)]).astype(np.uint8)


def row_bands_dark(mx):
    blank = (mx < BLANK_MAX).all(axis=1)
    return bands(~blank, 0)


def dark_rows(path):
    """검은 배경 시트 → {행(1부터): (y0, y1)}, RGB 배열."""
    rgb = np.array(Image.open(path).convert("RGB"))
    rows = row_bands_dark(rgb.max(axis=2))
    return rgb, {i + 1: r for i, r in enumerate(rows)}


def scale_img(arr, factor):
    im = Image.fromarray(arr, "RGBA").convert("RGBa")               # 알파 곱 상태로 리사이즈(번짐 방지)
    im = im.resize((max(1, round(arr.shape[1] * factor)), max(1, round(arr.shape[0] * factor))), Image.LANCZOS)
    return np.array(im.convert("RGBA"))


def trim(a):
    x0, y0, x1, y1 = bbox(a[:, :, 3])
    a = a[y0:y1, x0:x1]
    h = a.shape[0]
    ys, xs = np.nonzero(a[int(h * 0.40):, :, 3] > 128)
    return a, (float(xs.mean()) if len(xs) else a.shape[1] / 2)


def main() -> int:
    if not POSE_SHEET.exists():
        print(f"[안내] {POSE_SHEET.name} 가 없어 포즈 분리를 건너뜁니다.")
        return 0
    rgba = np.array(Image.open(POSE_SHEET).convert("RGBA"))
    alpha = rgba[:, :, 3]
    rows = bands((alpha > ALPHA_MIN).any(axis=1))
    if len(rows) != len(CHARS):
        print(f"[오류] 포즈 시트에서 행 {len(CHARS)}개를 예상했지만 {len(rows)}개: {rows}")
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
    factor = 1.0
    if LEGACY_REF.exists():
        ref = np.array(Image.open(LEGACY_REF))[:, :, 3]
        factor = head_width(ref) / head_width(crops[("chiikawa", "base")][:, :, 3])
    print(f"포즈 크기 보정 배율: {factor:.3f}")
    items = {}      # 이름 → (배열, 중심 x)
    for (ch, pose), arr in crops.items():
        items[f"{ch}_{pose}"] = trim(scale_img(arr, factor))
    base_head = {ch: head_width(items[f"{ch}_base"][0][:, :, 3]) for ch in CHARS}

    # 키보드 컷
    sheets = {}
    for key, path in (("typing", TYPING_SHEET), ("hu", HU_SHEET)):
        if path.exists():
            sheets[key] = dark_rows(path)
    typing_meta = {ch: [] for ch in CHARS}
    for ch, sources in TYPING_SOURCES.items():
        n, tfactor = 0, None
        for sheet_key, row, cols, busy in sources:
            if sheet_key not in sheets:
                print(f"[안내] {sheet_key} 시트가 없어 {ch} 키보드 컷 일부를 건너뜁니다.")
                continue
            rgb, rmap = sheets[sheet_key]
            y0, y1 = rmap[row]
            y0 = max(0, y0 - 10)
            blobs = []
            colmask = (rgb[y0:y1].max(axis=2) > BG_MAX).any(axis=0)
            blobs = bands(colmask, BLOB_GAP)
            for c, b in zip(cols, busy):
                if c > len(blobs):
                    print(f"[오류] {sheet_key} {row}행 {c}번 컷을 찾을 수 없습니다 (덩어리 {len(blobs)}개)")
                    return 1
                x0, x1 = blobs[c - 1]
                cell = black_to_alpha(rgb[y0:y1, max(0, x0 - 6):min(rgb.shape[1], x1 + 6)])
                if tfactor is None:                       # 이 캐릭터의 첫 컷으로 크기 보정 배율 결정
                    tfactor = base_head[ch] / head_width(cell[:, :, 3])
                    print(f"{ch} 키보드 컷 크기 보정 배율: {tfactor:.3f}")
                n += 1
                items[f"{ch}_type{n:02d}"] = trim(scale_img(cell, tfactor))
                typing_meta[ch].append({"name": f"{ch}_type{n:02d}", "busy": bool(b)})

    # 쉬는 동작 컷
    idle_meta = {ch: [] for ch in CHARS}
    for ch, sources in IDLE_SOURCES.items():
        n, ifactor = 0, None
        for src, row, cols in sources:
            if src == "legacy":
                files = [HERE / "frames" / f"r{row:02d}_c{c:02d}.png" for c in cols]
                if not all(f.exists() for f in files):
                    print(f"[안내] 기존 치이카와 프레임이 없어 {ch} 쉬는 컷 일부를 건너뜁니다.")
                    continue
                cells = [np.array(Image.open(f).convert("RGBA")) for f in files]
            else:
                if src not in sheets:
                    print(f"[안내] {src} 시트가 없어 {ch} 쉬는 컷 일부를 건너뜁니다.")
                    continue
                rgb, rmap = sheets[src]
                y0, y1 = rmap[row]
                y0 = max(0, y0 - 10)
                blobs = bands((rgb[y0:y1].max(axis=2) > BG_MAX).any(axis=0), BLOB_GAP)
                cells = []
                for c in cols:
                    if c > len(blobs):
                        print(f"[오류] {src} {row}행 {c}번 컷을 찾을 수 없습니다 (덩어리 {len(blobs)}개)")
                        return 1
                    x0, x1 = blobs[c - 1]
                    cells.append(black_to_alpha(rgb[y0:y1, max(0, x0 - 6):min(rgb.shape[1], x1 + 6)]))
            for cell in cells:
                if ifactor is None:
                    ifactor = base_head[ch] / head_width(cell[:, :, 3])
                    print(f"{ch} 쉬는 컷 크기 보정 배율: {ifactor:.3f}")
                n += 1
                items[f"{ch}_idle{n:02d}"] = trim(scale_img(cell, ifactor))
                idle_meta[ch].append(f"{ch}_idle{n:02d}")

    # 모든 컷을 같은 캔버스에 맞춘다(발끝 기준선 · 몸통 가로 중심)
    half = max(max(cx, a.shape[1] - cx) for a, cx in items.values())
    height = max(a.shape[0] for a, _ in items.values())
    W = int(round(half * 2)) + 2 * MARGIN
    H = height + MARGIN + 2
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):
        if not old.name.startswith("_"):
            old.unlink()
    manifest = {"canvas": [W, H], "baseline": H - 2, "scale": round(factor, 4), "poses": {}, "typing": typing_meta, "idle": idle_meta}
    for name, (a, cx) in items.items():
        ox, oy = int(round(W / 2 - cx)), (H - 2) - a.shape[0]
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        canvas.alpha_composite(Image.fromarray(remove_stray(a), "RGBA"), (ox, oy))
        canvas.save(OUT / f"{name}.png", optimize=True)
        manifest["poses"][name] = {"bbox": [ox, oy, ox + a.shape[1], oy + a.shape[0]]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"캔버스 {W}x{H}, 포즈 {len(POSES) * len(CHARS)}개, 키보드 컷 " +
          ", ".join(f"{ch} {len(v)}개" for ch, v in typing_meta.items()) + ", 쉬는 컷 " +
          ", ".join(f"{ch} {len(v)}개" for ch, v in idle_meta.items()))

    # 확인용 미리보기(밝은 배경 + 기준선): 캐릭터마다 3줄 = 포즈 / 키보드 컷 / 쉬는 컷
    from PIL import ImageDraw
    cols_n = max(len(POSES), max(len(v) for v in typing_meta.values()), max(len(v) for v in idle_meta.values()))
    prev = Image.new("RGBA", (W * cols_n, H * 9), (206, 224, 238, 255))
    d = ImageDraw.Draw(prev)
    for ci, ch in enumerate(CHARS):
        for pi, pose in enumerate(POSES):
            prev.alpha_composite(Image.open(OUT / f"{ch}_{pose}.png"), (pi * W, ci * 3 * H))
        for ti, t in enumerate(typing_meta[ch]):
            prev.alpha_composite(Image.open(OUT / f"{t['name']}.png"), (ti * W, (ci * 3 + 1) * H))
        for ti, name in enumerate(idle_meta[ch]):
            prev.alpha_composite(Image.open(OUT / f"{name}.png"), (ti * W, (ci * 3 + 2) * H))
    for r in range(9):
        d.line([(0, r * H + H - 2), (W * cols_n, r * H + H - 2)], fill=(255, 80, 80, 255), width=1)
    prev.convert("RGB").save(OUT / "_preview.png")
    print("완료 →", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
