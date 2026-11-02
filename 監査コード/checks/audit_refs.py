"""文書の参照チェック (監査ルール20)。

宣言した文書だけを対象に、文書中の参照が実態と合っているかを
警告レベルで確認する。目的は、実在しない仕組みやファイルへの
言及 (書き手の誤認) に、次回の監査で気づけるようにすること。

検査は2つ:
- パス参照: バッククォートで囲まれたパス形式の文字列について、
  文書の場所・workspace・ホームを起点に実在を確認する。
- 名前参照: 定数名の形をした名前 (大文字とアンダースコア) に
  ついて、監査コード (入口と checks/) と他の管理文書の中に、
  その文書以外でも現れるかを確認する。配布版フォルダ内の文書は
  写しなので、現れる側の数には入れない。

どちらも警告のみ。意味の正しさまでは確認しない。
仕様上の語彙として書く参照などは、文書中の
「参照チェック対象外：」の行に列挙して宣言できる。
状態ファイルは実行時に生成されるため、実在として扱う。
"""

from __future__ import annotations

import re
from pathlib import Path

from audit_common import (
    AUDIT_DIR,
    GOALS_DIR,
    HOME_DIR,
    PROJECTS,
    ROOT,
    Results,
)

DECLARE_RE = re.compile(r"^\s*参照チェック[:：]\s*対象\s*$", re.MULTILINE)
EXEMPT_RE = re.compile(r"参照チェック対象外[:：]\s*(.+)")
SPAN_RE = re.compile(r"`([^`\n]+)`")
TOKEN_RE = re.compile(r"[A-Z][A-Z0-9]*_[A-Z0-9_]+")
SKIP_CHARS = (" ", "<", ">", "*", "…", "#", "://", "{", "}")
EXTS = (".md", ".py", ".json", ".zip", ".txt", ".csv")
GENERATED = {"監査コード/.audit-state.json", "監査コード/.test-state.json"}
GENERATED_NAMES = {Path(g).name for g in GENERATED}
# システムが定める構造上のファイル名 (語彙として常に実在扱いにする)
STRUCTURAL_NAMES = {"INDEX.md", "chat.json", "PROJECT_LIST.md", "GOAL.md",
                    "REPO.md", "監査ルール.md"}


def _target_docs() -> list:
    docs = []
    rules = AUDIT_DIR / "監査ルール.md"
    if rules.is_file():
        docs.append(rules)
    if PROJECTS.is_dir():
        docs.extend(sorted(PROJECTS.rglob("*.md")))
    if GOALS_DIR.is_dir():
        docs.extend(sorted(GOALS_DIR.glob("*/GOAL.md")))
    return docs


def _corpus_texts() -> list:
    """名前参照の「他に現れるか」を判定する側の文書群。

    (パス, 本文) の一覧。テストコードは意図的な偽物を含むため
    入れない。配布版フォルダ内の文書は写しなので入れない。
    """
    texts = []

    def add(path) -> None:
        try:
            texts.append((path, path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            pass

    add(AUDIT_DIR / "audit_file_storage.py")
    if (AUDIT_DIR / "checks").is_dir():
        for part in sorted((AUDIT_DIR / "checks").glob("*.py")):
            add(part)
    rules = AUDIT_DIR / "監査ルール.md"
    if rules.is_file():
        add(rules)
    if PROJECTS.is_dir():
        for doc in sorted(PROJECTS.rglob("*.md")):
            if any(part.startswith("配布版_v") for part in doc.parts):
                continue
            add(doc)
    if GOALS_DIR.is_dir():
        for goal_md in sorted(GOALS_DIR.glob("*/GOAL.md")):
            add(goal_md)
    for top in sorted(HOME_DIR.glob("*.md")):
        add(top)
    return texts


def _all_basenames() -> set:
    names = set()
    for base in (ROOT, HOME_DIR):
        if base.is_dir():
            for path in base.rglob("*"):
                if path.is_file():
                    names.add(path.name)
    return names


def _path_exists(span: str, doc_dir) -> bool:
    if span.startswith("~/"):
        return (HOME_DIR / span[2:]).exists()
    if span.startswith("workspace/"):
        rest = span[len("workspace/"):]
        return (ROOT / rest).exists() or rest in GENERATED
    if span in GENERATED:
        return True
    return any((base / span).exists() for base in (doc_dir, ROOT, HOME_DIR))


def _is_path_candidate(span: str) -> bool:
    if any(char in span for char in SKIP_CHARS):
        return False
    if "/" in span:
        return span.endswith(EXTS) or span.endswith("/")
    return span.endswith(EXTS)


def check_references(res: Results) -> None:
    """宣言した文書の参照チェック (パス参照と名前参照)。"""
    corpus = _corpus_texts()
    basenames = _all_basenames()
    for doc in _target_docs():
        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not DECLARE_RE.search(text):
            continue
        exemptions = set()
        for match in EXEMPT_RE.finditer(text):
            for item in re.split(r"[、,，\s]+", match.group(1).strip()):
                item = item.strip("`")
                if item:
                    exemptions.add(item)
        try:
            disp = doc.relative_to(ROOT).as_posix()
        except ValueError:
            disp = doc.name
        problems = 0
        for span in sorted(set(SPAN_RE.findall(text))):
            if span in exemptions or not _is_path_candidate(span):
                continue
            if "/" in span:
                found = _path_exists(span, doc.parent)
            else:
                found = (span in basenames or span in STRUCTURAL_NAMES
                         or span in GENERATED_NAMES)
            if not found:
                problems += 1
                res.warn(f"[参照] {disp}: 参照先が見つかりません: {span}")
        for token in sorted(set(TOKEN_RE.findall(text))):
            if token in exemptions:
                continue
            if not any(token in other for path, other in corpus if path != doc):
                problems += 1
                res.warn(f"[参照] {disp}: 他に現れない名前です: {token}")
        if problems == 0:
            res.ok(f"[参照] {disp}: 参照に問題なし")
