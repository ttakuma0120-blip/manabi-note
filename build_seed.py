"""初期データ lessons_default.json を生成する（初回のみ手動実行可）"""

from __future__ import annotations

import json
from pathlib import Path

from seed_entries import ENTRIES


def main() -> None:
    root = Path(__file__).resolve().parent
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    out = []
    for i, e in enumerate(ENTRIES):
        out.append(
            {
                "id": f"seed{i+1:04d}",
                "date": e["date"],
                "title": e["title"],
                "content": e["content"].strip(),
            }
        )
    (data / "lessons_default.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(out)} entries to data/lessons_default.json")


if __name__ == "__main__":
    main()
