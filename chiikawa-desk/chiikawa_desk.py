#!/usr/bin/env python3
"""먼작귀 데스크톱 응원 위젯 (PyQt5)

  * 치이카와·하치와레·우사기가 화면 아래쪽에 함께 서서, 머리 위로 포스트잇(할 일 메모)을 들고 다닌다.
  * 쪽지를 누르면 펼쳐져서 편집, '–' 나 Esc 로 다시 접는다. (Ctrl+Enter = 체크리스트)
  * 일할 땐 다 같이 책상에서 키보드를 두드리고, 쉬는 시간엔 서로 다른 동작을 한다. (사용자 입력은 읽지 않는다)
  * 머리 위에 올릴 것(포스트잇·집중 타이머·퇴근 시계)은 캐릭터마다 설정한다.
  * 좌클릭 = 펼치기/접기, 끌기 = 옮기기(Shift = 모두), 휠 = 크기(Ctrl+휠 = 모두), 우클릭 = 메뉴.
"""
import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

HOME_DIR = Path(os.environ.get("CHIIKAWA_HOME") or (Path.home() / ".chiikawa_desk"))
POSE_DIR = HERE / "frames" / "poses"


def ensure_poses():
    if (POSE_DIR / "manifest.json").exists():
        return True
    print("frames/poses/ 가 없어 sprite_sheet_poses.png 에서 만듭니다...")
    try:
        import prepare_poses
    except ImportError as exc:
        print("prepare_poses 를 불러올 수 없습니다:", exc, "\n→ pip install pillow numpy")
        return False
    return prepare_poses.main() == 0 and (POSE_DIR / "manifest.json").exists()


def main():
    ap = argparse.ArgumentParser(description="먼작귀 데스크톱 응원 위젯")
    ap.add_argument("--reset", action="store_true", help="저장된 설정(위치·크기·타이머)을 초기화(포스트잇 내용은 유지)")
    ap.add_argument("--debug", action="store_true", help="상태 전환 로그 출력")
    args = ap.parse_args()

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not ensure_poses():
        return 1
    from manager import PetManager, load_config
    from notes_store import NoteStore
    from pet import PoseBank

    bank = PoseBank(POSE_DIR)
    cfg_path = HOME_DIR / "config.json"
    cfg = load_config(cfg_path, reset=args.reset)
    store = NoteStore(HOME_DIR / "notes.json")
    mgr = PetManager(cfg, cfg_path, store, bank, debug=args.debug)
    mgr.make_tray(app)
    code = app.exec_()
    return code


if __name__ == "__main__":
    sys.exit(main())
