#!/usr/bin/env python3
"""포차코 팩 만들기 — 내 PC 안에서만 실행한다(그림은 저장소·클라우드에 올리지 않는다).

사용:  python prepare_pack.py <포차코 시트 이미지> [--out <팩 폴더>]
  기본 출력 폴더: ~/.chiikawa_desk/packs/pochacco   (프로그램이 시작할 때 여기서 자동으로 불러온다)

* 시트: 검은 배경, 6열 × 12행 스티커 시트(흰 테두리). 열은 같은 간격, 행은 빈 줄로 나눈다.
* 컷을 잘라 배경을 지우고, 먹작귀 컷과 같은 캔버스·기준선·머리 폭 기준으로 맞춘다.
* 키보드 컷은 '책상이 같은 한 묶음'만 쓰고 책상 위치를 맞춰 책상이 움직이지 않게 한다.
* 시트에 그려진 말풍선 조각·먼지는 지운다.
출력: pochacco_<포즈>.png / pochacco_type<NN>.png / pochacco_idle<NN>.png / manifest.json
"""
import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import pack_map as pm  # noqa: E402
import prepare_poses as pp  # noqa: E402  (같은 컷 처리 도구를 재사용)

HOME_DIR = Path(os.environ.get("CHIIKAWA_HOME") or (Path.home() / ".chiikawa_desk"))
DEFAULT_OUT = HOME_DIR / "packs" / "pochacco"                 # (--species 가 pochacco 가 아니면 packs/<이름>)
BUILTIN_DIR = HERE / "frames" / "poses"
COLS = 6


def split_rows(mx):
    """행 띠(y0, y1) 12개. 붙어 있는 두 행은 가장 비어 있는 줄에서 나눈다."""
    blank = (mx < pp.BLANK_MAX).all(axis=1)
    rows = pp.bands(~blank, 0)
    out = []
    for y0, y1 in rows:
        if y1 - y0 > 240:                       # 두 행이 붙은 띠
            prof = (mx[y0:y1] >= pp.BLANK_MAX).sum(axis=1).astype(float)
            lo, hi = int((y1 - y0) * 0.35), int((y1 - y0) * 0.65)
            cut = y0 + lo + int(np.argmin(prof[lo:hi]))
            out += [(y0, cut), (cut, y1)]
        else:
            out.append((y0, y1))
    return out


def split_cols(mx, y0, y1, mn=None):
    """열 구간 [(x0, x1), ...]. 빈 세로줄로 나누고, 테두리가 붙어 있는 덩어리는 폭에 맞춰 같은 간격 근처에서 나눈다.
    나눌 곳은 '그림'(흰 테두리가 아닌 픽셀)이 가장 적은 세로줄 — 이웃 컷의 귀가 걸쳐 있어도 귀가 잘리지 않는다."""
    W = mx.shape[1]
    occ = (mx[y0:y1] >= pp.BLANK_MAX).sum(axis=0)
    blobs = pp.bands(occ > 1, 3)
    if mn is not None:
        sub_mx, sub_mn = mx[y0:y1], mn[y0:y1]
        art = ((sub_mx >= 40) & ~((sub_mn >= 190) & ((sub_mx - sub_mn) <= 40))).sum(axis=0)
        occ = art * 4 + occ
    unit = W / COLS                                           # 한 컷의 보통 폭(전체 너비 ÷ 6)
    out = []
    for x0, x1 in blobs:
        w = x1 - x0
        if w < 40:
            continue
        n = max(1, int(round(w / unit)))
        cuts = [x0]
        for k in range(1, n):
            c = x0 + int(round(w * k / n))
            win = range(max(cuts[-1] + 30, c - 30), min(x1 - 30, c + 30))
            cuts.append(min(win, key=lambda x: occ[x]) if len(win) else c)
        cuts.append(x1)
        out += list(zip(cuts[:-1], cuts[1:]))
    return out


