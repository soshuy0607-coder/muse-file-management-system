#!/usr/bin/env python3
"""監査コードのテスト実行係。

使い方:
    python3 ~/workspace/監査コード/tests/test_audit.py

変化のないケースは自動で省略する (監査の増分方式と同じ考え方)。
省略の判断はこの実行係自身が行い、使う側が指定する手段はない。
- ケースの指紋 = ケース定義の文面 + 監査コード全体の内容 + テスト基盤。
  指紋が前回と一致するケースは再実行しない。
- 前回失敗したケースも、変化がなければ再実行せず、失敗を引き継いで
  報告する (直す側が変われば指紋が変わり、必ず再実行される)。
- 状態が無い・壊れている場合と、テスト基盤が変わった場合、一定間隔
  (7日 / 20回) では全件実行する。
- 失敗したケースの検証環境は /tmp に残し、場所を表示する。
終了コード: 失敗 (引き継ぎを含む) があれば 1。標準ライブラリのみ。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "checks"))

from test_cases import CASES, Ctx  # noqa: E402

CODE_ROOT = Path(__file__).resolve().parents[1]  # 監査コード/
STATE_FILE = CODE_ROOT / ".test-state.json"
STATE_VERSION = 1
FULL_INTERVAL_DAYS = 7
FULL_INTERVAL_RUNS = 20
PART_FILES = {
    "common": CODE_ROOT / "checks" / "audit_common.py",
    "check_project": CODE_ROOT / "checks" / "audit_check_project.py",
    "cross": CODE_ROOT / "checks" / "audit_cross.py",
    "shelf": CODE_ROOT / "checks" / "audit_shelf.py",
    "state": CODE_ROOT / "checks" / "audit_state.py",
    "refs": CODE_ROOT / "checks" / "audit_refs.py",
    "fresh": CODE_ROOT / "checks" / "audit_fresh.py",
    "entry": CODE_ROOT / "audit_file_storage.py",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def base_fingerprint() -> str:
    """テスト基盤 (実行係とケース集の土台部分) の指紋。"""
    h = hashlib.sha256()
    for path in (Path(__file__), CODE_ROOT / "tests" / "test_cases.py"):
        h.update(path.read_bytes())
    return h.hexdigest()


def case_fingerprint(fn, targets: list[str]) -> str:
    # 指紋は「ケース定義 + 監査コード全体」。部品単位に絞らない:
    # 監査はプログラム全体が動くため、対象外の部品の不具合 (例:
    # 一覧照合側の例外) がケース結果を左右する干渉を取りこぼさない
    # ため (実際に起きた)。targets は「主に見る部品」の目印として残す。
    h = hashlib.sha256()
    h.update(inspect.getsource(fn).encode("utf-8"))
    for part in sorted(PART_FILES):
        h.update(part.encode("utf-8"))
        h.update(PART_FILES[part].read_bytes())
    return h.hexdigest()


def load_state() -> dict | None:
    for stale in CODE_ROOT.glob(".test-state.json.*.tmp"):
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
    if not isinstance(data.get("cases"), dict):
        return None
    return data


def save_state(state: dict) -> bool:
    tmp = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, STATE_FILE)
    except OSError:
        return False
    return True


def full_reason(state: dict | None, base_fp: str, now: datetime) -> str | None:
    if state is None:
        return "状態が無いか壊れているため"
    if state.get("base_fingerprint") != base_fp:
        return "テスト基盤が変わったため"
    try:
        last_full = datetime.fromisoformat(state["last_full_at"])
        elapsed = (now - last_full).days
    except (KeyError, ValueError, TypeError):
        return "状態の日時が読めないため"
    if elapsed >= FULL_INTERVAL_DAYS:
        return f"前回の全件テストから {elapsed} 日経過したため"
    if int(state.get("runs_since_full", 0)) >= FULL_INTERVAL_RUNS:
        return "全件テストからの実行回数が上限に達したため"
    return None


def main() -> int:
    now = datetime.now().astimezone()
    base_fp = base_fingerprint()
    state = load_state()
    reason = full_reason(state, base_fp, now)
    full = reason is not None
    prev_cases: dict = state["cases"] if state else {}
    new_cases: dict[str, dict] = {}
    lines: list[str] = []
    if full:
        lines.append(f"[全件] 全件テストを実施しました ({reason})")
    ran = skipped = passed = 0
    failures: list[str] = []

    for name, (fn, targets) in CASES.items():
        fp = case_fingerprint(fn, targets)
        prev = prev_cases.get(name)
        if not full and prev and prev.get("fingerprint") == fp:
            skipped += 1
            if prev.get("status") == "passed":
                lines.append(f"SKIP  {name} (変化なし)")
                new_cases[name] = prev
            else:
                problems = prev.get("problems", ["(内容不明)"])
                lines.append(f"FAIL  {name} (前回失敗・変化なしのため再実行を省略): {problems[0]}")
                failures.append(name)
                new_cases[name] = prev
            continue
        ran += 1
        root = Path(tempfile.mkdtemp(prefix=f"audit-test-{name}-"))
        try:
            problems = fn(Ctx(root))
        except Exception as exc:  # ケース自体の異常も失敗として報告する
            problems = [f"ケースが例外で終了しました: {exc!r}"]
        if problems:
            lines.append(f"FAIL  {name}: {problems[0]}")
            for extra in problems[1:]:
                lines.append(f"      - {extra}")
            lines.append(f"      検証環境を残しました: {root}")
            failures.append(name)
            new_cases[name] = {"fingerprint": fp, "status": "failed", "problems": problems,
                               "checked_at": now.strftime("%Y-%m-%d %H:%M")}
        else:
            passed += 1
            lines.append(f"OK    {name}")
            new_cases[name] = {"fingerprint": fp, "status": "passed", "problems": [],
                               "checked_at": now.strftime("%Y-%m-%d %H:%M")}
            shutil.rmtree(root, ignore_errors=True)

    new_state = {
        "version": STATE_VERSION,
        "base_fingerprint": base_fp,
        "last_full_at": (now.isoformat(timespec="seconds") if full else state["last_full_at"]),
        "runs_since_full": (0 if full else int(state.get("runs_since_full", 0)) + 1),
        "cases": new_cases,
    }
    saved = save_state(new_state)
    print("=== 監査コード テスト結果 ===")
    for line in lines:
        print(line)
    total_failed = len(failures)
    # 合格数は「今回合格 + 省略された前回合格」で数える
    carried_pass = sum(1 for n, c in new_cases.items()
                       if c.get("status") == "passed") - passed
    print(f"--- 実行 {ran} / 省略 {skipped} / 合格 {passed + carried_pass} / 失敗 {total_failed}")
    if not saved:
        print("WARN  テスト状態を保存できませんでした (次回は全件テストになります)")
    print("判定:", "不合格" if failures else "合格")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
