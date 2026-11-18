"""포스트잇 데이터 저장소 (Qt 없음). 내용은 내 PC의 JSON 파일에만 저장한다.

캐릭터 한 마리가 메모 한 장을 머리 위로 들고 다닌다.
메모 = 텍스트 한 덩어리: 첫 줄이 제목, '☐ '/'☑ ' 로 시작하는 줄은 체크리스트.
"""
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

UNCHECKED, CHECKED = "☐", "☑"

COLORS = {          # 영상의 노랑·분홍 + 4색
    "yellow": "#FCEB9C", "pink": "#F4C6CF", "blue": "#C9E3F7",
    "green": "#D5EDC4", "purple": "#DCD3F3", "orange": "#FAD7B0",
}
COLOR_LABELS = {"yellow": "노랑", "pink": "분홍", "blue": "하늘", "green": "연두", "purple": "보라", "orange": "주황"}
DEFAULT_OWNER_COLOR = {"chiikawa": "pink", "hachiware": "blue", "usagi": "yellow"}


def progress(text):
    """(완료 수, 전체 수) — 체크리스트 줄만 센다."""
    done = total = 0
    for line in text.splitlines():
        if line[:1] == UNCHECKED:
            total += 1
        elif line[:1] == CHECKED:
            total += 1
            done += 1
    return done, total


def title_of(text, default="새 메모"):
    for line in text.splitlines():
        s = line.strip()
        if s.startswith((UNCHECKED, CHECKED)):
            s = s[1:].strip()
        if s:
            return s
    return default


class NoteStore:
    def __init__(self, path):
        self.path = Path(path)
        self.notes = []
        self.load()

    # -- 파일 ---------------------------------------------------------------
    def load(self):
        self.notes = []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for n in data.get("notes", []):
                if isinstance(n, dict) and n.get("id") and n.get("owner"):
                    self.notes.append(self._normalize(n))
        except (OSError, ValueError):
            pass

    def save(self):
        """임시 파일에 쓴 뒤 교체(저장 도중 꺼져도 파일이 깨지지 않음)."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 2, "notes": self.notes}, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    @staticmethod
    def _normalize(n):
        out = {
            "id": str(n["id"]),
            "owner": n["owner"],
            "text": str(n.get("text", "")),
            "color": n.get("color") if n.get("color") in COLORS else DEFAULT_OWNER_COLOR.get(n["owner"], "yellow"),
            "open": bool(n.get("open", False)),          # 펼쳐 둔 상태로 끝냈는가
            "created": n.get("created", time.time()),
        }
        out["updated"] = n.get("updated", out["created"])
        return out

    # -- 조작 ---------------------------------------------------------------
    def get(self, note_id):
        return next((n for n in self.notes if n["id"] == note_id), None)

    def for_owner(self, owner):
        return next((n for n in self.notes if n["owner"] == owner), None)

    def ensure(self, owner, starter=""):
        """캐릭터의 메모를 돌려준다(없으면 만든다)."""
        n = self.for_owner(owner)
        if n is None:
            n = self._normalize({"id": uuid.uuid4().hex[:8], "owner": owner, "text": starter})
            self.notes.append(n)
        return n

    def update(self, note_id, **kw):
        n = self.get(note_id)
        if n:
            n.update(kw)
            n["updated"] = time.time()
        return n