def _label_components(mask):
    """8방향 연결 덩어리 번호표(0 = 없음)와 덩어리별 (x 평균, x 최소, x 최대)."""
    from collections import deque
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    info = {}
    n = 0
    for y in range(h):
        for x in range(w):
            if mask[y, x] and not lab[y, x]:
                n += 1
                q = deque([(y, x)])
                lab[y, x] = n
                xs = []
                while q:
                    cy, cx = q.popleft()
                    xs.append(cx)
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not lab[ny, nx]:
                                lab[ny, nx] = n
                                q.append((ny, nx))
                info[n] = (float(np.mean(xs)), min(xs), max(xs), len(xs))
    return lab, info


def thin_outline_alpha(cell):
    """검은 윤곽선이 검은 배경과 구별되지 않는 시트(키티): 바깥쪽의 가는 회색 띠(스티커 테두리)를 경계로 삼는다.
    1) 띠의 틈을 2px 메우고 바깥 검정을 찾는다  2) 띠 안쪽은 캐릭터  3) 띠 바로 바깥의 검은 여백과 회색 띠를 지운다.
    윤곽선(검정)은 띠 안쪽이라 남는다."""
    mx = cell.max(axis=2)
    mn = cell.min(axis=2)
    barrier = mx > 30
    exterior = pp.flood_from_border(~_dilate(barrier, 2))
    inside = ~exterior
    near_out = _dilate(exterior, 2)
    alpha = inside & ~(near_out & (mx <= 40))                       # 바깥 여백(검정) 제거
    big = np.zeros_like(alpha)
    comps = _components(alpha)
    for pts in comps:
        if len(pts) > 1500:                                          # 몸통 크기의 덩어리에서만 회색 띠를 지운다(작은 효과 그림은 그대로)
            for y, x in pts:
                big[y, x] = True
    ring_like = (mx >= 55) & ((mx - mn) <= 40)
    for _ in range(6):
        edge = alpha & _dilate(~alpha, 1) & big & ring_like
        if not edge.any():
            break
        alpha = alpha & ~edge
    out = np.dstack([cell, np.where(alpha, 255, 0).astype(np.uint8)]).astype(np.uint8)
    return out


def slice_sheet(path, thin=False):
    """{(행, 열): RGBA 배열} — 행·열은 1부터. 빈 칸은 없다.
    이웃 컷의 귀가 옆 칸으로 걸쳐 있어도 잘리지 않게, '그림(윤곽선·색)' 덩어리를 가장 가까운 컷에 배정해 그 컷의 범위를 넓혀서 자른다."""
    rgb = np.array(Image.open(path).convert("RGB"))
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    cells = {}
    for ri, (y0, y1) in enumerate(split_rows(mx), 1):
        cuts = split_cols(mx, y0, y1, mn)
        sub_mx, sub_mn = mx[y0:y1], mn[y0:y1]
        art = (sub_mx >= 40) & ~((sub_mn >= 190) & ((sub_mx - sub_mn) <= 40))
        lab, info = _label_components(_dilate(art))
        centers = [(a + b) / 2.0 for a, b in cuts]
        owner = {i: int(np.argmin([abs(v[0] - c) for c in centers])) for i, v in info.items() if v[3] >= 12}
        for ci, (x0, x1) in enumerate(cuts):
            mine = [i for i, o in owner.items() if o == ci]
            ex0 = min([x0] + [info[i][1] - 3 for i in mine])
            ex1 = max([x1] + [info[i][2] + 4 for i in mine])
            ex0, ex1 = max(0, ex0), min(rgb.shape[1], ex1)
            cell = rgb[y0:y1, ex0:ex1].copy()
            other = np.isin(lab[:, ex0:ex1], [i for i, o in owner.items() if o != ci])
            cell[_dilate(other, 2)] = 0                              # 다른 컷의 그림은 검게 지운다
            if (cell.max(axis=2) >= pp.BLANK_MAX).sum() < 200:
                continue
            a = thin_outline_alpha(cell) if thin else pp.black_to_alpha(cell)
            if (a[:, :, 3] > 40).sum() < 200:
                continue
            a, _ = pp.trim(a)
            cells[(ri, ci + 1)] = a
    return cells


