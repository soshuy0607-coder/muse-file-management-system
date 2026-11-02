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
        if cells[0] in ("フォルダ", "") or set(cells[0]) <= {"-", " "}:
            continue
        if len(cells) != 6:
            continue  # 形式の崩れた行は読み込まない (検出は project_list_problems の役目)
        folder = cells[0].strip("`").rstrip("/")
        entries[folder] = {
            "project": cells[1],
            "chat": cells[2],
            "chat_id": cells[3],
            "goal": cells[4],
            "status": cells[5],
        }
    return entries


def collect_project_info(project: Path) -> dict[str, str]:
    """一覧照合用に INDEX.md と chat.json から情報を集める。"""
    info: dict[str, str] = {}
    index = project / "INDEX.md"
    if index.is_file():
        try:
            text = index.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""  # 読めない台帳は情報なしとして扱う (検出は個別チェックの役目)
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
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass  # 読めない場合は情報なしとして扱う (検出は個別チェックの役目)
    return info


def project_list_problems(text: str) -> list[str]:
    """PROJECT_LIST.md の表の行形式の問題を返す。

    データ行は6列 (フォルダ/プロジェクト名/チャット名/チャットID/担当ゴール/状態)
    でなければならない。列数が違う行は、黙って誤読せずここで拾う。
    """
    problems: list[str] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if cells[0] in ("フォルダ", "") or set(cells[0]) <= {"-", " "}:
            continue  # ヘッダー行と区切り行
        if len(cells) != 6:
            problems.append(f"{lineno}行目: 列が {len(cells)} 個あります (6列のはずです)")
    return problems
