#!/usr/bin/env python3
"""먼작귀 데스크톱 응원 위젯 (PyQt5)

  * 치이카와·하치와레·우사기가 화면 아래쪽에 함께 서서, 머리 위로 포스트잇(할 일 메모)을 들고 다닌다.
  * 쪽지를 누르면 펼쳐져서 편집, '–' 나 Esc 로 다시 접는다. (Ctrl+Enter = 체크리스트)
  * 다른 프로그램에서 작업해도(입력 유휴 시간 기반) 캐릭터가 함께 집중한다. 키 내용은 읽지 않는다.
  * 집중 타이머, 퇴근 시각 표시. 좌클릭 = 타이머 카드, 휠 = 크기(Ctrl+휠 = 모두), 우클릭 = 메뉴.
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
    ap.add_argument("--diagnose-input", action="store_true", help="입력 유휴 시간을 10초간 출력(작업 감지 확인용)")
    ap.add_argument("--reset", action="store_true", help="저장된 설정(위치·크기·타이머)을 초기화(포스트잇 내용은 유지)")
    ap.add_argument("--debug", action="store_true", help="상태 전환 로그 출력")
    args = ap.parse_args()

    if args.diagnose_input:
        import idle_probe
        idle_probe.diagnose()
        return 0

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
    import idle_probe
    from manager import PetManager, load_config
    from notes_store import NoteStore
    from pet import PoseBank

    bank = PoseBank(POSE_DIR)
    cfg_path = HOME_DIR / "config.json"
    cfg = load_config(cfg_path, reset=args.reset)
    store = NoteStore(HOME_DIR / "notes.json")
    probe = idle_probe.create_probe()
    print("[작업 감지]", probe.name if probe.available else f"사용 불가 — {probe.reason}")

    mgr = PetManager(cfg, cfg_path, store, bank, probe, debug=args.debug)
    mgr.make_tray(app)
    code = app.exec_()
    return code


if __name__ == "__main__":
    sys.exit(main())