def contact_sheet(cells, out_path, cols=COLS):
    """번호(행,열)를 붙인 확인용 사진."""
    from PIL import ImageDraw
    cw = max(a.shape[1] for a in cells.values()) + 8
    ch = max(a.shape[0] for a in cells.values()) + 22
    rows = max(r for r, _ in cells)
    sheet = Image.new("RGBA", (cw * cols, ch * rows), (200, 205, 215, 255))
    d = ImageDraw.Draw(sheet)
    for (r, c), a in cells.items():
        x, y = (c - 1) * cw, (r - 1) * ch
        sheet.alpha_composite(Image.fromarray(a, "RGBA"), (x + 4, y + 18))
        d.text((x + 4, y + 3), f"{r}-{c}", fill=(160, 0, 0, 255))
    sheet.convert("RGB").save(out_path)


def _components(mask):
    from collections import deque
    h, w = mask.shape
    seen = np.zeros((h, w), bool)
    out = []
    for y in range(h):
        for x in range(w):
            if mask[y, x] and not seen[y, x]:
                q, pts = deque([(y, x)]), []
                seen[y, x] = True
                while q:
                    cy, cx = q.popleft()
                    pts.append((cy, cx))
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = cy + dy, cx + dx
                            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                                seen[ny, nx] = True
                                q.append((ny, nx))
                out.append(pts)
    out.sort(key=len, reverse=True)
    return out


def _dilate(m, n=1):
    for _ in range(n):
        g = m.copy()
        g[1:, :] |= m[:-1, :]
        g[:-1, :] |= m[1:, :]
        g[:, 1:] |= m[:, :-1]
        g[:, :-1] |= m[:, 1:]
        m = g
    return m


def _strip_limited(a, depth=10):
    """(예비) 바깥에서 depth 픽셀 안쪽까지만 흰 픽셀을 지운다."""
    a = a.copy()
    rgb = a[:, :, :3].astype(int)
    mn, mx = rgb.min(axis=2), rgb.max(axis=2)
    whitish = ((mn >= 140) & ((mx - mn) <= 34)) | (((mx - mn) <= 10) & (mn >= 12) & (mn < 140))
    reach = a[:, :, 3] <= 40
    for _ in range(depth):
        grow = _dilate(reach) & ~reach & whitish
        if not grow.any():
            break
        reach |= grow
        a[grow, 3] = 0
    return a


def strip_sticker_border(a, thin=False):
    """스티커 시트의 흰 테두리·흰 바탕을 깔끔하게 지운다.
    그림(짙은 윤곽선·색이 있는 곳)을 장벽으로 보고(틈은 2px 메워서), 바깥에서 이어진 흰 영역을 깊이 제한 없이 지운 뒤
    윤곽선 바로 바깥의 가는 흰 띠(3px)도 지운다. 몸 안쪽의 흰색은 윤곽선에 막혀 그대로 남는다(만약 윤곽선이 크게 열려 몸까지 지워지면 예비 방식으로 되돌린다)."""
    if thin:                                                         # 키티: 배경 처리(thin_outline_alpha)에서 이미 띠를 지웠다
        return a
    pad = np.pad(a, ((1, 1), (1, 1), (0, 0)))                      # 칸 가장자리에 닿은 것도 바깥에서 이어지게
    rgb = pad[:, :, :3].astype(int)
    mn, mx = rgb.min(axis=2), rgb.max(axis=2)
    opaque = pad[:, :, 3] > 40
    whitish = ((mn >= 140) & ((mx - mn) <= 34)) | (((mx - mn) <= 10) & (mn >= 12) & (mn < 140))
    art = opaque & ~whitish
    free = ~_dilate(art, 2)                                          # 그림에서 2px 이상 떨어진 곳(투명 + 흰 바탕)
    exterior = np.zeros_like(free)
    exterior[0, :], exterior[-1, :], exterior[:, 0], exterior[:, -1] = free[0, :], free[-1, :], free[:, 0], free[:, -1]
    while True:
        g = _dilate(exterior) & free
        if g.sum() == exterior.sum():
            break
        exterior = g
    clear = exterior.copy()
    for _ in range(3):                                               # 윤곽선 바로 바깥 2~3px 의 흰 띠
        clear |= _dilate(clear) & whitish & opaque
    out = pad.copy()
    out[clear & opaque, 3] = 0
    before = int((opaque & whitish).sum())
    after = int(((out[:, :, 3] > 40) & whitish).sum())
    if before and after < before * 0.55:                             # 몸 안쪽 흰색이 너무 많이 지워졌다 = 윤곽선이 열려 있다
        return _strip_limited(a)
    return _strip_limited(out[1:-1, 1:-1], depth=8)                  # 좁은 틈에 남은 흰 조각(책상 옆 등)을 한 번 더 정리


