"""
しょうたさんの学び管理（Flask）

URL:
  / → 学びノート閲覧トップへリダイレクト（下記プレフィックスの閲覧ページ）
  /manabi_note/           共有用（閲覧のみ・未設定時）
  /manabi_note/manage     編集用（本人用・未設定時）

  MANABI_VIEW_SECRET に 8〜128 文字（英数字・_- のみ）を設定すると:
  /manabi_note/<秘密>/           共有用
  /manabi_note/<秘密>/manage     編集用
  （旧 /manabi_note/ 直下は使わない。推測されにくいパスで難読化）

  /webhook/line        LINE Messaging API Webhook（変更なし）
  /api/lessons         JSON（互換のため維持）
  （秘密パス利用時）/manabi_note/<秘密>/api/lessons  同上

LINE連携: LINE_CHANNEL_SECRET 設定後、Webhook に https://（公開URL）/webhook/line
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from flask import Blueprint, Flask, Response, redirect, render_template, request, url_for

APP_DIR = Path(__file__).resolve().parent
DATA_PATH = APP_DIR / "data" / "lessons.json"
DEFAULT_EXPORT = APP_DIR / "data" / "lessons_default.json"

VALID_VIEWS = frozenset({"normal", "accordion", "genre", "timeline"})
VIEW_LABELS = {
    "normal": "通常表示",
    "accordion": "タイトルのみ表示（コンパクトに表示）",
    "genre": "ジャンル別",
    "timeline": "月別タイムライン",
}
# ツールバー表示順（sorted(VALID_VIEWS) に任せると並びが直感的でないため固定）
VIEW_TOOLBAR_ORDER = ("normal", "accordion", "genre", "timeline")

# ジャンル表示順（グループ表示用）
GENRE_ORDER = [
    "お金・経済",
    "習慣・継続・身体",
    "マインド・思考・行動",
    "ビジネス・仕事",
    "人間関係・コミュニケーション",
    "時間",
    "その他",
]

# (キーワードの一部), ジャンル名 — 先に書いたルールが優先
_GENRE_KEYWORD_RULES: list[tuple[tuple[str, ...], str]] = [
    (
        (
            "固定費",
            "資産",
            "投資",
            "インフレ",
            "キャッシュ",
            "ポイ活",
            "リテラシー",
            "格差社会",
            "原油",
            "生活水準",
            "お金持ち",
            "小さな5000",
            "1万円を取り続ける",
            "ディドロ",
            "銀行",
            "物価",
            "経済",
        ),
        "お金・経済",
    ),
    (
        (
            "習慣",
            "反復",
            "シナプス",
            "大脳基底核",
            "1.01",
            "0.99",
            "継続",
            "コンディション",
            "睡眠",
            "判断力",
            "IQが下がる",
            "筋トレ",
            "早起き",
        ),
        "習慣・継続・身体",
    ),
    (
        (
            "マインド",
            "思考",
            "コンフォート",
            "執着",
            "制限",
            "素直",
            "情の熱",
            "情熱",
            "価値観",
            "行動を変える",
            "挑戦は奇跡",
            "挑戦をしない",
            "悔しさ",
            "劣等感",
            "目的論",
            "変わらない",
            "環境は恐るべし",
            "環境に影響",
        ),
        "マインド・思考・行動",
    ),
    (
        (
            "ビジネス",
            "マーケ",
            "センス",
            "専門性",
            "効果のない作業",
            "仕事を取り",
            "市場",
            "カフェ",
            "アサイー",
            "収益",
            "オペレーション",
            "勝てる設計",
        ),
        "ビジネス・仕事",
    ),
    (
        (
            "感謝",
            "第一印象",
            "社会貢献",
            "人助け",
            "コミュニケーション",
            "課題の分離",
            "承認欲求",
            "人間関係",
            "ネガティブを引っ張られ",
        ),
        "人間関係・コミュニケーション",
    ),
    (
        ("時間は", "期限をつけ", "不可逆", "時間だけは", "時間を投資"),
        "時間",
    ),
]

# ジャンル名 → CSSクラス（色分け用）
GENRE_CSS_CLASSES: dict[str, str] = {
    "お金・経済": "genre-money",
    "習慣・継続・身体": "genre-habit",
    "マインド・思考・行動": "genre-mind",
    "ビジネス・仕事": "genre-business",
    "人間関係・コミュニケーション": "genre-human",
    "時間": "genre-time",
    "その他": "genre-other",
}


def genre_css_class(genre_label: str) -> str:
    return GENRE_CSS_CLASSES.get(genre_label, "genre-other")


app = Flask(__name__)
app.secret_key = "change-me-in-production-" + uuid.uuid4().hex

_SECRET_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_-]{8,128}$")


def manabi_blueprint_url_prefix() -> str:
    """環境変数 MANABI_VIEW_SECRET があれば /manabi_note/<secret>、なければ /manabi_note。"""
    raw = os.environ.get("MANABI_VIEW_SECRET", "").strip()
    if not raw:
        return "/manabi_note"
    if not _SECRET_SEGMENT_RE.match(raw):
        print(
            "MANABI_VIEW_SECRET: 空にするか、英数字と _ - のみで 8〜128 文字にしてください。",
            file=sys.stderr,
        )
        sys.exit(1)
    return f"/manabi_note/{raw}"


manabi_bp = Blueprint("manabi", __name__, url_prefix=manabi_blueprint_url_prefix())


def ensure_data_dir() -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_PATH.exists() and DEFAULT_EXPORT.exists():
        DATA_PATH.write_text(DEFAULT_EXPORT.read_text(encoding="utf-8"), encoding="utf-8")


def load_lessons() -> list[dict]:
    ensure_data_dir()
    raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    return raw


def save_lessons(rows: list[dict]) -> None:
    ensure_data_dir()
    DATA_PATH.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def classify_genre(title: str, content: str) -> str:
    text = f"{title}\n{content}"
    for keywords, label in _GENRE_KEYWORD_RULES:
        for kw in keywords:
            if kw in text:
                return label
    return "その他"


def lesson_genre(lesson: dict) -> str:
    g = lesson.get("genre")
    if isinstance(g, str) and g.strip():
        return g.strip()
    return classify_genre(lesson.get("title", ""), lesson.get("content", ""))


def enrich_lesson(lesson: dict) -> dict:
    out = dict(lesson)
    g = lesson_genre(lesson)
    out["genre"] = g
    out["genre_css"] = genre_css_class(g)
    return out


def auto_title(content: str, fallback: str = "学び") -> str:
    text = content.strip()
    if not text:
        return fallback
    m = re.search(r"今日は「([^」]+)」について", text)
    if m:
        return m.group(1)[:80]
    first = text.splitlines()[0].strip()
    if len(first) > 52:
        return first[:52] + "…"
    return first or fallback


def sort_lessons(rows: list[dict]) -> list[dict]:
    def key(r: dict) -> tuple:
        return (r.get("date", ""), r.get("id", ""))

    return sorted(rows, key=key, reverse=True)


def group_lessons_by_genre(lessons: list[dict]) -> list[tuple[str, list[dict]]]:
    bucket: dict[str, list[dict]] = defaultdict(list)
    for L in lessons:
        bucket[L["genre"]].append(L)
    ordered: list[tuple[str, list[dict]]] = []
    for g in GENRE_ORDER:
        if bucket.get(g):
            ordered.append((g, bucket[g]))
    for g, items in bucket.items():
        if g not in GENRE_ORDER and items:
            ordered.append((g, items))
    return ordered


def group_lessons_by_month(lessons: list[dict]) -> list[tuple[str, list[dict]]]:
    bucket: dict[str, list[dict]] = defaultdict(list)
    for L in lessons:
        d = L.get("date", "")[:7]
        if len(d) == 7:
            bucket[d].append(L)
        else:
            bucket["日付不明"].append(L)
    months = sorted([k for k in bucket if k != "日付不明"], reverse=True)
    out: list[tuple[str, list[dict]]] = []
    for m in months:
        out.append((m, bucket[m]))
    if bucket.get("日付不明"):
        out.append(("日付不明", bucket["日付不明"]))
    return out


def month_label(ym: str) -> str:
    if len(ym) == 7 and ym[4] == "-":
        y, mo = ym.split("-", 1)
        return f"{y}年{int(mo)}月"
    return ym


def parse_view() -> str:
    v = request.args.get("view", "normal")
    return v if v in VALID_VIEWS else "normal"


def _render_index(*, read_only: bool) -> str:
    view = parse_view()
    raw = sort_lessons(load_lessons())
    lessons = [enrich_lesson(L) for L in raw]
    today = date.today().isoformat()
    genre_groups = group_lessons_by_genre(lessons)
    timeline_groups = group_lessons_by_month(lessons)
    index_endpoint = "manabi.public_index" if read_only else "manabi.manage_index"
    return render_template(
        "index.html",
        lessons=lessons,
        genre_groups=genre_groups,
        timeline_groups=timeline_groups,
        count=len(lessons),
        default_date=today,
        current_view=view,
        read_only=read_only,
        index_endpoint=index_endpoint,
        valid_views=VIEW_TOOLBAR_ORDER,
        flash_message=request.args.get("msg"),
        flash_type=request.args.get("t", "ok"),
        month_label=month_label,
        view_labels=VIEW_LABELS,
        genre_css_class=genre_css_class,
    )


@manabi_bp.get("/")
def public_index():
    """共有用：閲覧のみ（追加・削除なし）。他の人に渡すURLはこちら。"""
    return _render_index(read_only=True)


@manabi_bp.get("/manage")
def manage_index():
    """編集用：追加・削除あり。ブックマークは自分だけに。"""
    return _render_index(read_only=False)


@manabi_bp.post("/manage/add")
def manage_add():
    view = request.form.get("view", "normal")
    if view not in VALID_VIEWS:
        view = "normal"
    d = request.form.get("date", "").strip()
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    if not d or not content:
        return redirect(
            url_for("manabi.manage_index", view=view, msg="日付と内容は必須です", t="err")
        )
    if not title:
        title = auto_title(content)
    genre = classify_genre(title, content)
    new_id = uuid.uuid4().hex[:12]
    row = {
        "id": new_id,
        "date": d,
        "title": title,
        "content": content,
        "genre": genre,
        "source": "manual",
    }
    rows = load_lessons()
    rows.append(row)
    save_lessons(rows)
    return redirect(url_for("manabi.manage_index", view=view, msg="追加しました"))


@manabi_bp.post("/manage/delete/<lesson_id>")
def manage_delete(lesson_id: str):
    view = request.form.get("view", "normal")
    if view not in VALID_VIEWS:
        view = "normal"
    rows = [r for r in load_lessons() if r.get("id") != lesson_id]
    save_lessons(rows)
    return redirect(url_for("manabi.manage_index", view=view, msg="削除しました"))


@manabi_bp.get("/api/lessons")
def manabi_api_lessons():
    from flask import jsonify

    raw = sort_lessons(load_lessons())
    return jsonify([enrich_lesson(L) for L in raw])


app.register_blueprint(manabi_bp)


@app.get("/")
def root_redirect():
    return redirect(url_for("manabi.public_index"))


@app.get("/api/lessons")
def api_lessons():
    from flask import jsonify

    raw = sort_lessons(load_lessons())
    return jsonify([enrich_lesson(L) for L in raw])


def _line_verify_signature(body: bytes, signature: str, secret: str) -> bool:
    if not secret or not signature:
        return False
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def _line_allowed_user(source: dict) -> bool:
    raw = os.environ.get("LINE_ALLOWED_USER_IDS", "").strip()
    if not raw:
        return True
    allowed = {x.strip() for x in raw.split(",") if x.strip()}
    uid = (source or {}).get("userId")
    return uid in allowed if uid else False


@app.post("/webhook/line")
def webhook_line():
    """
    LINE Messaging API からのコールバック。
    - LINE_CHANNEL_SECRET 必須
    - LINE_ALLOWED_USER_IDS に userId をカンマ区切りで入れると、その送信者のみ取り込み
    - メッセージの投稿日時は可能ならイベントの timestamp から JST 日付を推定
    """
    secret = os.environ.get("LINE_CHANNEL_SECRET", "").strip()
    if not secret:
        return Response(
            "LINE_CHANNEL_SECRET 未設定。環境変数を設定してから Webhook を有効にしてください。",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    body = request.get_data()
    sig = request.headers.get("X-Line-Signature", "")
    if not _line_verify_signature(body, sig, secret):
        return Response("Invalid signature", status=400, content_type="text/plain; charset=utf-8")

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        return Response("Invalid JSON", status=400, content_type="text/plain; charset=utf-8")

    events = payload.get("events") or []
    added = 0
    rows = load_lessons()

    for ev in events:
        if ev.get("type") != "message":
            continue
        msg = ev.get("message") or {}
        if msg.get("type") != "text":
            continue
        source = ev.get("source") or {}
        if not _line_allowed_user(source):
            continue
        text = (msg.get("text") or "").strip()
        if len(text) < 3:
            continue

        ts = ev.get("timestamp")
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
            d = dt.date().isoformat()
        else:
            d = date.today().isoformat()

        title = auto_title(text)
        genre = classify_genre(title, text)
        new_id = uuid.uuid4().hex[:12]
        rows.append(
            {
                "id": new_id,
                "date": d,
                "title": title,
                "content": text,
                "genre": genre,
                "source": "line",
                "line_user_id": source.get("userId"),
                "line_message_id": msg.get("id"),
            }
        )
        added += 1

    if added:
        save_lessons(rows)

    from flask import jsonify

    return jsonify({"ok": True, "imported": added})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
