"""監査コードのテストケース集。

各ケースは、検証用の小さな環境 (フィクスチャ) を組み立て、そこへ
現在の監査コードを複写して実行し、出力と終了コードを確かめる。
実データには依存しない (テストは再現可能であること)。

ケースの関数名がそのままケース名になる。各ケースは対象部品を
targets に持ち、実行係はその部品が変わったケースだけを再実行する。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]  # 監査コード/

INDEX_TEXT = """# テスト_サンプル

- プロジェクト名：テスト
- サイドチャット名：テスト_サンプル
- チャットID：chat-id-0001
- 担当ゴール：テストゴール（goal_test000000001）
"""

LIST_TEXT = """# プロジェクト一覧

| フォルダ | プロジェクト名 | チャット名 | チャットID | 担当ゴール | 状態 |
|---|---|---|---|---|---|
| `テスト_サンプル` | テスト | テスト_サンプル | chat-id-0001 | テストゴール（goal_test000000001） | 進行中 |
"""

GOAL_TEXT = """# テストゴール

Goal ID: goal_test000000001

担当プロジェクト：{テスト}
"""

AGENTS_TEXT = """# AGENTS.md (テスト用)

## 本棚の目次 (agents棚)
本棚フォルダ：本棚/agents
種別 | 題名 | 場所 | 要約 | 合図
本 | テスト本 | 本棚/agents/テスト本.md | テスト用の本 | テスト
"""

REPO_TEXT = """# GitHub登録

