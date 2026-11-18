#!/usr/bin/env python3
"""스프라이트 시트 → 프레임 PNG(배경 투명) 분리 스크립트.

- 시트는 가로 7칸 × 세로 11행. 행 사이의 검은 여백으로 행 경계를 자동 검출합니다.
- 각 칸의 가장자리와 이어진 '검은 배경'만 투명하게 만듭니다(윤곽선·눈동자는 보존).
- 결과: frames/rNN_cNN.png (행·열 모두 1부터), frames/manifest.json
- 확인용: frames/_preview.png (밝은 회색 배경 위 미리보기)
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SHEET = HERE / "sprite_sheet.png"
OUT = HERE / "frames"

COLS = 7
ROWS = 11
# 1~3행은 7칸 격자, 4~11행은 6칸 격자로 배치되어 있음
COLS_BY_ROW = [7, 7, 7, 6, 6, 6, 6, 6, 6, 6, 6]
BG_MAX = 22        # 이 밝기 이하의 어두운 픽셀을 '배경 후보'로 본다
BLANK_MAX = 20     # 행 경계 검출용
PAD = 10           # 행 위쪽 여유 픽셀
PAD_BOTTOM = 2     # 아래쪽은 거의 붙임(바닥/책상에 딱 앉도록)
# 엎드린 포즈가 칸 경계를 넘어가는 행은 격자 대신 '캐릭터 덩어리' 단위로 자른다
BLOB_ROWS = {3}
BLOB_GAP = 5       # 이 폭 이상 비어 있으면 서로 다른 캐릭터
BLOB_MARGIN = 6


def find_row_bands(mx: np.ndarray):
    blank = (mx < BLANK_MAX).all(axis=1)
    bands, start = [], None
    for y, b in enumerate(blank):
        if not b and start is None:
            start = y
        elif b and start is not None:
            bands.append((start, y))
            start = None
    if start is not None:
        bands.append((start, len(blank)))
    return bands


def blob_ranges(band: np.ndarray):
    """행 밴드의 열 투영으로 캐릭터 덩어리의 (시작, 끝) x 범위를 찾는다."""
    col = (band.max(axis=2) > BG_MAX).any(axis=0)
    out, start, last = [], None, None
    for x, on in enumerate(col):
        if on:
            if start is None:
                start = x
            last = x
        elif start is not None and x - last > BLOB_GAP:
            out.append((start, last + 1))
            start = None
    if start is not None:
        out.append((start, last + 1))
    return out


def flood_from_border(mask: np.ndarray) -> np.ndarray:
    """mask(True=어두움) 중 이미지 테두리와 연결된 영역만 반환."""
    h, w = mask.shape
    reach = np.zeros_like(mask)
    reach[0, :] = mask[0, :]
    reach[-1, :] |= mask[-1, :]
    reach[:, 0] |= mask[:, 0]
    reach[:, -1] |= mask[:, -1]
    while True:
        grown = reach.copy()
        grown[1:, :] |= reach[:-1, :]
        grown[:-1, :] |= reach[1:, :]
        grown[:, 1:] |= reach[:, :-1]
        grown[:, :-1] |= reach[:, 1:]
        grown &= mask
        if grown.sum() == reach.sum():
            return grown
        reach = grown


def cell_to_rgba(cell: np.ndarray) -> np.ndarray:
    mx = cell.max(axis=2)
    bg = flood_from_border(mx <= BG_MAX)
    alpha = np.where(bg, 0, 255).astype(np.float32)

    # 배경과 맞닿은 1~2px 경계는 밝기에 따라 부드럽게 (검은 테두리 헤일로 방지)
    ring = bg.copy()
    for _ in range(2):
        g = ring.copy()
        g[1:, :] |= ring[:-1, :]
        g[:-1, :] |= ring[1:, :]
        g[:, 1:] |= ring[:, :-1]
        g[:, :-1] |= ring[:, 1:]
        ring = g
    edge = ring & ~bg
    soft = np.clip((mx.astype(np.float32) - 6.0) / (48.0 - 6.0), 0.0, 1.0) * 255.0
    alpha[edge] = np.minimum(alpha[edge], soft[edge])
    # 부드러운 경계가 너무 연해지지 않도록 하한
    alpha[edge] = np.maximum(alpha[edge], 0)

    return np.dstack([cell, alpha.astype(np.uint8)]).astype(np.uint8)


# ── 키보드 치는 포즈 시트 (두 번째 시트) ─────────────────────────────────
TYPING_SHEET = HERE / "sprite_sheet_typing.png"
TYPING_SRC_ROWS = (11, 12)   # 이 시트의 11·12행이 타이핑 포즈
TYPING_COLS = (6, 5)         # 각 행의 프레임 수
# 출력 행 번호: 12 = 타이핑 기본(6칸), 13 = 타이핑 변주(5칸)
# 말풍선 그림이 박혀 있는 컷(13행 3·4번)은 쓰지 않는다
TYPING_SKIP = {13: {3, 4}}


def head_width(rgba: np.ndarray, y_from: int = 30, y_to: int = 80) -> int:
    """머리 부근 가로 폭 (두 시트의 캐릭터 크기를 맞추는 기준)."""
    a = rgba[:, :, 3] > 40
    ys = np.nonzero(a.any(axis=1))[0]
    top = int(ys[0])
    best = 0
    for y in range(top + y_from, min(a.shape[0], top + y_to)):
        xs = np.nonzero(a[y])[0]
        if len(xs):
            best = max(best, int(xs[-1] - xs[0] + 1))
    return best


def add_typing_rows(manifest) -> int:
    if not TYPING_SHEET.exists():
        print(f"[안내] {TYPING_SHEET.name} 가 없어 타이핑 프레임은 건너뜁니다.")
        return 0
    sheet = np.array(Image.open(TYPING_SHEET).convert("RGB"))
    H, W = sheet.shape[:2]
    bands = find_row_bands(sheet.max(axis=2))
    if len(bands) < max(TYPING_SRC_ROWS):
        print(f"[오류] 타이핑 시트에서 행 {len(bands)}개만 찾았습니다.")
        return 1
    ref_w = head_width(np.array(Image.open(OUT / "r01_c01.png")))
    scale = None
    for k, (src_row, ncols) in enumerate(zip(TYPING_SRC_ROWS, TYPING_COLS)):
        out_row = ROWS + 1 + k
        y0, y1 = bands[src_row - 1]
        y0, y1 = max(0, y0 - PAD), min(H, y1 + PAD_BOTTOM)
        blobs = blob_ranges(sheet[y0:y1])
        if len(blobs) != ncols:
            print(f"[오류] 타이핑 {src_row}행: 덩어리 {ncols}개 예상, {len(blobs)}개 발견 {blobs}")
            return 1
        raws = [cell_to_rgba(sheet[y0:y1, max(0, a - BLOB_MARGIN):min(W, b + BLOB_MARGIN)]) for a, b in blobs]
        if scale is None:
            scale = ref_w / head_width(raws[0])
            print(f"타이핑 프레임 크기 보정 배율: {scale:.3f}")
        imgs = []
        for r in raws:
            im = Image.fromarray(r, "RGBA").convert("RGBa")        # 알파 곱 상태로 리사이즈(테두리 번짐 방지)
            im = im.resize((round(r.shape[1] * scale), round(r.shape[0] * scale)), Image.LANCZOS).convert("RGBA")
            imgs.append(im)
        skip = TYPING_SKIP.get(out_row, set())
        kept = [(c, im) for c, im in enumerate(imgs, start=1) if c not in skip]
        cw = max(im.width for _, im in kept)
        # 사용하는 컷들만 기준으로 위쪽 빈 공간을 잘라낸다
        top = min(im.getchannel("A").getbbox()[1] for _, im in kept)
        h = imgs[0].height - top
        for c, im in kept:
            canvas = Image.new("RGBA", (cw, h), (0, 0, 0, 0))
            canvas.paste(im.crop((0, top, im.width, im.height)), ((cw - im.width) // 2, 0))
            canvas.save(OUT / f"r{out_row:02d}_c{c:02d}.png")
        manifest["rows"].append({"row": out_row, "frames": ncols, "w": cw, "h": h})
        print(f"행 {out_row:2d}: 프레임 {ncols}개, 크기 {cw}x{h}  (타이핑 시트 {src_row}행)")
    return 0


def main() -> int:
    if not SHEET.exists():
        print(f"[오류] {SHEET.name} 파일이 없습니다.")
        return 1
    OUT.mkdir(exist_ok=True)
    sheet = np.array(Image.open(SHEET).convert("RGB"))
    mx = sheet.max(axis=2)
    H, W = mx.shape

    bands = find_row_bands(mx)
    if len(bands) != ROWS:
        print(f"[오류] 행 {ROWS}개를 예상했지만 {len(bands)}개를 찾았습니다: {bands}")
        return 1

    manifest = {"rows": []}
    for r, (y0, y1) in enumerate(bands, start=1):
        y0 = max(0, y0 - PAD)
        y1 = min(H, y1 + PAD_BOTTOM)
        frames = 0
        ncols = COLS_BY_ROW[r - 1]
        if r in BLOB_ROWS:
            blobs = blob_ranges(sheet[y0:y1])
            if len(blobs) != ncols:
                print(f"[오류] {r}행에서 덩어리 {ncols}개를 예상했지만 {len(blobs)}개: {blobs}")
                return 1
            cw = max(b - a for a, b in blobs) + 2 * BLOB_MARGIN
            cells = [(a - BLOB_MARGIN, b + BLOB_MARGIN) for a, b in blobs]
            x1 = x0 = 0
            x1 = cw
        else:
            col_edges = [round(i * W / ncols) for i in range(ncols + 1)]
            cells = [(col_edges[i], col_edges[i + 1]) for i in range(ncols)]
            cw = None
        for c in range(ncols):
            x0, x1 = cells[c]
            cell = sheet[y0:y1, max(0, x0):min(W, x1)]
            rgba = cell_to_rgba(cell)
            if cw is not None:   # 덩어리 행: 폭을 통일한 캔버스 가운데에 배치
                canvas = np.zeros((rgba.shape[0], cw, 4), dtype=np.uint8)
                off = (cw - rgba.shape[1]) // 2
                canvas[:, off:off + rgba.shape[1]] = rgba
                rgba = canvas
            if (rgba[:, :, 3] > 0).sum() < 400:   # 빈 칸
                continue
            Image.fromarray(rgba, "RGBA").save(OUT / f"r{r:02d}_c{c + 1:02d}.png")
            frames = max(frames, c + 1)
        manifest["rows"].append({"row": r, "frames": frames, "w": cw if cw is not None else x1 - x0, "h": y1 - y0})
        print(f"행 {r:2d}: 프레임 {frames}개, 크기 {cw if cw is not None else x1 - x0}x{y1 - y0}")

    if add_typing_rows(manifest):
        return 1

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # 미리보기 (밝은 배경 위에 합성)
    pw = 7 * 220
    ph = sum(r["h"] for r in manifest["rows"])
    prev = Image.new("RGBA", (pw, ph), (200, 220, 235, 255))
    y = 0
    for info in manifest["rows"]:
        for c in range(info["frames"]):
            f = OUT / f"r{info['row']:02d}_c{c + 1:02d}.png"
            if f.exists():
                prev.alpha_composite(Image.open(f), (c * info["w"], y))
        y += info["h"]
    prev.convert("RGB").save(OUT / "_preview.png")
    print("완료 →", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
