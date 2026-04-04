"""
data/lessons.json から、「今日は「…」についてお話します」形式だけを残すフィルタ。
必要なら再実行: python filter_lessons.py

※ 日報・一言などは削除します。【】見出しの「固定費・使えるお金」回だけ例外で残します。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

_FIXED_FEE_MARK = "【どれだけ稼ぐかより、どれだけ使えるお金を用意できるかが大事です】"


def is_fixed_fee_bracket_lesson(lesson: dict) -> bool:
    c = (lesson.get("content") or "").lstrip()
    return c.startswith(_FIXED_FEE_MARK)


def is_standard_talk_format(lesson: dict) -> bool:
    c = lesson.get("content") or ""
    if is_fixed_fee_bracket_lesson(lesson):
        return len(c) >= 100
    if "【経営会議報告】" in c or "プチ経営会議" in c or "No.◯" in c:
        return False
    if "今日は「" not in c or "についてお話します" not in c:
        return False
    if len(c) < 100:
        return False
    return True


def main() -> None:
    root = Path(__file__).resolve().parent
    path = root / "data" / "lessons.json"
    if not path.exists():
        print("data/lessons.json がありません")
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        print("形式が不正です")
        return
    bak = path.with_suffix(".json.bak-" + datetime.now().strftime("%Y%m%d%H%M%S"))
    shutil.copy(path, bak)
    print("バックアップ:", bak)
    filtered = [x for x in raw if isinstance(x, dict) and is_standard_talk_format(x)]
    path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2), encoding="utf-8")
    default = root / "data" / "lessons_default.json"
    if default.exists():
        default.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"{len(raw)} 件 → {len(filtered)} 件")


if __name__ == "__main__":
    main()