def clean_cell(key, a, thin=False):
    """칸 하나 정리: 옆 칸 귀 조각, 말풍선, 먼지를 지운다."""
    a = a.copy()
    h, w = a.shape[:2]
    if key in pm.EDGE_SLIVER:
        for pts in _components(a[:, :, 3] > 40)[1:]:
            xs = [p[1] for p in pts]
            lum = np.mean([a[y, x, :3].mean() for y, x in pts])
            if (min(xs) == 0 or max(xs) == w - 1) and lum < 150 and len(pts) < 2000:
                for y, x in pts:
                    a[y, x, 3] = 0
    if key in pm.BUBBLE_ERASE:
        fx, fy = pm.BUBBLE_ERASE[key]
        a[: int(h * fy), int(w * fx):, 3] = 0
        for pts in _components(a[:, :, 3] > 10)[1:]:               # 풍선 꼬리 조각 같은 떨어진 작은 덩어리
            if len(pts) < 500:
                for y, x in pts:
                    a[y, x, 3] = 0
    a = pp.remove_stray(a)
    a = strip_sticker_border(a, thin)
    a, _ = pp.trim(a)
    return a


def _lower_cx(a):
    ys, xs = np.nonzero(a[int(a.shape[0] * 0.40):, :, 3] > 128)
    return float(xs.mean()) if len(xs) else a.shape[1] / 2.0


def tan_mask(a):
    """책상(갈색) 픽셀."""
    r, g, b = a[:, :, 0].astype(int), a[:, :, 1].astype(int), a[:, :, 2].astype(int)
    return (a[:, :, 3] > 128) & (abs(r - 205) < 38) & (abs(g - 160) < 38) & (abs(b - 105) < 42) & (r > g) & (g > b)


def desk_extent(a):
    """책상으로 볼 수 있는 픽셀의 (ys, xs): 가로로 길게 이어진 줄만 쓴다(귀·옷 가장자리의 비슷한 색은 무시)."""
    m = tan_mask(a)
    rows = np.nonzero(m.sum(axis=1) >= 40)[0]
    sel = np.zeros_like(m)
    sel[rows] = m[rows]
    return np.nonzero(sel)


