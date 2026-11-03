"""本棚の照合 (カタログの目次と棚フォルダの中身)。

カタログ (AGENTS.md など毎回読まれるファイル) の「本棚フォルダ：」宣言と
目次 (種別 | 題名 | 場所 | 要約 | 合図) を読み、棚フォルダの実物・リンクと
双方向に照合する。宣言の無いカタログは対象外 (棚は順次導入する)。
"""

from __future__ import annotations

import re
from pathlib import Path

from audit_common import (HOME_DIR, MEMORY_CHAR_LIMIT,
                        MEMORY_ENTRY_CHAR_LIMIT, Results)

# 本棚を持ち得るカタログ (ホーム直下)。宣言があるものだけ照合する
CATALOG_FILES = ("AGENTS.md", "USER.md", "MEMORY.md", "SOUL.md", "IDENTITY.md", "TOOLS.md",
                 "memory/people/INDEX.md", "memory/groups/INDEX.md")
DECL = re.compile(r"^本棚フォルダ：(.+)$", flags=re.MULTILINE)
ENTRY = re.compile(r"^(本|参照) \| (.+?) \| (.+?) \| (.+?) \| (.+)$", flags=re.MULTILINE)


def _headings(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    return {line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")}


def check_sizes(res: Results) -> None:
    """22. 常時読込ファイルのサイズ (MEMORY.md の総量と項目長)。

    毎回読み込まれる MEMORY.md は、大きくなると全ターンの
    トークンを消費する。総量の上限と、1項目の長さの目安を
    超えたら警告する (詳細は本やプロジェクトファイルへ
    逃がす候補)。AGENTS.md の上限はルール14が別に担う。
    """
    path = HOME_DIR / "MEMORY.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    if len(text) > MEMORY_CHAR_LIMIT:
        res.warn(f"[サイズ] MEMORY.md: 総量が目安 ({MEMORY_CHAR_LIMIT:,}字) を"
                 f"超えています (現在 {len(text):,}字)")
    for entry in text.split("\n- "):
        entry = entry.strip()
        if len(entry) > MEMORY_ENTRY_CHAR_LIMIT:
            label = entry.splitlines()[0][:36] if entry else ""
            res.warn(f"[サイズ] MEMORY.md: 長すぎる項目があります"
                     f" ({len(entry):,}字): {label}…")


def check_shelves(res: Results) -> None:
    primary: dict[str, str] = {}  # 実体パス -> 棚名 (二重登録の検出)
    for name in CATALOG_FILES:
        catalog = HOME_DIR / name
        if not catalog.is_file():
            continue
        try:
            text = catalog.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            res.error(f"[本棚] カタログが読めません: {name}")
            continue
        m = DECL.search(text)
        if not m:
            continue
        shelf_rel = m.group(1).strip()
        shelf_name = Path(shelf_rel).name
        room = HOME_DIR / shelf_rel
        if not room.is_dir():
            res.error(f"[本棚] {shelf_name}: 棚フォルダがありません ({shelf_rel})")
            continue
        entries = ENTRY.findall(text)
        registered: set[str] = set()
        n_books = n_refs = 0
        for kind, _title, loc, _summary, _cue in entries:
            loc = loc.strip()
            path_part, _, anchor = loc.partition("#")
            item = HOME_DIR / path_part
            if not str(path_part).startswith(shelf_rel + "/"):
                res.error(f"[本棚] {shelf_name}: 目次の場所が棚フォルダの外です: {loc}")
                continue
            registered.add(path_part)
            if not item.exists():
                res.error(f"[本棚] {shelf_name}: 目次にあるのに棚に無い／リンク切れです: {loc}")
                continue
            if anchor:
                target = item.resolve() if item.is_symlink() else item
                if anchor.strip() not in _headings(target):
                    res.error(f"[本棚] {shelf_name}: 参照先の節が見つかりません: {loc}")
            if kind == "本":
                n_books += 1
                real = str((item.resolve() if item.is_symlink() else item))
                if real in primary and primary[real] != shelf_name:
                    res.error(f"[本棚] 実体が複数の棚で「本」として登録されています: {real}")
                primary[real] = shelf_name
            else:
                n_refs += 1
        for item in sorted(room.iterdir()):
            if item.is_dir() and not item.is_symlink():
                res.error(f"[本棚] {shelf_name}: 棚フォルダの中にフォルダがあります: {item.name}")
                continue
            rel = f"{shelf_rel}/{item.name}"
            if rel not in registered:
                res.error(f"[本棚] {shelf_name}: 棚にあるのに目次に登録されていません: {item.name}")
        if not any(e.startswith(f"[本棚] {shelf_name}") for e in res.errors):
            res.ok(f"[本棚] {shelf_name}: 目次と棚フォルダが一致 (本{n_books}件・参照{n_refs}件)")
