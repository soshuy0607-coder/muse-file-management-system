"""プロジェクト単体のチェック (フォルダ名・構成・チャット名・ファイル名)。"""
from __future__ import annotations

import json

from audit_common import *  # noqa: F401,F403
from audit_common import Results


def check_project(res: Results, project: Path) -> None:
    name = project.name

    # 3. フォルダ名形式「プロジェクト名_テーマ」
    parts = name.split("_", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        res.error(f"[命名] {name}: 「プロジェクト名_テーマ」形式になっていません")
    else:
        res.ok(f"[命名] {name}")

    # 4. 必須構成
    for d in REQUIRED_DIRS:
        if not (project / d).is_dir():
            res.error(f"[構成] {name}: {d}/ がありません")
    index = project / "INDEX.md"
    if not index.is_file():
        res.error(f"[構成] {name}: INDEX.md がありません")
        return

    # 5. 直下のファイルは INDEX.md / chat.json だけ
    for entry in sorted(project.iterdir()):
        if entry.is_file() and entry.name not in ALLOWED_PROJECT_FILES:
            res.error(f"[直置き] {name}: 直下に許可されていないファイルがあります: {entry.name}")

    # 6. INDEX の記載
    text = index.read_text(encoding="utf-8", errors="replace")
    for label in ("プロジェクト名：", "サイドチャット名：", "チャットID："):
        if label not in text:
            res.error(f"[INDEX] {name}: 「{label}」の記載がありません")

    # 7. チャット名 == フォルダ名
    documented_chat = index_field(text, "サイドチャット名")
    if documented_chat is not None:
        if documented_chat != name:
            res.error(
                f"[チャット名] {name}: INDEXのサイドチャット名「{documented_chat}」がフォルダ名と一致しません"
            )
        else:
            res.ok(f"[チャット名] {name}: INDEX記載がフォルダ名と一致")

    chat_file = project / "chat.json"
    if not chat_file.is_file():
        res.error(f"[構成] {name}: chat.json がありません")
    else:
        try:
            data = json.loads(chat_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            res.error(f"[チャット名] {name}: chat.json が読めません (JSON形式を確認してください)")
            data = None
        if isinstance(data, dict):
            actual = data.get("chat_name")
            if actual != name:
                res.error(
                    f"[チャット名] {name}: 実際のチャット名「{actual}」がフォルダ名と一致しません"
                )
            else:
                res.ok(f"[チャット名] {name}: 実際のチャット名がフォルダ名と一致")
            chat_id_index = index_field(text, "チャットID")
            if chat_id_index and data.get("chat_id") != chat_id_index:
                res.error(f"[チャット名] {name}: chat.json の chat_id が INDEX と一致しません")

    # 8. 曖昧なファイル名 (警告)
    for path in project.rglob("*"):
        if path.is_file() and path.name not in ALLOWED_PROJECT_FILES:
            if any(p.search(path.name) for p in BAD_NAME_PATTERNS):
                res.warn(f"[ファイル名] {name}: 曖昧な名前です: {path.relative_to(project)}")