def fill_notches(a):
    """머리 꼭대기의 작은 홈(귀·머리털 사이)을 메운다: 투명한데 왼쪽·오른쪽·아래가 모두 흰 몸이면 흰색으로 채운다."""
    a = a.copy()
    rgb = a[:, :, :3].astype(int)
    mn, mx = rgb.min(axis=2), rgb.max(axis=2)
    white = (a[:, :, 3] > 200) & (mn >= 215) & ((mx - mn) <= 30)
    h, w = white.shape

    def shifted(m, dy, dx):
        out = np.zeros_like(m)
        ys, ye = max(0, dy), min(h, h + dy)
        xs, xe = max(0, dx), min(w, w + dx)
        out[ys:ye, xs:xe] = m[ys - dy:ye - dy, xs - dx:xe - dx]
        return out

    left = np.zeros_like(white)
    right = np.zeros_like(white)
    below = np.zeros_like(white)
    for k in (1, 2, 3, 4):
        left |= shifted(white, 0, k)
        right |= shifted(white, 0, -k)
        below |= shifted(white, -k, 0)
    hole = (a[:, :, 3] <= 40) & left & right & below
    a[hole] = (255, 255, 255, 255)
    # 머리털 사이 V 홈: 윤곽선이 없는 곳에서 흰 몸이 투명한 바깥과 바로 닿으면, 그 경계에 짙은 갈색 윤곽선(2px)을 그려 준다
    opaque = a[:, :, 3] > 200
    white_now = opaque & (a[:, :, :3].astype(int).min(axis=2) >= 215)
    left2 = np.zeros_like(white)
    right2 = np.zeros_like(white)
    for k in range(1, 15):
        left2 |= shifted(opaque, 0, k)
        right2 |= shifted(opaque, 0, -k)
    near_white = _dilate(white_now, 2)
    notch = (a[:, :, 3] <= 40) & left2 & right2 & near_white
    a[notch] = (66, 40, 36, 255)
    return a


def clip_desk_sides(a):
    """키보드 컷: 책상 높이 이하에서는 책상 가로 범위 밖의 그림(옆에 남은 흰 조각)을 지운다."""
    ys, xs = desk_extent(a)
    a = a.copy()
    top = int(ys.min()) - 3
    a[top:, : int(xs.min()) - 1, 3] = 0
    a[top:, int(xs.max()) + 1:, 3] = 0
    return a


def fit_inside(a, margin=2):
    """그림이 캔버스 가장자리에 닿아 잘리지 않게 가로로 조금 옮긴다."""
    ys, xs = np.nonzero(a[:, :, 3] > 40)
    W = a.shape[1]
    dx = 0
    if xs.min() < margin:
        dx = margin - int(xs.min())
    elif xs.max() > W - 1 - margin:
        dx = (W - 1 - margin) - int(xs.max())
    if dx == 0:
        return a
    out = np.zeros_like(a)
    if dx > 0:
        out[:, dx:] = a[:, :W - dx]
    else:
        out[:, :W + dx] = a[:, -dx:]
    return out


