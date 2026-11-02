"""一覧との照合用ヘルパー (PROJECT_LIST の読み取り、プロジェクト情報の収集)。"""
from __future__ import annotations

import json

from audit_common import *  # noqa: F401,F403
from audit_common import index_field


def parse_project_list(text: str) -> dict[str, dict[str, str]]:
    """PROJECT_LIST.md の表を読む。戻り値: フォルダ相対パス -> 行データ。"""
    entries: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or cells[0] in ("フォルダ", "") or set(cells[0]) <= {"-", " "}:
            continue
        folder = cells[0].strip("`").rstrip("/")
        entries[folder] = {
            "project": cells[1],
            "chat": cells[2],
            "chat_id": cells[3],
            "goal": cells[4] if len(cells) >= 6 else "",
            "status": cells[5] if len(cells) >= 6 else cells[4],
        }
    return entries


def collect_project_info(project: Path) -> dict[str, str]:
    """一覧照合用に INDEX.md と chat.json から情報を集める。"""
    info: dict[str, str] = {}
    index = project / "INDEX.md"
    if index.is_file():
        text = index.read_text(encoding="utf-8", errors="replace")
        for key, label in (("project", "プロジェクト名"), ("chat", "サイドチャット名"),
                           ("chat_id", "チャットID")):
            value = index_field(text, label)
            if value:
                info[key] = value
        # 担当ゴールは「名前（ID）」形式で ID ごと必要なため、生の値を取得する
        m = re.search(r"^-\s*担当ゴール：(.+)$", text, flags=re.MULTILINE)
        if m:
            info["goal_raw"] = m.group(1).strip()
    chat_file = project / "chat.json"
    if chat_file.is_file():
        try:
            data = json.loads(chat_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if data.get("chat_name"):
                    info["actual_chat"] = str(data["chat_name"])
                if data.get("chat_id"):
                    info["actual_chat_id"] = str(data["chat_id"])
        except json.JSONDecodeError:
            pass
    return info
