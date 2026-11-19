"""포스트잇 데이터 저장소 (Qt 없음). 내용은 내 PC의 JSON 파일에만 저장한다.

폴드 메모(FoldMemo)의 포스트잇 규칙을 따른다.
  * 색 8가지(옐로·샌드·로즈·오렌지·세이지·스카이·라벤더·그래파이트)
  * 제목은 첫 의미 있는 줄에서 자동으로 만들고(최대 20자), 직접 바꾸면 그 이름을 유지한다
  * 체크리스트: 줄 머리의 ☐ / ☑ (Ctrl+Enter 로 전환)
캐릭터 한 마리가 메모 한 장을 머리 위로 들고 다닌다.
"""
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

UNCHECKED, CHECKED = "☐", "☑"

# 폴드 메모 영상에서 실측한 파스텔 색(RGB)
COLOR_NAMES = ["yellow", "sand", "rose", "orange", "sage", "sky", "lavender", "graphite"]
COLOR_RGB = {
    "yellow": (249, 234, 157), "sand": (226, 214, 192), "rose": (244, 202, 207), "orange": (247, 208, 150),
    "sage": (210, 227, 199), "sky": (194, 218, 238), "lavender": (214, 204, 238), "graphite": (64, 66, 72),
}
COLORS = {k: "#%02X%02X%02X" % v for k, v in COLOR_RGB.items()}
COLOR_LABELS = {"yellow": "옐로", "sand": "샌드", "rose": "로즈", "orange": "오렌지", "sage": "세이지",
                "sky": "스카이", "lavender": "라벤더", "graphite": "그래파이트"}
LEGACY_COLORS = {"pink": "rose", "blue": "sky", "green": "sage", "purple": "lavender"}   # 이전 버전의 색 이름
DEFAULT_OWNER_COLOR = {"chiikawa": "rose", "hachiware": "sky", "usagi": "yellow"}

# 펼친 크기 프리셋 (최소 180×170: 머리줄 + 서식 줄 + 편집 영역)
SIZES = {"작게": (210, 210), "보통": (240, 260), "크게": (300, 340)}
MIN_W, MIN_H, MAX_W, MAX_H = 180, 170, 480, 520
DEFAULT_FONT_SIZE = 11

_MARKER = re.compile(r"^[\s\t]*((☐|☑|□|■|○|●|•|\*|-|\d+[.)]\s|\[[ xX]\])\s*)+")
_OPEN_BOX = re.compile(r"^(☐|□|\[ \]|\[\]|- \[ \])")
_DONE_BOX = re.compile(r"^(☑|■|\[x\]|\[X\]|- \[x\]|- \[X\])")


def normalize_line(line):
    """체크박스·글머리 기호를 뗀 줄(폴드 메모의 정규화 규칙)."""
    s = (line or "").replace("📅", "").replace("️", "").strip()
    return _MARKER.sub("", s).strip()


def derived_title(text, max_chars=20):
    """첫 의미 있는 줄로 만든 제목(최대 20자, 넘으면 …)."""
    for ln in re.split(r"\r\n|\n|\r", text or ""):
        s = normalize_line(ln)
        if not s:
            continue
        return s[:max_chars].strip() + "…" if len(s) > max_chars else s
    return ""


def progress(text):
    """(완료 수, 전체 수) — ☐/☑ 와 같은 뜻의 표기만 센다."""
    done = total = 0
    for ln in re.split(r"\r\n|\n|\r", text or ""):
        s = ln.strip()
        if _OPEN_BOX.match(s):
            total += 1
        elif _DONE_BOX.match(s):
            total += 1
            done += 1
    return done, total


def toggle_checklist_line(line):
    """Ctrl+Enter / 글머리 클릭: ☐ → ☑ → ☐ , 체크박스가 없으면 '☐ ' 를 붙인다(폴드 메모와 같은 규칙)."""
    if line.startswith(UNCHECKED):
        return CHECKED + " " + re.sub(r"^☐\s*", "", line)
    if line.startswith(CHECKED):
        return UNCHECKED + " " + re.sub(r"^☑\s*", "", line)
    return UNCHECKED + " " + line


def display_title(note):
    """머리줄·접은 쪽지에 보일 제목. 글을 쓰지 않았고 직접 짓지도 않았으면 빈 문자열."""
    title = str(note.get("title", "") or "")
    if note.get("title_manual"):
        return title
    if not (note.get("text") or "").strip():
        return ""
    return derived_title(note.get("text", "")) or title


def _clean_runs(runs, text_len):
    """저장된 서식 구간을 검사해 쓸 수 있는 것만 남긴다(글이 달라져 범위를 벗어나면 버린다)."""
    out = []
    if not isinstance(runs, list):
        return out
    for r in runs:
        if not isinstance(r, dict):
            continue
        try:
            start, length = int(r.get("s", -1)), int(r.get("n", 0))
        except (TypeError, ValueError):
            continue
        if start < 0 or length <= 0 or start + length > text_len:
            continue
        keep = {"s": start, "n": length}
        if r.get("f"):
            keep["f"] = str(r["f"])
        if r.get("z"):
            try:
                keep["z"] = max(6.0, min(72.0, float(r["z"])))
            except (TypeError, ValueError):
                pass
        for k in ("b", "i", "k", "u"):                 # 굵게 · 기울임 · 취소선 · 밑줄 (1 = 켬, 0 = 끔)
            if k in r:
                keep[k] = 1 if r[k] else 0
        if r.get("h"):
            keep["h"] = str(r["h"])
        out.append(keep)
    return out


