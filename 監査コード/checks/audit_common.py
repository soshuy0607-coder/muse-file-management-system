"""監査の共通部品: パス、定数、結果の置き場、小さなヘルパー。"""
from __future__ import annotations

import re
from pathlib import Path

import os

_env_root = os.environ.get("MUSE_AUDIT_ROOT")
ROOT = Path(_env_root).resolve() if _env_root else Path(__file__).resolve().parents[2]  # workspace/
PROJECTS = ROOT / "projects"
ARCHIVE = PROJECTS / "_archive"
LIST_FILE = PROJECTS / "PROJECT_LIST.md"
GOALS_DIR = ROOT / "goals"
AUDIT_DIR = ROOT / "監査コード"
HOME_DIR = ROOT.parent  # ホーム (カタログと本棚の置き場所)
AGENTS_FILE = ROOT.parent / "AGENTS.md"  # 全体用AGENTS.md (毎回読み込まれる)
AGENTS_CHAR_LIMIT = 3000  # これを超えたら警告 (詳細は監査ルール.mdへ移す目安)
MEMORY_BYTE_LIMIT = 30000  # MEMORY.md の総量の目安 (バイト数、超えたら警告)
MEMORY_ENTRY_CHAR_LIMIT = 3000  # MEMORY.md の1項目の長さの目安 (字数、超えたら警告)

ALLOWED_ROOT_FILES: set[str] = set()  # workspace直下にファイルは置かない
ALLOWED_PROJECTS_FILES = {"PROJECT_LIST.md"}
ALLOWED_PROJECT_FILES = {"INDEX.md", "chat.json"}
# 直下に置けるのは入口とルール文書のみ。Git管理物（.git / .gitignore）は
# バージョン管理の仕組みそのものなので例外として許可する（監査ルール13）。
ALLOWED_AUDIT_FILES = {"audit_file_storage.py", "監査ルール.md", ".gitignore", ".audit-state.json", ".test-state.json"}
ALLOWED_AUDIT_DIRS = {"checks", "tests", ".git"}
REQUIRED_DIRS = ("files", "inputs", "hidden_files")
# プロジェクト任意フォルダ: GitHub登録 (github/REPO.md)。無いプロジェクトは対象外 (監査ルール16)。
GITHUB_DIR_NAME = "github"
GITHUB_REPO_FILE = "REPO.md"
GITHUB_VISIBILITIES = {"public", "private"}
ALLOWED_PROJECT_DIRS = set(REQUIRED_DIRS) | {GITHUB_DIR_NAME}
# 未配布の改良の上限 (監査ルール17)。超過したら警告する。
RELEASE_PENDING_FILE = "リリース予定.md"  # 置き場所はプロジェクトの hidden_files/
RELEASE_PENDING_MAX = 15
BAD_NAME_PATTERNS = [
    re.compile(r"(?i)final"),
    re.compile(r"(?i)(^|_)new($|_)"),
    re.compile(r"コピー|copy|\(\d+\)"),
]

class Results:
    """監査結果の受け渡し専用オブジェクト。

    結果は必ずこのオブジェクト経由で集める。リストを各部品が個別に
    持ち直すと、作り直した側の結果が報告から消える事故が起きるため。
    """

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.oks: list[str] = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def ok(self, msg: str) -> None:
        self.oks.append(msg)


def read_text_report(res: "Results", path: Path, label: str) -> str | None:
    """台帳ファイルを厳密に読む。読めなければ黙って読み飛ばさず、
    エラーとして記録して None を返す (文字化けの置換で異常を飲まない)。"""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        res.error(f"[読込] {label}: ファイルが読めません: {path.name}")
        return None


def index_field(text: str, label: str) -> str | None:
    """INDEX の「- ラベル：値」行から値を取り出す。末尾の（補足）は除く。"""
    m = re.search(rf"^-\s*{re.escape(label)}：(.+)$", text, flags=re.MULTILINE)
    if not m:
        return None
    value = m.group(1).strip()
    value = re.sub(r"（[^）]*）\s*$", "", value).strip()
    return value


def parse_goal_entries(raw: str) -> dict[str, str]:
    """「ゴール名（goal_id）；ゴール名（goal_id）」を {goal_id: ゴール名} にする。「なし」は空。"""
    result: dict[str, str] = {}
    for title, goal_id in re.findall(r"([^（；]+)（(goal_[^）]+)）", raw or ""):
        result[goal_id.strip()] = title.strip()
    return result


def validate_root() -> None:
    """監査対象を取り違えていないか、開始前に必ず確認する。

    部品の置き場所が変わると ROOT の逆算がずれて、別の場所を監査して
    「問題なし」と誤報する恐れがあるため、想定の構成が無ければ中止する。
    """
    problems = []
    if not (ROOT / "projects").is_dir():
        problems.append("projects/ がありません")
    if not (ROOT / "監査コード" / "audit_file_storage.py").is_file():
        problems.append("監査コード/audit_file_storage.py がありません")
    if problems:
        raise SystemExit(
            "監査を中止します: 監査対象の場所が想定と違います "
            f"(ROOT={ROOT}): " + "; ".join(problems))