def put(a, cx, bottom, W, H):
    canvas = np.zeros((H, W, 4), np.uint8)
    ox, oy = int(round(W / 2 - cx)), int(bottom - a.shape[0])
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(W, ox + a.shape[1]), min(H, oy + a.shape[0])
    canvas[y0:y1, x0:x1] = a[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    return canvas


def build(sheet, out_dir, builtin=BUILTIN_DIR, species="pochacco"):
    meta = json.loads((Path(builtin) / "manifest.json").read_text(encoding="utf-8"))
    W, H = meta["canvas"]
    ref = np.array(Image.open(Path(builtin) / "chiikawa_base.png").convert("RGBA"))
    thin = species == "kitty"
    cells = {k: clean_cell(k, a, thin) for k, a in slice_sheet(sheet, thin).items()}
    need = set(pm.POSE_CELLS.values()) | {c for c, _ in pm.TYPING_CELLS} | set(pm.IDLE_CELLS)
    missing = sorted(need - set(cells))
    if missing:
        print(f"[오류] 시트에서 칸을 찾지 못했습니다: {missing}")
        return 1
    factor = pp.head_width(ref[:, :, 3]) / pp.head_width(cells[pm.POSE_CELLS["base"]][:, :, 3])
    widest = max(cells[c].shape[1] for c in need) * factor
    if widest > W - 12:                                       # 캔버스에 들어가게
        factor *= (W - 12) / widest
    tallest = max(cells[c].shape[0] for c in need) * factor
    if tallest > H - 6:                                       # 키가 큰 컷(귀)이 위에서 잘리지 않게
        factor *= (H - 6) / tallest
    scaled = {k: pp.scale_img(a, factor) for k, a in cells.items() if k in need}
    baseline = H - 2
    frames = {}
    for pose, cell in pm.POSE_CELLS.items():
        a = scaled[cell]
        frames[f"{species}_{pose}"] = put(a, _lower_cx(a), baseline, W, H)
    desk_bottom = baseline - 3
    typing_meta = []
    for i, (cell, busy) in enumerate(pm.TYPING_CELLS, 1):
        a = scaled[cell]
        ys, xs = desk_extent(a)
        cx = (xs.min() + xs.max()) / 2.0                       # 책상 가운데에 맞춘다(책상이 움직이지 않게)
        shift = desk_bottom - (ys.max() + 1)
        frames[f"{species}_type{i:02d}"] = clip_desk_sides(put(a, cx, a.shape[0] + shift, W, H))
        typing_meta.append({"name": f"{species}_type{i:02d}", "busy": busy})
    idle_names = []
    for cell in pm.IDLE_CELLS:
        a = scaled[cell]
        name = f"{species}_idle{pm.idle(cell):02d}"
        frames[name] = fit_inside(put(a, _lower_cx(a), baseline, W, H))
        idle_names.append(name)
    if not thin:
        frames = {k: fill_notches(v) for k, v in frames.items()}
    # 책상 고정: 첫 컷의 책상을 기준으로 위치를 ±5px 안에서 맞추고, 손이 닿지 않는 아래쪽(앞면·다리)은 기준 컷 그대로 덮는다
    names = [t["name"] for t in typing_meta]
    ref = frames[names[0]]
    ref_mask = tan_mask(ref)
    lo = int(desk_extent(ref)[0].max()) - 28
    band = slice(lo - 60, None)
    for n in names[1:]:
        arr = frames[n]
        best = None
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                m = np.roll(np.roll(tan_mask(arr), dy, axis=0), dx, axis=1)
                d = int((m[band] ^ ref_mask[band]).sum())
                if best is None or d < best[0]:
                    best = (d, dy, dx)
        _, dy, dx = best
        arr = np.roll(np.roll(arr, dy, axis=0), dx, axis=1)
        arr[lo:] = ref[lo:]
        frames[n] = arr
    ext = [desk_extent(frames[n]) for n in names]
    spread = lambda vals: int(max(vals) - min(vals))
    desk_ok = max(spread([e[0].min() for e in ext]), spread([e[1].min() for e in ext]), spread([e[1].max() for e in ext]))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    manifest = {"canvas": [W, H], "baseline": baseline, "scale": round(factor, 4), "poses": {}, "typing": {species: typing_meta},
                "idle": {species: idle_names},
                "tea": {species: [f"{species}_idle{pm.idle(c):02d}" if c != pm.POSE_CELLS["rest"] else f"{species}_rest" for c in pm.TEA_CELLS]},
                "desk_diff": desk_ok}
    for name, arr in frames.items():
        Image.fromarray(arr, "RGBA").save(out_dir / f"{name}.png", optimize=True)
        ys, xs = np.nonzero(arr[:, :, 3] > 10)
        manifest["poses"][name] = {"bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"{species} 팩 {len(frames)}컷 → {out_dir}  (크기 보정 {factor:.3f}, 키보드 컷 {len(typing_meta)}장, 책상 위치 차이 최대 {desk_ok}px)")
    if desk_ok > 6:
        print("[경고] 키보드 컷의 책상이 서로 다릅니다. 시트와 pack_map.py 의 TYPING_CELLS 를 확인하세요.")
        return 2
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="포차코 팩 만들기")
    ap.add_argument("sheet")
    ap.add_argument("--species", default="pochacco", choices=["pochacco", "kitty"], help="캐릭터 이름(팩 폴더 이름)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--contact", help="확인용 번호 사진만 저장하고 끝냄")
    args = ap.parse_args()
    if args.contact:
        contact_sheet({k: clean_cell(k, a, args.species == "kitty") for k, a in slice_sheet(args.sheet, args.species == "kitty").items()}, args.contact)
        print("확인 사진 →", args.contact)
        sys.exit(0)
    sys.exit(build(args.sheet, args.out or str(HOME_DIR / "packs" / args.species), species=args.species))
