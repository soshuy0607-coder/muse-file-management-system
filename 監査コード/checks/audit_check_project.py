"""プロジェクト単体のチェック (命名・構成・チャット名・ファイル名・GitHub登録・リリース件数・配布物の整合・想定外の存在)。"""
from __future__ import annotations

import json
import zipfile

from audit_common import *  # noqa: F401,F403
from audit_common import Results


def check_project(res: Results, project: Path) -> None:
    name = project.name

    # 3. フォルダ名形式「プロジェクト名_テーマ」
    parts = name.split("_", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        res.error(f"[命名] {name}: 「プロジェクト名_テーマ」形式になっていません")
    else:
        res.ok(f"[命名] {name}")

    # 4. 必須構成
    for d in REQUIRED_DIRS:
        if not (project / d).is_dir():
            res.error(f"[構成] {name}: {d}/ がありません")
    index = project / "INDEX.md"
    if not index.is_file():
        res.error(f"[構成] {name}: INDEX.md がありません")
        return

    # 5. 直下のファイルは INDEX.md / chat.json だけ
    for entry in sorted(project.iterdir()):
        if entry.is_file() and entry.name not in ALLOWED_PROJECT_FILES:
            res.error(f"[直置き] {name}: 直下に許可されていないファイルがあります: {entry.name}")

    # 4b. 直下の想定外フォルダ
    for entry in sorted(project.iterdir()):
        if entry.is_dir() and not entry.is_symlink() and entry.name not in ALLOWED_PROJECT_DIRS:
            res.error(f"[構成] {name}: 直下に想定外のフォルダがあります: {entry.name}")

    # 6. INDEX の記載
    text = read_text_report(res, index, name)
    if text is None:
        return
    for label in ("プロジェクト名：", "サイドチャット名：", "チャットID："):
        if label not in text:
            res.error(f"[INDEX] {name}: 「{label}」の記載がありません")

    # 7. チャット名 == フォルダ名
    documented_chat = index_field(text, "サイドチャット名")
    if documented_chat is not None:
        if documented_chat != name:
            res.error(
                f"[チャット名] {name}: INDEXのサイドチャット名「{documented_chat}」がフォルダ名と一致しません"
            )
        else:
            res.ok(f"[チャット名] {name}: INDEX記載がフォルダ名と一致")

    chat_file = project / "chat.json"
    if not chat_file.is_file():
        res.error(f"[構成] {name}: chat.json がありません")
    else:
        try:
            data = json.loads(chat_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            res.error(f"[チャット名] {name}: chat.json が読めません (JSON形式を確認してください)")
            data = None
        if isinstance(data, dict):
            actual = data.get("chat_name")
            if actual != name:
                res.error(
                    f"[チャット名] {name}: 実際のチャット名「{actual}」がフォルダ名と一致しません"
                )
            else:
                res.ok(f"[チャット名] {name}: 実際のチャット名がフォルダ名と一致")
            chat_id_index = index_field(text, "チャットID")
            if chat_id_index and data.get("chat_id") != chat_id_index:
                res.error(f"[チャット名] {name}: chat.json の chat_id が INDEX と一致しません")

    check_github(res, project)
    check_distribution(res, project)

    # 18. プロジェクト内のシンボリックリンク (想定外の存在)
    for path in sorted(project.rglob("*")):
        if path.is_symlink():
            res.error(f"[想定外] {name}: シンボリックリンクがあります: {path.relative_to(project)}")

    # 8. 曖昧なファイル名 (警告)
    for path in project.rglob("*"):
        if path.is_file() and path.name not in ALLOWED_PROJECT_FILES:
            if any(p.search(path.name) for p in BAD_NAME_PATTERNS):
                res.warn(f"[ファイル名] {name}: 曖昧な名前です: {path.relative_to(project)}")


def check_github(res: Results, project: Path) -> None:
    """16. GitHub登録 (任意フォルダ github/ がある場合のみ照合する)。

    登録は GitHub 実態のスナップショットであり、監査は実在確認をしない
    (chat.json と同じ考え方)。書式と相互の一致だけを確認する。
    """
    name = project.name
    gh = project / GITHUB_DIR_NAME
    if not gh.is_dir():
        return  # 任意フォルダ: 無いプロジェクトは対象外
    errors_before = len(res.errors)
    for entry in sorted(gh.iterdir()):
        if entry.is_dir() or entry.name != GITHUB_REPO_FILE:
            res.error(f"[GitHub] {name}: github/ には REPO.md だけを置きます: {entry.name}")
    repo_md = gh / GITHUB_REPO_FILE
    if not repo_md.is_file():
        res.error(f"[GitHub] {name}: github/REPO.md がありません")
        return
    text = read_text_report(res, repo_md, name)
    if text is None:
        return
    repo = index_field(text, "リポジトリ")
    url = index_field(text, "URL")
    branch = index_field(text, "既定ブランチ")
    visibility = index_field(text, "公開範囲")
    for label, value in (("リポジトリ", repo), ("URL", url), ("既定ブランチ", branch), ("公開範囲", visibility)):
        if value is None:
            res.error(f"[GitHub] {name}: REPO.md に「{label}：」の記載がありません")
    if repo is not None and not re.match(r"^[\w.-]+/[\w.-]+$", repo):
        res.error(f"[GitHub] {name}: リポジトリ「{repo}」が owner/name 形式になっていません")
        repo = None
    if repo is not None and url is not None and url != f"https://github.com/{repo}":
        res.error(f"[GitHub] {name}: URL「{url}」がリポジトリ「{repo}」と一致しません")
    if visibility is not None and visibility not in GITHUB_VISIBILITIES:
        res.error(f"[GitHub] {name}: 公開範囲「{visibility}」は public / private のいずれかにしてください")
    source = index_field(text, "同期元")
    if source is not None and not (project / source).exists():
        res.error(f"[GitHub] {name}: 同期元「{source}」がプロジェクト内に存在しません")
    history = index_field(text, "履歴")
    if history is None:
        res.error(f"[GitHub] {name}: REPO.md に「履歴：」の記載がありません")
    else:
        history_path = project / history
        if not history_path.is_dir():
            res.error(f"[GitHub] {name}: 履歴「{history}」の場所が存在しません")
        elif not (history_path / ".git").exists():
            res.error(f"[GitHub] {name}: 履歴「{history}」は Git リポジトリではありません (.git がありません)")
    if repo is not None and len(res.errors) == errors_before:
        res.ok(f"[GitHub] {name}: 登録あり ({repo})")
    check_release_pending(res, project)


def check_release_pending(res: Results, project: Path) -> None:
    """17. 未配布の改良の件数 (上限を超えたら警告)。

    件数は hidden_files/リリース予定.md の項目行 (「- 」で始まる行) の数。
    記録ファイルが無い場合は 0 件として扱う。
    """
    name = project.name
    pending_file = project / "hidden_files" / RELEASE_PENDING_FILE
    count = 0
    if pending_file.is_file():
        text = read_text_report(res, pending_file, name)
        if text is None:
            return
        count = sum(1 for line in text.splitlines() if re.match(r"^-\s+\S", line))
    if count > RELEASE_PENDING_MAX:
        res.warn(
            f"[リリース] {name}: 未配布の改良が {count} 件溜まっています"
            f" (上限 {RELEASE_PENDING_MAX})。GitHubへリリースする時期です"
        )
    else:
        res.ok(f"[リリース] {name}: 未配布の改良 {count} 件 (上限 {RELEASE_PENDING_MAX})")


def check_distribution(res: Results, project: Path) -> None:
    """19. 配布物の整合 (files/ 内の「配布版_vX.Y.Z」フォルダが対象)。

    VERSION と変更履歴は、片方でもあれば両方そろって版と一致すること
    (どちらも無い旧版は仕組み導入前として対象外)。同版の ZIP があれば、
    中身のファイル集合がフォルダと一致すること。
    """
    name = project.name
    files_dir = project / "files"
    if not files_dir.is_dir():
        return
    for folder in sorted(files_dir.iterdir()):
        m = re.match(r"^配布版_v(\d+(?:\.\d+)+)$", folder.name)
        if not folder.is_dir() or not m:
            continue
        ver = m.group(1)
        version_file = folder / "VERSION"
        changelog = folder / "CHANGELOG.md"
        if version_file.is_file() or changelog.is_file():
            if not version_file.is_file():
                res.error(f"[配布] {name}: {folder.name} に VERSION がありません")
            elif version_file.read_text(encoding="utf-8", errors="replace").strip() != ver:
                res.error(f"[配布] {name}: {folder.name} の VERSION の中身がフォルダ名の版と一致しません")
            if not changelog.is_file():
                res.error(f"[配布] {name}: {folder.name} に CHANGELOG.md がありません")
            else:
                cl_text = changelog.read_text(encoding="utf-8", errors="replace")
                if not re.search(rf"^## .*\[?{re.escape(ver)}\]?", cl_text, flags=re.MULTILINE):
                    res.error(f"[配布] {name}: {folder.name} の変更履歴に {ver} の節がありません")
        for zpath in sorted(files_dir.glob("*.zip")):
            if not zpath.stem.endswith(f"_v{ver}"):
                continue
            try:
                with zipfile.ZipFile(zpath) as z:
                    zip_files = {n for n in z.namelist() if not n.endswith("/")}
            except zipfile.BadZipFile:
                res.error(f"[配布] {name}: ZIP が読めません: {zpath.name}")
                continue
            folder_files = {
                f"{folder.name}/{f.relative_to(folder).as_posix()}"
                for f in folder.rglob("*") if f.is_file()
            }
            if zip_files != folder_files:
                only_zip = sorted(zip_files - folder_files)
                only_folder = sorted(folder_files - zip_files)
                res.error(
                    f"[配布] {name}: {zpath.name} の中身が {folder.name} と一致しません"
                    f" (ZIPにのみ: {only_zip}; フォルダにのみ: {only_folder})")
            else:
                res.ok(f"[配布] {name}: {folder.name} と ZIP の中身が一致")
