"""本棚の照合 (カタログの目次と棚フォルダの中身)。

カタログ (AGENTS.md など毎回読まれるファイル) の「本棚フォルダ：」宣言と
目次 (種別 | 題名 | 場所 | 要約 | 合図) を読み、棚フォルダの実物・リンクと
双方向に照合する。宣言の無いカタログは対象外 (棚は順次導入する)。
"""

from __future__ import annotations

import re
from pathlib import Path

from audit_common import (HOME_DIR, ROOT, MEMORY_BYTE_LIMIT,
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


def _save_memory_autocopy(text: str) -> str:
    """サイズ警告時に、その時点の MEMORY.md 全文を自動コピーする。

    保存先は管理プロジェクトの hidden_files。ファイル名に
    内容ハッシュを含め、同一内容は重複して作らない。
    戻り値は、警告文に付す結果の一文。
    """
    import datetime
    import hashlib

    proj = ROOT / "projects" / "ファイル管理システム_監査システム管理"
    if not proj.is_dir():
        return "自動コピーの保存先（管理プロジェクト）が無いため未保存"
    dest_dir = proj / "hidden_files"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    if list(dest_dir.glob(f"自動コピー_MEMORY_*_{digest}.md")):
        return "自動コピーは保存済み（同一内容）"
    name = f"自動コピー_MEMORY_{datetime.date.today():%Y-%m-%d}_{digest}.md"
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / name).write_text(text, encoding="utf-8")
    except OSError:
        return "自動コピーの保存に失敗しました"
    return f"自動コピーを保存しました: {name}"


def check_sizes(res: Results) -> None:
    """22. 常時読込ファイルのサイズ (MEMORY.md の総量と項目長)。

    毎回読み込まれる MEMORY.md は、大きくなると全ターンの
    トークンを消費する。総量の上限と、1項目の長さの目安を
    超えたら警告する (詳細は本やプロジェクトファイルへ
    逃がす候補)。AGENTS.md の上限はルール14が別に担う。
    警告を発した時点で、その時点の全文を自動コピーする
    (圧縮時の内容確認の土台。詳細は監査ルール.md 第4節)。
    """
    path = HOME_DIR / "MEMORY.md"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    messages: list[str] = []
    nbytes = len(text.encode("utf-8"))
    if nbytes > MEMORY_BYTE_LIMIT:
        messages.append(f"[サイズ] MEMORY.md: 総量が目安 ({MEMORY_BYTE_LIMIT:,}バイト) を"
                        f"超えています (現在 {nbytes:,}バイト)")
    for entry in text.split("\n- "):
        entry = entry.strip()
        if len(entry) > MEMORY_ENTRY_CHAR_LIMIT:
            label = entry.splitlines()[0][:36] if entry else ""
            messages.append(f"[サイズ] MEMORY.md: 長すぎる項目があります"
                            f" ({len(entry):,}字): {label}…")
    if messages:
        note = _save_memory_autocopy(text)
        for msg in messages:
            res.warn(f"{msg}（{note}）")


_MGMT_HIDDEN = ("projects", "ファイル管理システム_監査システム管理", "hidden_files")

_ANCHOR_PATTERNS = (
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",  # UUID
    r"goal_[0-9a-f]{8,}",  # ゴールID
    r"(?<![A-Za-z0-9])D\d{1,3}(?!\d)",  # 決定番号 (D123 など)
    r"『[^』]{2,}』",  # 作品名・固有名詞
    r"(?<![\w])[\w\-./]+\.md",  # ファイル名・パス (日本語に接着したものは拾わない)
    r"\d{1,3},\d{3}",  # 桁区切りの数値
    r"v\d+\.\d+(?:\.\d+)?",  # 版番号
    r"\d+(?:\.\d+)?(?:項目|倍|秒|マス|%)",  # 特徴的な数値
)


def _extract_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    for pattern in _ANCHOR_PATTERNS:
        for hit in re.findall(pattern, text):
            hit = hit.strip()
            if len(hit) >= 2:
                anchors.add(hit)
    return anchors


def _is_snapshot_name(name: str) -> bool:
    return name.startswith("自動コピー_MEMORY_") or name.endswith("_MEMORY圧縮前_全文.md")


def _latest_snapshot() -> Path | None:
    folder = ROOT.joinpath(*_MGMT_HIDDEN)
    if not folder.is_dir():
        return None
    cands = [p for p in folder.iterdir() if p.is_file() and _is_snapshot_name(p.name)]
    if not cands:
        return None

    def key(p: Path) -> tuple[str, float]:
        m = re.search(r"\d{4}-\d{2}-\d{2}", p.name)
        return (m.group(0) if m else "", p.stat().st_mtime)

    return max(cands, key=key)


def _discarded_anchors() -> set[str]:
    path = ROOT.joinpath(*_MGMT_HIDDEN) / "メモリ破棄台帳.md"
    out: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if line.startswith("- "):
            token = re.split(r"[：:｜|（]", line[2:].strip(), maxsplit=1)[0].strip()
            if token:
                out.add(token)
    return out


def _corpus_texts() -> list[str]:
    texts: list[str] = []
    bases = [ROOT, HOME_DIR / "memory", HOME_DIR / "本棚"]
    for base in bases:
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix not in (".md", ".txt", ".json", ".py"):
                continue
            if ".git" in p.parts or _is_snapshot_name(p.name) or p.name == "メモリ破棄台帳.md":
                continue
            if base == ROOT and p.parts[len(base.parts)] == "監査コード":
                continue  # 監査コード自身は正の置き場ではない
            try:
                texts.append(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    for p in HOME_DIR.glob("*.md"):
        try:
            texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return texts


def check_anchors(res: Results) -> None:
    """23. 圧縮時の内容確認 (スナップショットからの痕跡の生存)。

    最新のスナップショットにあって現行 MEMORY.md から消えた
    痕跡 (ID・決定番号・数値など) が、正の置き場 (ワークスペース・
    memory・本棚の文書) にも見つからなければ警告する。
    破棄台帳に登録された痕跡は照合から外す。スナップショットが
    無ければ照合しない。詳細は監査ルール.md 第4節。
    """
    snap = _latest_snapshot()
    if snap is None:
        return
    try:
        base_text = snap.read_text(encoding="utf-8", errors="replace")
        current = (HOME_DIR / "MEMORY.md").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    discarded = _discarded_anchors()
    candidates = sorted(
        a for a in _extract_anchors(base_text)
        if a not in current and a not in discarded)
    if not candidates:
        res.ok(f"[痕跡] MEMORY.md: スナップショット ({snap.name}) からの痕跡は"
               "すべて現行メモリか破棄台帳で確認できました")
        return
    corpus = _corpus_texts()
    missing = [a for a in candidates if not any(a in t for t in corpus)]
    if missing:
        shown = ", ".join(missing[:15])
        more = f" ほか{len(missing) - 15}件" if len(missing) > 15 else ""
        res.warn(f"[痕跡] MEMORY.md: スナップショット ({snap.name}) から消えた痕跡が、"
                 f"現行メモリにも正の置き場にも見つかりません: {shown}{more}"
                 f" (全{len(missing)}件)")
    else:
        res.ok(f"[痕跡] MEMORY.md: スナップショット ({snap.name}) からの痕跡は"
               "すべて正の置き場で確認できました")


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
