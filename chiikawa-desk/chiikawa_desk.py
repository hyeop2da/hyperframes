#!/usr/bin/env python3
"""먼작귀 데스크톱 응원 위젯 (PyQt5)

Characters: © nagano / chiikawa committee

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
# 포차코 같은 추가 캐릭터 팩은 내 PC의 이 폴더에서 불러온다(그림은 프로그램·저장소에 들어 있지 않다)


PACK_SPECIES = ("pochacco", "kitty")


def pack_dirs(species="pochacco"):
    """팩을 찾는 위치(앞에서부터): 내 사용자 폴더 → exe 바로 옆의 packs 폴더 → 소스 폴더."""
    out = [HOME_DIR / "packs" / species]
    if getattr(sys, "frozen", False):                 # exe 로 실행 중이면 exe 가 있는 폴더 옆(압축 푼 폴더 그대로 쓰기)
        out.append(Path(sys.executable).resolve().parent / "packs" / species)
    out.append(HERE / "packs" / species)
    return out


def found_packs():
    """있는 팩 폴더들(포차코·키티)."""
    found = []
    for sp in PACK_SPECIES:
        d = next((d for d in pack_dirs(sp) if (d / "manifest.json").exists()), None)
        if d is not None:
            found.append(d)
    return found


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

    bank = PoseBank(POSE_DIR, found_packs())
    if bank.pack_error:
        print("캐릭터 팩을 불러오지 못했어요:", bank.pack_error)
    cfg_path = HOME_DIR / "config.json"
    cfg = load_config(cfg_path, reset=args.reset)
    store = NoteStore(HOME_DIR / "notes.json")
    import autostart
    autostart.set_enabled(bool(cfg.get("autostart", True)))      # 설정대로 시작 프로그램 등록을 맞춘다(기본 켬)
    mgr = PetManager(cfg, cfg_path, store, bank, debug=args.debug)
    mgr.make_tray(app)
    code = app.exec_()
    return code


if __name__ == "__main__":
    sys.exit(main())
