"""鮮度・自己記述の警告 (監査ルール21)。

「メンテナンスが必要かもしれない」兆候を、警告レベルで知らせる。
直すかどうかは判断の側に残し、検知だけを機械が担う。
信号は、変わったものと変わっていないものの差で定義できる
ものだけに絞る。

- 文書内の自己整合: 宣言した文書 (ルール20と同じ宣言) の
  「全N項目・全N件」という主張と、文書内の最長の番号付き
  一覧の実数の照合。
- 構成の列挙と実態: プロジェクト INDEX の「フォルダ構成」に
  列挙された名前の実在と、監査ルール.md 第1節の部品一覧と
  実際の部品ファイルの集合の一致。
- 鮮度の乖離: プロジェクト直下の顔ぶれ (ファイル・フォルダの
  集合) が前回から変わったのに、INDEX.md の内容が変わって
  いない場合に警告する。内容の編集では鳴らない。
- 現行ポインタ: GitHub登録の同期元が、実在する配布版の中で
  最新版を指していない場合に警告する。
- 日付つき現況の経年: 「YYYY-MM-DD 時点」と書かれた記述が
  30日を超えたら見直し候補として警告する。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

from audit_common import AUDIT_DIR, GOALS_DIR, PROJECTS, ROOT, Results
from audit_refs import DECLARE_RE

CLAIM_RE = re.compile(r"全(\d+)(?:項目|件)")
NUMBERED_RE = re.compile(r"^(\d+)[.．]\s", flags=re.MULTILINE)
DATED_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*時点")
SYNC_RE = re.compile(r"^-\s*同期元[:：]\s*(.+)$", flags=re.MULTILINE)
DIST_RE = re.compile(r"配布版_v(\d+)\.(\d+)\.(\d+)$")
STALE_DAYS = 30


def _disp(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _projects() -> list[Path]:
    if not PROJECTS.is_dir():
        return []
    return [p for p in sorted(PROJECTS.iterdir())
            if p.is_dir() and p.name != "_archive"]


def _check_self_counts(res: Results, doc: Path, text: str) -> None:
    claims = {int(n) for n in CLAIM_RE.findall(text)}
    if not claims:
        return
    numbers = [int(n) for n in NUMBERED_RE.findall(text)]
    longest = run = 0
    expect = 1
    for n in numbers:
        run = run + 1 if n == expect else (1 if n == 1 else 0)
        expect = n + 1
        longest = max(longest, run)
    if longest == 0:
        return
    for claim in sorted(claims):
        if claim != longest:
            res.warn(f"[鮮度] {_disp(doc)}: 「全{claim}」の主張と、文書内の"
                     f"項目数 {longest} が一致しません")


def _check_index_listing(res: Results, project: Path) -> None:
    text = _read(project / "INDEX.md")
    if text is None:
        return
    section = None
    current: list[str] = []
    for line in text.splitlines():
        if re.match(r"^#{1,4}\s", line):
            if section is not None:
                break
            if "フォルダ構成" in line:
                section = current
            continue
        if section is not None:
            section.append(line)
    if section is None:
        return
    tokens = []
    for line in section:
        if line.lstrip().startswith("- "):
            found = re.search(r"`([^`\n]+)`", line)
            if found:
                tokens.append(found.group(1))
    for token in sorted(set(tokens)):
        if token in (".", ".."):
            continue
        target = project / token
        ok = target.is_dir() if token.endswith("/") else target.exists()
        if not ok:
            res.warn(f"[鮮度] {project.name}: INDEX のフォルダ構成に載っている"
                     f" {token} が実在しません")


def _check_parts_list(res: Results) -> None:
    text = _read(AUDIT_DIR / "監査ルール.md")
    if text is None or "## 1." not in text or "## 2." not in text:
        return
    section = text.split("## 1.", 1)[1].split("## 2.", 1)[0]
    listed = set(re.findall(r"`([A-Za-z_]+\.py)`", section))
    actual = {"audit_file_storage.py"}
    for sub in ("checks", "tests"):
        folder = AUDIT_DIR / sub
        if folder.is_dir():
            actual |= {p.name for p in folder.glob("*.py")}
    for name in sorted(actual - listed):
        res.warn(f"[鮮度] 監査ルール.md 第1節の部品一覧に {name} が載っていません")
    for name in sorted(listed - actual):
        res.warn(f"[鮮度] 監査ルール.md 第1節の部品一覧にある {name} が実在しません")


def _check_divergence(res: Results, prev_bases: dict, cur_bases: dict) -> None:
    for rel, cur in cur_bases.items():
        prev = prev_bases.get(rel)
        if not prev or not cur:
            continue
        if set(prev.get("top", [])) == set(cur.get("top", [])):
            continue
        if prev.get("index") == cur.get("index"):
            name = rel.split("/")[-1]
            res.warn(f"[鮮度] {name}: プロジェクト直下の構成が変わりましたが"
                     f" INDEX.md は更新されていません (見直し候補)")


def _check_sync_pointer(res: Results, project: Path) -> None:
    repo_file = project / "github" / "REPO.md"
    text = _read(repo_file)
    if text is None:
        return
    match = SYNC_RE.search(text)
    if not match:
        return
    source = match.group(1).strip()
    dist = DIST_RE.search(source)
    if not dist:
        return
    current = tuple(int(x) for x in dist.groups())
    files_dir = project / "files"
    if not files_dir.is_dir():
        return
    versions = []
    for folder in files_dir.glob("配布版_v*"):
        found = DIST_RE.search(folder.name)
        if folder.is_dir() and found:
            versions.append((tuple(int(x) for x in found.groups()), folder.name))
    if not versions:
        return
    newest = max(versions)
    if newest[0] > current:
        res.warn(f"[鮮度] {project.name}: 同期元 ({source}) より新しい"
                 f"配布版 {newest[1]} があります")


def _check_dated(res: Results) -> None:
    docs = []
    rules = AUDIT_DIR / "監査ルール.md"
    if rules.is_file():
        docs.append(rules)
    for project in _projects():
        docs.extend(sorted(project.rglob("*.md")))
    if GOALS_DIR.is_dir():
        docs.extend(sorted(GOALS_DIR.glob("*/GOAL.md")))
    today = datetime.now().date()
    for doc in docs:
        text = _read(doc)
        if text is None:
            continue
        for found in sorted(set(DATED_RE.findall(text))):
            try:
                stated = date.fromisoformat(found)
            except ValueError:
                continue
            age = (today - stated).days
            if age > STALE_DAYS:
                res.warn(f"[鮮度] {_disp(doc)}: 「{found} 時点」の記述が"
                         f" {age} 日経過しています (見直し候補)")


def check_freshness(res: Results, prev_fps: dict, cur_fps: dict) -> None:
    """鮮度・自己記述の警告 (ルール21)。prev/cur は鮮度比較材料の対応表。"""
    rules = AUDIT_DIR / "監査ルール.md"
    declared = []
    if rules.is_file():
        declared.append(rules)
    for project in _projects():
        declared.extend(sorted(project.rglob("*.md")))
    if GOALS_DIR.is_dir():
        declared.extend(sorted(GOALS_DIR.glob("*/GOAL.md")))
    for doc in declared:
        text = _read(doc)
        if text is not None and DECLARE_RE.search(text):
            _check_self_counts(res, doc, text)
    for project in _projects():
        _check_index_listing(res, project)
        _check_sync_pointer(res, project)
    _check_parts_list(res)
    _check_divergence(res, prev_fps, cur_fps)
    _check_dated(res)
