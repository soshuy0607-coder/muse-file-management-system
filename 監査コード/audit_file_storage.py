#!/usr/bin/env python3
"""ファイル置き場の監査コード (入口)。

使い方:
    python3 ~/workspace/監査コード/audit_file_storage.py [--verbose]

既定は要約表示 (OKは集約、エラー・警告は全件)。--verbose で OK も全行出す。

ルールの詳細は隣の 監査ルール.md を見ること。このファイルは実行の入口と
全体の照合 (一覧・ゴール)、増分監査の取りまとめ (状態の読み書きと
省略の判断) を持ち、個別の照合は checks/ の部品に分割してある。
終了コード: 問題 (ERROR) があれば 1、なければ 0。標準ライブラリのみ。
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True  # 部品の読み込みで __pycache__ を作らない
sys.path.insert(0, str(Path(__file__).resolve().parent / "checks"))

from audit_common import (  # noqa: E402
    read_text_report,
    ALLOWED_AUDIT_DIRS,
    AGENTS_CHAR_LIMIT,
    AGENTS_FILE,
    ALLOWED_AUDIT_FILES,
    ALLOWED_PROJECTS_FILES,
    ALLOWED_ROOT_FILES,
    ARCHIVE,
    AUDIT_DIR,
    GOALS_DIR,
    LIST_FILE,
    PROJECTS,
    ROOT,
    Results,
    parse_goal_entries,
    validate_root,
)
from audit_check_project import check_project  # noqa: E402
from audit_state import (  # noqa: E402
    audit_code_fingerprint,
    fresh_base,
    full_audit_reason,
    load_state,
    project_fingerprint,
    save_state,
)
from audit_cross import collect_project_info, parse_project_list, project_list_problems  # noqa: E402
from audit_shelf import check_shelves  # noqa: E402
from audit_refs import check_references  # noqa: E402
from audit_fresh import check_freshness  # noqa: E402


def check_audit_dir(res: Results) -> None:
    """監査コードフォルダ自身の構成 (直下は入口・ルール文書・例外のみ)。"""
    if not AUDIT_DIR.is_dir():
        res.error("[監査構造] 監査コード/ フォルダがありません")
        return
    bad = []
    for entry in sorted(AUDIT_DIR.iterdir()):
        if entry.name.startswith((".audit-state.json.", ".test-state.json.")) and entry.name.endswith(".tmp"):
            continue  # 状態保存の一時ファイル (残っていても想定内)
        if entry.is_file() and entry.name not in ALLOWED_AUDIT_FILES:
            bad.append(entry.name)
        if entry.is_dir() and entry.name not in ALLOWED_AUDIT_DIRS:
            bad.append(entry.name + "/")
    for name in bad:
        res.error(f"[監査構造] 監査コード直下に想定外のものがあります: {name}")
    if not bad:
        res.ok("[監査構造] 監査コード直下の構成が正しい")
    # 部品フォルダ (checks/ と tests/) の中身 (Python部品のみ。__pycache__ は生成物なので対象外)
    for dirname in ("checks", "tests"):
        parts_dir = AUDIT_DIR / dirname
        if not parts_dir.is_dir():
            res.error(f"[監査構造] {dirname}/ フォルダがありません")
            continue
        bad_parts = []
        for entry in sorted(parts_dir.iterdir()):
            if entry.name == "__pycache__":
                continue
            if entry.is_file() and entry.suffix == ".py":
                continue
            bad_parts.append(entry.name + ("/" if entry.is_dir() else ""))
        for name in bad_parts:
            res.error(f"[監査構造] {dirname}/ に想定外のものがあります: {name}")
        if not bad_parts:
            res.ok(f"[監査構造] {dirname}/ の中身はPython部品のみ")


def check_agents_size(res: Results) -> None:
    """全体用AGENTS.md のサイズ (毎回読み込まれるため上限を警告で担保)。"""
    if not AGENTS_FILE.is_file():
        res.warn("[サイズ] 全体用AGENTS.md が見つかりません")
        return
    size = len(AGENTS_FILE.read_text(encoding="utf-8", errors="replace"))
    if size > AGENTS_CHAR_LIMIT:
        res.warn(f"[サイズ] 全体用AGENTS.md が上限超過です ({size} / {AGENTS_CHAR_LIMIT} 文字)。"
                 "詳細は 監査コード/監査ルール.md へ移してください")
    else:
        res.ok(f"[サイズ] 全体用AGENTS.md は上限内 ({size} / {AGENTS_CHAR_LIMIT} 文字)")


def check_list_cross(res: Results, disk: dict[str, Path]) -> None:
    """PROJECT_LIST.md と実態の双方向照合、担当ゴール、ゴール側表記。"""
    if not LIST_FILE.is_file():
        res.error("[一覧] projects/PROJECT_LIST.md がありません")
        return
    list_text = read_text_report(res, LIST_FILE, "PROJECT_LIST")
    if list_text is None:
        return
    for problem in project_list_problems(list_text):
        res.error(f"[一覧] PROJECT_LIST.md の行形式が想定と違います ({problem})")
    entries = parse_project_list(list_text)
    info_cache: dict[str, dict] = {}

    def info_of(project: Path) -> dict:
        key = str(project)
        if key not in info_cache:
            info_cache[key] = collect_project_info(project)
        return info_cache[key]
    if not entries:
        res.error("[一覧] PROJECT_LIST.md にプロジェクト行がありません")
    seen_chat_ids: set[str] = set()
    for rel, row in entries.items():
        if row["chat_id"] in seen_chat_ids:
            res.error(f"[一覧] チャットIDが重複しています: {row['chat_id']}")
        seen_chat_ids.add(row["chat_id"])
        if rel not in disk:
            res.error(f"[一覧] 一覧にあるが実在しないプロジェクトです: {rel}")
    for rel, project in disk.items():
        if rel not in entries:
            res.error(f"[一覧] 一覧に書かれていないプロジェクトがあります: {rel}")
            continue
        row = entries[rel]
        info = info_of(project)
        if info.get("project") and row["project"] != info["project"]:
            res.error(
                f"[一覧] {rel}: 一覧のプロジェクト名「{row['project']}」が INDEX と一致しません")
        if row["chat"] != project.name:
            res.error(
                f"[一覧] {rel}: 一覧のチャット名「{row['chat']}」がフォルダ名と一致しません")
        expected_id = info.get("actual_chat_id") or info.get("chat_id")
        if expected_id and row["chat_id"] != expected_id:
            res.error(
                f"[一覧] {rel}: 一覧に書かれていないチャットです (ID: {expected_id})")
        # 担当ゴールの一致 (IDをキーの集合で照合)
        if "goal_raw" not in info:
            res.error(f"[ゴール] {rel}: INDEXに担当ゴールの記載がありません (無い場合は「なし」)")
        else:
            index_goals = parse_goal_entries(info["goal_raw"])
            list_goals = parse_goal_entries(row.get("goal", ""))
            if info["goal_raw"] != "なし" and not index_goals:
                res.error(
                    f"[ゴール] {rel}: INDEXの担当ゴールが「ゴール名（ゴールID）」形式になっていません")
            elif index_goals != list_goals:
                only_index = sorted(set(index_goals) - set(list_goals))
                only_list = sorted(set(list_goals) - set(index_goals))
                diff_titles = sorted(g for g in set(index_goals) & set(list_goals)
                                     if index_goals[g] != list_goals[g])
                detail = []
                if only_index:
                    detail.append(f"INDEXにのみあるゴール: {only_index}")
                if only_list:
                    detail.append(f"一覧にのみあるゴール: {only_list}")
                if diff_titles:
                    detail.append(f"名前が食い違うゴール: {diff_titles}")
                res.error(f"[ゴール] {rel}: 担当ゴールが一覧とINDEXで一致しません ({'; '.join(detail)})")
            else:
                res.ok(f"[ゴール] {rel}: 担当ゴールが一覧とINDEXで一致 ({len(index_goals)}件)")
    if not any(e.startswith("[一覧]") for e in res.errors):
        res.ok("[一覧] PROJECT_LIST.md と実在プロジェクト／チャットが一致")

    # ゴール側の「担当プロジェクト：{…}」と割り当て実態の照合
    goal_projects: dict[str, set[str]] = {}
    for project in disk.values():
        pinfo = info_of(project)
        pname = pinfo.get("project")
        if pname and "goal_raw" in pinfo:
            for gid in parse_goal_entries(pinfo["goal_raw"]):
                goal_projects.setdefault(gid, set()).add(pname)
    goal_notes: dict[str, set[str] | None] = {}
    if GOALS_DIR.is_dir():
        for goal_md in sorted(GOALS_DIR.glob("*/GOAL.md")):
            gtext = read_text_report(res, goal_md, "GOAL.md")
            if gtext is None:
                continue
            mid = re.search(r"^Goal ID:\s*(goal_\S+)", gtext, flags=re.MULTILINE)
            if not mid:
                res.warn(f"[ゴール表記] {goal_md.parent.name}: GOAL.md に Goal ID の記載がありません")
                continue
            mnote = re.search(r"担当プロジェクト：\{([^}]*)\}", gtext)
            if mnote is None:
                goal_notes[mid.group(1)] = None
            else:
                inner = mnote.group(1).strip()
                goal_notes[mid.group(1)] = (
                    {n.strip() for n in re.split(r"[,、]", inner) if n.strip()}
                    if inner else set())
    for gid, expected in sorted(goal_projects.items()):
        if gid not in goal_notes:
            res.error(f"[ゴール表記] {gid}: GOAL.md が見つかりません")
        elif goal_notes[gid] is None:
            res.error(f"[ゴール表記] {gid}: GOAL.md に「担当プロジェクト：{{…}}」の記載がありません")
        elif goal_notes[gid] != expected:
            res.error(
                f"[ゴール表記] {gid}: 担当プロジェクト表記 {sorted(goal_notes[gid])} が割り当て実態 {sorted(expected)} と一致しません")
        else:
            res.ok(f"[ゴール表記] {gid}: 担当プロジェクト {{…}} が割り当て実態と一致")


def check_goal_structure(res: Results) -> None:
    """ゴール名フォルダと GOAL.md リンクの確認。"""
    if not GOALS_DIR.is_dir():
        return
    for goal_dir in sorted(GOALS_DIR.iterdir()):
        if goal_dir.is_dir() and not (goal_dir / "GOAL.md").is_file():
            res.error(f"[ゴール構造] {goal_dir.name}: GOAL.md がありません")
    for goal_md in sorted(GOALS_DIR.glob("*/GOAL.md")):
        gtext = read_text_report(res, goal_md, "GOAL.md")
        if gtext is None:
            continue
        mtitle = re.search(r"^#\s*(.+)$", gtext, flags=re.MULTILINE)
        if not mtitle:
            continue
        title = mtitle.group(1).strip()
        workspace = goal_md.parent
        named_dir = workspace / title
        if not named_dir.is_dir():
            res.error(f"[ゴール構造] {title}: ゴール名フォルダがありません ({workspace.name}/ の中)")
            continue
        nested = named_dir / "GOAL.md"
        if not nested.is_file():
            res.error(f"[ゴール構造] {title}: ゴール名フォルダの中に GOAL.md がありません")
            continue
        try:
            same = os.path.samefile(goal_md, nested)
        except OSError:
            same = False
        if not same and nested.read_text(encoding="utf-8", errors="replace") != gtext:
            res.error(f"[ゴール構造] {title}: ゴール名フォルダの GOAL.md が本体と同一ではありません")
        else:
            res.ok(f"[ゴール構造] {title}: ゴール名フォルダと GOAL.md リンクあり")


def main() -> int:
    verbose = "--verbose" in sys.argv
    validate_root()
    res = Results()
    # workspace/ 直下 (ファイルは置かない)
    loose_root = [e.name for e in sorted(ROOT.iterdir())
                  if e.is_file() and e.name not in ALLOWED_ROOT_FILES]
    for fname in loose_root:
        res.error(f"[直置き] workspace直下に許可されていないファイルがあります: {fname}")
    if not loose_root:
        res.ok("[直置き] workspace直下にファイルなし")

    check_audit_dir(res)
    check_agents_size(res)

    if not PROJECTS.is_dir():
        res.error("[構成] projects/ がありません")
        report(res, verbose=verbose)
        return 1

    # projects/ 直下のファイルは PROJECT_LIST.md のみ
    loose = [e.name for e in sorted(PROJECTS.iterdir())
             if e.is_file() and e.name not in ALLOWED_PROJECTS_FILES]
    for fname in loose:
        res.error(f"[直置き] projects直下に許可されていないファイルがあります: {fname}")
    if not loose:
        res.ok("[直置き] projects直下のファイルは一覧のみ")

    # 増分監査: 変化のないプロジェクトは個別チェックを省略し、
    # 前回の問題は引き継いで表示する。判断はコード自身が行う。
    now = datetime.now().astimezone()
    code_fp = audit_code_fingerprint()
    state = load_state()
    reason = full_audit_reason(state, code_fp, now)
    full = reason is not None
    if full:
        res.ok(f"[全件] 全件監査を実施しました ({reason})")
    prev_projects: dict = state["projects"] if state else {}
    new_projects: dict[str, dict] = {}

    def process(project: Path, rel: str) -> None:
        fp = project_fingerprint(project)
        prev = prev_projects.get(rel)
        if not full and prev and prev.get("fingerprint") == fp:
            res.ok(f"[省略] {project.name}: 変化なしのため個別チェックを省略"
                   f" (前回確認 {prev.get('checked_at', '日時不明')})")
            for prob in prev.get("problems", []):
                text = prob["text"] + " (前回検出・変化なしのため再検査を省略)"
                if prob["level"] == "error":
                    res.error(text)
                else:
                    res.warn(text)
            new_projects[rel] = prev
            return
        w0, e0 = len(res.warnings), len(res.errors)
        check_project(res, project)
        problems = ([{"level": "warn", "text": m} for m in res.warnings[w0:]]
                    + [{"level": "error", "text": m} for m in res.errors[e0:]])
        new_projects[rel] = {"fingerprint": fp,
                             "checked_at": now.strftime("%Y-%m-%d %H:%M"),
                             "problems": problems,
                             "fresh_base": fresh_base(project)}

    # 実在プロジェクト (相対パス -> フォルダ)。アーカイブは _archive/<名前>
    disk: dict[str, Path] = {}
    projects = [p for p in sorted(PROJECTS.iterdir()) if p.is_dir() and p.name != "_archive"]
    for project in projects:
        disk[project.name] = project
        process(project, project.name)
    archived = []
    if ARCHIVE.is_dir():
        archived = [p for p in sorted(ARCHIVE.iterdir()) if p.is_dir()]
        for project in archived:
            disk[f"_archive/{project.name}"] = project
            process(project, f"_archive/{project.name}")

    new_state = {
        "version": 1,
        "last_full_audit_at": (now.isoformat(timespec="seconds") if full
                               else state["last_full_audit_at"]),
        "runs_since_full": (0 if full else int(state.get("runs_since_full", 0)) + 1),
        "audit_code_fingerprint": code_fp,
        "projects": new_projects,
    }
    if not save_state(new_state):
        res.warn("[状態] 監査の状態を保存できませんでした (次回は全件監査になります)")

    check_shelves(res)
    check_list_cross(res, disk)
    check_goal_structure(res)
    check_references(res)
    check_freshness(
        res,
        {rel: e.get("fresh_base") for rel, e in prev_projects.items()},
        {rel: e.get("fresh_base") for rel, e in new_projects.items()})

    report(res, len(projects), [p.name for p in projects], len(archived), verbose)
    return 1 if res.errors else 0


def report(res: Results, project_count: int | None = None,
           project_names: list[str] | None = None, archived_count: int = 0,
           verbose: bool = False) -> None:
    print("=== ファイル置き場 監査結果 ===")
    total = (project_count or 0) + archived_count
    if project_count is not None:
        print(f"対象プロジェクト: {project_count} 件 (アーカイブ済み: {archived_count} 件)")
        if verbose:
            for n in project_names or []:
                print(f"  - {n}")
    if verbose:
        for line in res.oks:
            print(f"OK    {line}")
    else:
        # プロジェクト個別のOKは集約し、それ以外はそのまま出す
        categories = [("命名", "命名"), ("チャット名", "チャット名"), ("ゴール", "担当ゴール"),
                      ("GitHub", "GitHub登録"), ("リリース", "リリース"), ("配布", "配布"), ("省略", "省略")]
        per_project: dict[str, set[str]] = {c: set() for c, _ in categories}
        others: list[str] = []
        for line in res.oks:
            grouped = False
            for category in per_project:
                prefix = f"[{category}] "
                if line.startswith(prefix):
                    subject = line[len(prefix):].split(":")[0].strip()
                    per_project[category].add(subject)
                    grouped = True
                    break
            if not grouped:
                others.append(line)
        for line in others:
            print(f"OK    {line}")
        if total:
            parts = [f"{label} {len(per_project[c])}/{total}件" for c, label in categories[:3]]
            for category, label in categories[3:]:
                if per_project[category]:
                    parts.append(f"{label} {len(per_project[category])}/{total}件")
            print("OK    [要約] プロジェクト個別チェック: " + "、".join(parts))
    for line in res.warnings:
        print(f"WARN  {line}")
    for line in res.errors:
        print(f"ERROR {line}")
    print(f"--- OK {len(res.oks)} / WARN {len(res.warnings)} / ERROR {len(res.errors)}")
    print("判定:", "問題あり" if res.errors else "問題なし")
    if not verbose:
        print("(要約表示です。OKの全行は --verbose で出ます)")


if __name__ == "__main__":
    sys.exit(main())