- リポジトリ：owner/test-repo
- URL：https://github.com/owner/test-repo
- 既定ブランチ：main
- 公開範囲：private
- 同期元：files
- 履歴：../../監査コード
"""


class Ctx:
    """1ケース分の検証環境と、監査の実行係。"""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.workspace = self.home / "workspace"
        self.project = self.workspace / "projects" / "テスト_サンプル"
        self._build()

    def _build(self) -> None:
        ws = self.workspace
        audit_dir = ws / "監査コード"
        (audit_dir / "checks").mkdir(parents=True)
        (audit_dir / "audit_file_storage.py").write_bytes(
            (CODE_ROOT / "audit_file_storage.py").read_bytes())
        (audit_dir / "監査ルール.md").write_bytes(
            (CODE_ROOT / "監査ルール.md").read_bytes())
        for part in (CODE_ROOT / "checks").glob("*.py"):
            (audit_dir / "checks" / part.name).write_bytes(part.read_bytes())
        (audit_dir / ".git").mkdir()  # 履歴の照合先 (中身は空でよい)
        (audit_dir / "tests").mkdir()
        for part in (CODE_ROOT / "tests").glob("*.py"):
            (audit_dir / "tests" / part.name).write_bytes(part.read_bytes())
        (self.home / "AGENTS.md").write_text(AGENTS_TEXT, encoding="utf-8")
        shelf = self.home / "本棚" / "agents"
        shelf.mkdir(parents=True)
        (shelf / "テスト本.md").write_text("# テスト本\n", encoding="utf-8")
        (ws / "projects").mkdir()
        (ws / "projects" / "_archive").mkdir()
        (ws / "projects" / "PROJECT_LIST.md").write_text(LIST_TEXT, encoding="utf-8")
        for d in ("files", "inputs", "hidden_files"):
            (self.project / d).mkdir(parents=True)
        (self.project / "INDEX.md").write_text(INDEX_TEXT, encoding="utf-8")
        (self.project / "chat.json").write_text(
            json.dumps({"chat_name": "テスト_サンプル", "chat_id": "chat-id-0001"}),
            encoding="utf-8")
        goal_dir = ws / "goals" / "test-goal"
        goal_dir.mkdir(parents=True)
        (goal_dir / "GOAL.md").write_text(GOAL_TEXT, encoding="utf-8")
        named = goal_dir / "テストゴール"
        named.mkdir()
        os.symlink("../GOAL.md", named / "GOAL.md")

    def run(self, verbose: bool = False) -> tuple[int, str]:
        env = {**os.environ, "MUSE_AUDIT_ROOT": str(self.workspace)}
        argv = [sys.executable, str(self.workspace / "監査コード" / "audit_file_storage.py")]
        if verbose:
            argv.append("--verbose")
        proc = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", env=env)
        return proc.returncode, proc.stdout + proc.stderr

    # --- 検証の小道具 ---
    def expect(self, problems: list[str], code: int, out: str,
               want_code: int, *needles: str) -> None:
        if code != want_code:
            problems.append(f"終了コードが {code} (期待: {want_code})")
        for needle in needles:
            if needle not in out:
                problems.append(f"出力に「{needle}」がありません")

    def add_github(self) -> Path:
        gh = self.project / "github"
        gh.mkdir()
        (gh / "REPO.md").write_text(REPO_TEXT, encoding="utf-8")
        return gh


# --- 正常系 ---

def case_healthy(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "判定: 問題なし")
    if any(line.startswith("ERROR ") for line in out.splitlines()):
        problems.append("正常系なのに ERROR 行があります")
    return problems


# --- 入口まわり (直置き・監査構造・サイズ) ---

def case_root_loose_file(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.workspace / "loose.txt").write_text("x", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[直置き]")
    return problems


def case_agents_oversize(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    agents = ctx.home / "AGENTS.md"
    agents.write_text(agents.read_text(encoding="utf-8") + "あ" * 3100, encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "WARN  [サイズ]")
    return problems


# --- プロジェクト単体 ---

def case_project_bad_name(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    ctx.project.rename(ctx.project.parent / "テストサンプル")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[命名]")
    return problems


def case_project_missing_dir(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "inputs").rmdir()
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[構成]")
    return problems


def case_project_stray_file(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "memo.txt").write_text("x", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[直置き]")
    return problems


def case_project_stray_dir(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "謎フォルダ").mkdir()
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "想定外のフォルダ")
    return problems


def case_project_symlink(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    os.symlink("INDEX.md", ctx.project / "files" / "link.md")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[想定外]")
    return problems


def case_index_missing_label(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    text = (ctx.project / "INDEX.md").read_text(encoding="utf-8")
    (ctx.project / "INDEX.md").write_text(
        text.replace("- チャットID：chat-id-0001\n", ""), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[INDEX]")
    return problems


def case_index_broken_encoding(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "INDEX.md").write_bytes(b"\xff\xfe broken")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[読込]")
    return problems


def case_chat_name_mismatch(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    text = (ctx.project / "INDEX.md").read_text(encoding="utf-8")
    (ctx.project / "INDEX.md").write_text(
        text.replace("テスト_サンプル", "別の名前_テーマ"), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[チャット名]")
    return problems


def case_chat_json_broken(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "chat.json").write_text("{invalid json", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "chat.json が読めません")
    return problems


def case_chat_json_broken_encoding(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "chat.json").write_bytes(b"\xff\xfe broken")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "chat.json が読めません")
    return problems


def case_ambiguous_filename(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "files" / "final.txt").write_text("x", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "WARN  [ファイル名]")
    return problems


# --- 一覧・ゴールとの照合 ---

def case_list_row_missing(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    text = (ctx.workspace / "projects" / "PROJECT_LIST.md").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if "テスト_サンプル" not in ln]
    (ctx.workspace / "projects" / "PROJECT_LIST.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[一覧]")
    return problems


def case_list_malformed_row(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    path = ctx.workspace / "projects" / "PROJECT_LIST.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        " | テストゴール（goal_test000000001） | 進行中 |", " | 進行中 |"), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "行形式が想定と違います")
    return problems


def case_goal_assignment_mismatch(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    path = ctx.workspace / "projects" / "PROJECT_LIST.md"
    path.write_text(path.read_text(encoding="utf-8").replace(
        "テストゴール（goal_test000000001）", "なし"), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[ゴール]")
    return problems


def case_goal_dir_without_goalmd(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.workspace / "goals" / "ghost").mkdir()
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[ゴール構造]")
    return problems


def case_goal_named_folder_missing(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    named = ctx.workspace / "goals" / "test-goal" / "テストゴール"
    (named / "GOAL.md").unlink()
    named.rmdir()
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[ゴール構造]")
    return problems


# --- GitHub登録・リリース件数 ---

def case_github_url_mismatch(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    gh = ctx.add_github()
    # URL だけをずらす (リポジトリ欄は元のまま)
    (gh / "REPO.md").write_text(REPO_TEXT.replace(
        "https://github.com/owner/test-repo", "https://github.com/owner/other-repo"),
        encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[GitHub]")
    return problems


def case_github_bad_visibility(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    gh = ctx.add_github()
    (gh / "REPO.md").write_text(REPO_TEXT.replace("private", "社内"), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[GitHub]")
    return problems


def case_github_stray_file(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    gh = ctx.add_github()
    (gh / "memo.txt").write_text("x", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[GitHub]")
    return problems


def case_github_history_missing(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    gh = ctx.add_github()
    (gh / "REPO.md").write_text(REPO_TEXT.replace("- 履歴：../../監査コード\n", ""), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "「履歴：」の記載がありません")
    return problems


def case_github_history_not_a_repo(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    gh = ctx.add_github()
    (gh / "REPO.md").write_text(REPO_TEXT.replace("- 履歴：../../監査コード", "- 履歴：files"), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "Git リポジトリではありません")
    return problems


def _set_pending(ctx: Ctx, count: int) -> None:
    ctx.add_github()
    items = "".join(f"- 改良{i}\n" for i in range(1, count + 1))
    (ctx.project / "hidden_files" / "リリース予定.md").write_text(
        "# リリース予定\n\n" + items, encoding="utf-8")


def case_release_pending_boundary(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    _set_pending(ctx, 15)
    code, out = ctx.run(verbose=True)
    ctx.expect(problems, code, out, 0, "未配布の改良 15 件")
    if "WARN  [リリース]" in out:
        problems.append("15件ちょうどなのに警告が出ています")
    return problems


def case_release_pending_over(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    _set_pending(ctx, 16)
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "WARN  [リリース]")
    return problems


# --- 配布物の整合 ---

def _add_distribution(ctx: Ctx, version_text: str = "1.0.0", extra_file: bool = False) -> None:
    folder = ctx.project / "files" / "配布版_v1.0.0"
    folder.mkdir()
    (folder / "VERSION").write_text(version_text + "\n", encoding="utf-8")
    (folder / "CHANGELOG.md").write_text("## [1.0.0]\n\n- 初版\n", encoding="utf-8")
    (folder / "README.md").write_text("# 配布\n", encoding="utf-8")
    if extra_file:
        (folder / "EXTRA.md").write_text("x", encoding="utf-8")
    zpath = ctx.project / "files" / "テスト製品_v1.0.0.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for name in ("VERSION", "CHANGELOG.md", "README.md"):
            z.write(folder / name, f"配布版_v1.0.0/{name}")


def case_release_pending_broken_encoding(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    ctx.add_github()
    (ctx.project / "hidden_files" / "リリース予定.md").write_bytes(b"\xff\xfe broken")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[読込]")
    return problems


def _add_declared_doc(ctx: Ctx, body: str) -> None:
    (ctx.project / "hidden_files" / "メモ.md").write_text(body, encoding="utf-8")


def case_refs_missing_path(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    _add_declared_doc(ctx, "# メモ\n\n参照チェック：対象\n\n参照は `存在しない場所/資料.md` です。\n")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "参照先が見つかりません")
    return problems


def case_refs_missing_name(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    _add_declared_doc(ctx, "# メモ\n\n参照チェック：対象\n\n設定は MISSING_REFERENCE_TOKEN で決まります。\n")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "他に現れない名前です")
    return problems


def case_refs_exempt(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    _add_declared_doc(ctx, "# メモ\n\n参照チェック：対象\n参照チェック対象外：存在しない場所/資料.md、MISSING_REFERENCE_TOKEN\n\n参照は `存在しない場所/資料.md` と MISSING_REFERENCE_TOKEN です。\n")
    code, out = ctx.run()
    if "参照先が見つかりません" in out or "他に現れない名前です" in out:
        problems.append("対象外に宣言した参照が警告されました")
    return problems


def case_refs_ok(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    _add_declared_doc(ctx, "# メモ\n\n参照チェック：対象\n\n参照は `監査コード/checks/audit_common.py` と MUSE_AUDIT_ROOT です。\n")
    code, out = ctx.run()
    if "参照先が見つかりません" in out or "他に現れない名前です" in out:
        problems.append("実在する参照が警告されました")
    return problems


def case_refs_mention_not_declared(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "hidden_files" / "メモ.md").write_text(
        "# メモ\n\n「参照チェック：対象」と宣言した文書だけが照合されます。\n\n- `存在しない.md` への参照\n", encoding="utf-8")
    code, out = ctx.run()
    if code != 0:
        problems.append(f"終了コードが {code} (期待: 0)")
    if "参照先が見つかりません" in out or "他に現れない名前です" in out:
        problems.append("宣言していない文書が参照チェックされました")
    return problems


def case_fresh_index_listing_missing(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    index = ctx.project / "INDEX.md"
    index.write_text(index.read_text(encoding="utf-8") + "\n## フォルダ構成\n\n- `files/` — 成果物\n- `存在しない/` — 説明\n", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "フォルダ構成に載っている")
    return problems


def case_fresh_self_count_mismatch(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "hidden_files" / "メモ.md").write_text(
        "# メモ\n\n参照チェック：対象\n\n全3項目あります。\n\n1. ひとつ\n2. ふたつ\n", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "主張と")
    return problems


def case_fresh_pointer_stale(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    gh = ctx.add_github()
    (gh / "REPO.md").write_text(REPO_TEXT.replace("- 同期元：files", "- 同期元：files/配布版_v1.0.0"), encoding="utf-8")
    for version in ("v1.0.0", "v1.1.0"):
        folder = ctx.project / "files" / f"配布版_{version}"
        folder.mkdir()
        (folder / "README.md").write_text("x", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "より新しい配布版")
    return problems


def case_fresh_stale_dated(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.project / "hidden_files" / "メモ.md").write_text(
        "# メモ\n\n現況（2020-01-01 時点）です。\n", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "2020-01-01")
    return problems


def case_fresh_structure_divergence(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    ctx.run()  # 基準の状態を作る
    ctx.add_github()
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "構成が変わりましたが")
    return problems


def case_fresh_parts_list_mismatch(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    doc = ctx.workspace / "監査コード" / "監査ルール.md"
    doc.write_text(doc.read_text(encoding="utf-8").replace("`audit_shelf.py`", "`audit_shelf_OLD.py`", 1), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "部品一覧")
    return problems


def case_distribution_ok(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    _add_distribution(ctx)
    code, out = ctx.run(verbose=True)
    ctx.expect(problems, code, out, 0, "[配布]")
    return problems


def case_distribution_version_mismatch(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    _add_distribution(ctx, version_text="9.9.9")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[配布]")
    return problems


def case_distribution_zip_mismatch(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    _add_distribution(ctx, extra_file=True)
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[配布]")
    return problems


# --- 本棚 ---

def case_shelf_unregistered(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    (ctx.home / "本棚" / "agents" / "未登録.md").write_text("# 未登録\n", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[本棚]")
    return problems


# --- 増分監査 ---

def case_incremental_skip_and_carry(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "[全件]")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "省略 1/1件")
    # 壊すと再検査されて検出される
    text = (ctx.project / "INDEX.md").read_text(encoding="utf-8")
    (ctx.project / "INDEX.md").write_text(
        text.replace("テスト_サンプル", "別の名前_テーマ"), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "[チャット名]")
    # 変化なしの次回は、再検査せずに問題が引き継がれる
    code, out = ctx.run()
    ctx.expect(problems, code, out, 1, "前回検出・変化なしのため再検査を省略")
    # 直すと再検査されて解消する
    text = (ctx.project / "INDEX.md").read_text(encoding="utf-8")
    (ctx.project / "INDEX.md").write_text(
        text.replace("別の名前_テーマ", "テスト_サンプル"), encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "判定: 問題なし")
    return problems


def case_incremental_state_corrupt(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0)
    state = ctx.workspace / "監査コード" / ".audit-state.json"
    state.write_text("garbage{", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "[全件]")
    try:
        json.loads(state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        problems.append("状態ファイルが作り直されていません")
    return problems


def case_incremental_code_change(ctx: Ctx) -> list[str]:
    problems: list[str] = []
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0)
    part = ctx.workspace / "監査コード" / "checks" / "audit_shelf.py"
    part.write_text(part.read_text(encoding="utf-8") + "\n# touch\n", encoding="utf-8")
    code, out = ctx.run()
    ctx.expect(problems, code, out, 0, "監査コードが変わったため")
    return problems


# ケース名 -> (関数, 対象部品)。common は全ケース共通で暗黙に対象。
CASES: dict[str, tuple] = {
    "healthy": (case_healthy, ["check_project", "cross", "shelf", "entry", "state"]),
    "root_loose_file": (case_root_loose_file, ["entry"]),
    "agents_oversize": (case_agents_oversize, ["entry"]),
    "project_bad_name": (case_project_bad_name, ["check_project"]),
    "project_missing_dir": (case_project_missing_dir, ["check_project"]),
    "project_stray_file": (case_project_stray_file, ["check_project"]),
    "project_stray_dir": (case_project_stray_dir, ["check_project"]),
    "project_symlink": (case_project_symlink, ["check_project"]),
    "index_missing_label": (case_index_missing_label, ["check_project"]),
    "index_broken_encoding": (case_index_broken_encoding, ["check_project"]),
    "chat_name_mismatch": (case_chat_name_mismatch, ["check_project"]),
    "chat_json_broken": (case_chat_json_broken, ["check_project"]),
    "chat_json_broken_encoding": (case_chat_json_broken_encoding, ["check_project"]),
    "ambiguous_filename": (case_ambiguous_filename, ["check_project"]),
    "list_row_missing": (case_list_row_missing, ["cross"]),
    "list_malformed_row": (case_list_malformed_row, ["cross"]),
    "goal_assignment_mismatch": (case_goal_assignment_mismatch, ["cross"]),
    "goal_dir_without_goalmd": (case_goal_dir_without_goalmd, ["entry"]),
    "goal_named_folder_missing": (case_goal_named_folder_missing, ["entry"]),
    "github_url_mismatch": (case_github_url_mismatch, ["check_project"]),
    "github_bad_visibility": (case_github_bad_visibility, ["check_project"]),
    "github_stray_file": (case_github_stray_file, ["check_project"]),
    "github_history_missing": (case_github_history_missing, ["check_project"]),
    "github_history_not_a_repo": (case_github_history_not_a_repo, ["check_project"]),
    "release_pending_boundary": (case_release_pending_boundary, ["check_project"]),
    "release_pending_over": (case_release_pending_over, ["check_project"]),
    "release_pending_broken_encoding": (case_release_pending_broken_encoding, ["check_project"]),
    "refs_missing_path": (case_refs_missing_path, ["refs"]),
    "refs_missing_name": (case_refs_missing_name, ["refs"]),
    "refs_exempt": (case_refs_exempt, ["refs"]),
    "refs_ok": (case_refs_ok, ["refs"]),
    "refs_mention_not_declared": (case_refs_mention_not_declared, ["refs"]),
    "fresh_index_listing_missing": (case_fresh_index_listing_missing, ["fresh"]),
    "fresh_self_count_mismatch": (case_fresh_self_count_mismatch, ["fresh"]),
    "fresh_pointer_stale": (case_fresh_pointer_stale, ["fresh"]),
    "fresh_stale_dated": (case_fresh_stale_dated, ["fresh"]),
    "fresh_structure_divergence": (case_fresh_structure_divergence, ["fresh", "state"]),
    "fresh_parts_list_mismatch": (case_fresh_parts_list_mismatch, ["fresh"]),
    "distribution_ok": (case_distribution_ok, ["check_project"]),
    "distribution_version_mismatch": (case_distribution_version_mismatch, ["check_project"]),
    "distribution_zip_mismatch": (case_distribution_zip_mismatch, ["check_project"]),
    "shelf_unregistered": (case_shelf_unregistered, ["shelf"]),
    "incremental_skip_and_carry": (case_incremental_skip_and_carry, ["state", "entry"]),
    "incremental_state_corrupt": (case_incremental_state_corrupt, ["state", "entry"]),
    "incremental_code_change": (case_incremental_code_change, ["state", "entry", "shelf"]),
}