MAX_PER_OWNER = 30                       # 캐릭터 한 마리가 가질 수 있는 포스트잇 수


class NoteStore:
    def __init__(self, path):
        self.path = Path(path)
        self.notes = []
        self.active = {}                     # 캐릭터 → 지금 들고 있는 포스트잇 id
        self.load()

    # -- 파일 ---------------------------------------------------------------
    def load(self):
        self.notes = []
        self.active = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for n in data.get("notes", []):
                if isinstance(n, dict) and n.get("id") and n.get("owner"):
                    self.notes.append(self._normalize(n))
            act = data.get("active")
            if isinstance(act, dict):
                self.active = {str(k): str(v) for k, v in act.items()}
        except (OSError, ValueError):
            pass

    def save(self):
        """임시 파일에 쓴 뒤 교체(저장 도중 꺼져도 파일이 깨지지 않음)."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 3, "notes": self.notes, "active": self.active}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    @staticmethod
    def _normalize(n):
        color = LEGACY_COLORS.get(n.get("color"), n.get("color"))
        if color not in COLOR_RGB:
            color = DEFAULT_OWNER_COLOR.get(n["owner"], "yellow")
        try:
            w = int(n.get("width", SIZES["보통"][0]))
            h = int(n.get("height", SIZES["보통"][1]))
        except (TypeError, ValueError):
            w, h = SIZES["보통"]
        try:
            fs = float(n.get("font_size", DEFAULT_FONT_SIZE))
        except (TypeError, ValueError):
            fs = DEFAULT_FONT_SIZE
        out = {
            "id": str(n["id"]),
            "owner": n["owner"],
            "text": str(n.get("text", "")),
            "title": str(n.get("title", "")),
            "title_manual": bool(n.get("title_manual", False)),
            "color": color,
            "open": bool(n.get("open", False)),          # 펼쳐 둔 상태로 끝냈는가
            "width": max(MIN_W, min(MAX_W, w)),
            "height": max(MIN_H, min(MAX_H, h)),
            "font_family": str(n.get("font_family", "") or ""),      # 비어 있으면 기본 글꼴
            "runs": _clean_runs(n.get("runs"), len(str(n.get("text", "")))),   # 글자별 서식(선택한 부분만 바꾼 글꼴·굵게 등)
            "font_size": max(8.0, min(24.0, fs)),
            "bold": bool(n.get("bold", False)),
            "italic": bool(n.get("italic", False)),
            "created": n.get("created", time.time()),
        }
        out["updated"] = n.get("updated", out["created"])
        return out

    # -- 조작 ---------------------------------------------------------------
    def get(self, note_id):
        return next((n for n in self.notes if n["id"] == note_id), None)

    def notes_of(self, owner):
        """캐릭터의 포스트잇 목록(만든 순서)."""
        return sorted((x for x in self.notes if x["owner"] == owner), key=lambda x: x["created"])

    def for_owner(self, owner):
        """캐릭터가 지금 들고 있는 포스트잇(없으면 None)."""
        n = self.get(self.active.get(owner, ""))
        if n is not None and n["owner"] == owner:
            return n
        mine = self.notes_of(owner)
        if mine:
            self.active[owner] = mine[0]["id"]
            return mine[0]
        return None

    def ensure(self, owner, starter=""):
        """캐릭터가 들고 있는 메모를 돌려준다(없으면 만든다)."""
        n = self.for_owner(owner)
        return n if n is not None else self.add(owner, starter)

    def add(self, owner, starter=""):
        """새 포스트잇을 만들어 들게 한다(색은 가진 장수에 맞춰 돌아가며 정한다)."""
        first = COLOR_NAMES.index(DEFAULT_OWNER_COLOR.get(owner, "yellow"))
        color = COLOR_NAMES[(first + len(self.notes_of(owner))) % (len(COLOR_NAMES) - 1)]   # 그래파이트(어두운 색)는 건너뜀
        n = self._normalize({"id": uuid.uuid4().hex[:8], "owner": owner, "text": starter, "color": color,
                             "created": time.time() + len(self.notes) * 1e-6})
        self.notes.append(n)
        self.active[owner] = n["id"]
        return n

    def set_active(self, owner, note_id):
        n = self.get(note_id)
        if n is not None and n["owner"] == owner:
            self.active[owner] = note_id
        return n

    def delete(self, note_id):
        """포스트잇을 지우고, 그 캐릭터가 이어서 들 포스트잇을 돌려준다(하나도 안 남으면 빈 것을 새로 만든다)."""
        n = self.get(note_id)
        if n is None:
            return None
        owner = n["owner"]
        self.notes.remove(n)
        if self.active.get(owner) == note_id:
            self.active.pop(owner, None)
        return self.ensure(owner)

    def update(self, note_id, **kw):
        n = self.get(note_id)
        if n:
            n.update(kw)
            n["updated"] = time.time()
        return n
