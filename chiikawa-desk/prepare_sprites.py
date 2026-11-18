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
PAD = 10           # 행 위아래 여유 픽셀
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
        y1 = min(H, y1 + PAD)
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
