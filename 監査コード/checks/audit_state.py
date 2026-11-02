"""増分監査の状態管理 (前回結果の記録、指紋の計算、全件に倒す判断)。

省略するかどうかはコード自身が実行時に判断する。使う側が指定する
手段は無い。状態が無い・壊れている場合は必ず全件監査に倒す。
設計の正は 監査ルール.md 第2節「増分監査」。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from audit_common import AUDIT_DIR

STATE_FILE = AUDIT_DIR / ".audit-state.json"
STATE_VERSION = 1
FULL_AUDIT_INTERVAL_DAYS = 7
FULL_AUDIT_INTERVAL_RUNS = 20
# 中身まで指紋に入れる台帳 (プロジェクト直下からの相対パス)
LEDGER_FILES = {"INDEX.md", "chat.json", "github/REPO.md", "hidden_files/リリース予定.md"}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fresh_base(project: Path) -> dict:
    """鮮度チェック (ルール21) の比較材料。

    プロジェクト直下の顔ぶれ (第1階層の名前の集合) と INDEX.md の
    内容ハッシュ。状態ファイルに一緒に保存し、次回と比較する。
    """
    top = set()
    for dirpath, dirnames, filenames in os.walk(project):
        base = Path(dirpath)
        for name in list(dirnames) + list(filenames):
            rel = (base / name).relative_to(project).as_posix()
            top.add(rel.split("/")[0])
    index = project / "INDEX.md"
    index_hash = _sha256(index.read_bytes()) if index.is_file() else None
    return {"top": sorted(top), "index": index_hash}


def project_fingerprint(project: Path) -> str:
    """プロジェクトの指紋 (全ファイルのパス・サイズ・更新時刻＋台帳は内容)。

    フォルダ自体も記録する (空の想定外フォルダの追加を変化として拾うため)。
    シンボリックリンクはリンク先文字列で記録する。
    """
    entries: list[str] = []
    for dirpath, dirnames, filenames in os.walk(project):
        dirnames.sort()
        base = Path(dirpath)
        for d in dirnames:
            rel = (base / d).relative_to(project).as_posix()
            entries.append(f"D\t{rel}")
        for f in sorted(filenames):
            path = base / f
            rel = path.relative_to(project).as_posix()
            if path.is_symlink():
                entries.append(f"L\t{rel}\t{os.readlink(path)}")
                continue
            st = path.stat()
            line = f"F\t{rel}\t{st.st_size}\t{st.st_mtime_ns}"
            if rel in LEDGER_FILES:
                line += f"\t{_sha256(path.read_bytes())}"
            entries.append(line)
    entries.sort()
    return _sha256("\n".join(entries).encode("utf-8"))


def audit_code_fingerprint() -> str:
    """監査コード自身 (入口＋checks/ の部品) の内容の指紋。"""
    targets = [AUDIT_DIR / "audit_file_storage.py"] + sorted((AUDIT_DIR / "checks").glob("*.py"))
    h = hashlib.sha256()
    for path in targets:
        h.update(path.name.encode("utf-8"))
        h.update(path.read_bytes())
    return h.hexdigest()


def load_state() -> dict | None:
    """前回の状態を読む。無い・壊れている・版が違う場合は None (全件に倒す)。"""
    for stale in AUDIT_DIR.glob(".audit-state.json.*.tmp"):
        try:
            stale.unlink()
        except OSError:
            pass
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return None
    if not isinstance(data.get("projects"), dict):
        return None
    return data


def save_state(state: dict) -> bool:
    """状態を原子的に保存する (仮ファイルに書いてから差し替える)。"""
    tmp = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except OSError:
        return False
    return True


def full_audit_reason(state: dict | None, code_fp: str, now: datetime) -> str | None:
    """全件監査に倒すべきなら、その理由を返す。倒さない場合は None。"""
    if state is None:
        return "状態が無いか壊れているため"
    if state.get("audit_code_fingerprint") != code_fp:
        return "監査コードが変わったため"
    try:
        last_full = datetime.fromisoformat(state["last_full_audit_at"])
        elapsed_days = (now - last_full).days
    except (KeyError, ValueError, TypeError):
        return "状態の日時が読めないため"
    if elapsed_days >= FULL_AUDIT_INTERVAL_DAYS:
        return f"前回の全件監査から {elapsed_days} 日経過したため"
    if int(state.get("runs_since_full", 0)) >= FULL_AUDIT_INTERVAL_RUNS:
        return "全件監査からの実行回数が上限に達したため"
    return None
