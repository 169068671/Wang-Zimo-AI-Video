#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_REMOTE = "https://github.com/169068671/Wang-Zimo-AI-Video.git"
DEFAULT_BRANCH = "main"
DEFAULT_VAULT = Path(__file__).resolve().parents[3]
TIMEOUT = 180
UPLOAD_ANCHOR_POLICY_VERSION = 1
UPLOAD_ANCHOR_DIR = Path("attachments/上传锚点")
LOCAL_ANCHOR_DIRS = (
    Path("attachments/人物锚点"),
    Path("attachments/场景锚点"),
    Path("attachments/品牌锚点"),
    Path("attachments/4K锚点组"),
)
UPLOAD_ANCHOR_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_ANCHOR_BYTES = 2 * 1024 * 1024


class SyncError(RuntimeError):
    pass


def run(
    args: list[str],
    *,
    cwd: Path,
    check: bool = True,
    git_command: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if git_command:
        env["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=TIMEOUT,
    )
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise SyncError(detail or f"Command failed: {' '.join(args)}")
    return result


def git(vault: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["git", *args], cwd=vault, check=check, git_command=True)



def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_local_anchor(vault: Path, path: Path) -> Path:
    head = path.read_bytes()[:256]
    if not head.startswith(b"version https://git-lfs.github.com/spec/v1"):
        return path
    match = re.search(rb"oid sha256:([0-9a-f]{64})", head)
    if not match:
        raise SyncError(f"无法解析本地 Git LFS 锚点：{path.relative_to(vault)}")
    oid = match.group(1).decode("ascii")
    obj = vault / ".git" / "lfs" / "objects" / oid[:2] / oid[2:4] / oid
    if not obj.is_file():
        raise SyncError(f"本机缺少 Git LFS 锚点原图：{path.relative_to(vault)}")
    return obj


def prepare_upload_anchor_policy(vault: Path) -> dict[str, int]:
    originals = []
    for rel_dir in LOCAL_ANCHOR_DIRS:
        root = vault / rel_dir
        if root.is_dir():
            originals.extend(
                path for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in UPLOAD_ANCHOR_SUFFIXES
            )
    upload_root = vault / UPLOAD_ANCHOR_DIR
    uploads = [
        path for path in upload_root.rglob("*")
        if path.is_file() and path.suffix.lower() in UPLOAD_ANCHOR_SUFFIXES
    ] if upload_root.is_dir() else []
    if originals and not uploads:
        raise SyncError("检测到本地原始锚点，但缺少 attachments/上传锚点，已停止上传。")
    oversized = [path.relative_to(vault).as_posix() for path in uploads if path.stat().st_size > MAX_UPLOAD_ANCHOR_BYTES]
    if oversized:
        joined = "\n".join(f"- {path}" for path in oversized)
        raise SyncError(f"上传锚点超过 2 MB，已停止上传：\n{joined}")
    manifest = upload_root / "上传锚点清单.json"
    if originals and not manifest.is_file():
        raise SyncError("缺少上传锚点哈希清单，已停止上传。")
    try:
        records = json.loads(manifest.read_text(encoding="utf-8")).get("anchors", []) if manifest.is_file() else []
    except (json.JSONDecodeError, OSError) as exc:
        raise SyncError(f"上传锚点清单不可读，已停止上传：{exc}") from exc
    listed_uploads = set()
    for record in records:
        source = vault / str(record.get("source", ""))
        upload = vault / str(record.get("upload_anchor", ""))
        if not source.is_file() or not upload.is_file():
            raise SyncError(f"上传锚点清单存在缺失文件：{record}")
        listed_uploads.add(upload.resolve())
        if sha256_file(resolve_local_anchor(vault, source)) != record.get("source_sha256"):
            raise SyncError(f"原始锚点已变化，请重新生成上传锚点：{source.relative_to(vault)}")
        if sha256_file(upload) != record.get("upload_sha256"):
            raise SyncError(f"上传锚点哈希不一致，已停止上传：{upload.relative_to(vault)}")
    actual_uploads = {path.resolve() for path in uploads}
    if listed_uploads != actual_uploads:
        raise SyncError("上传锚点目录与哈希清单不一致，已停止上传。")
    for rel_dir in LOCAL_ANCHOR_DIRS:
        git(vault, ["rm", "-r", "--cached", "--ignore-unmatch", "--", rel_dir.as_posix()], check=False)
    return {"originals": len(originals), "uploads": len(uploads)}

def normalize_remote(value: str) -> str:
    remote = value.strip().rstrip("/")
    if remote.endswith(".git"):
        remote = remote[:-4]
    match = re.fullmatch(r"git@([^:]+):(.+)", remote)
    if match:
        return f"{match.group(1).lower()}/{match.group(2).lower()}"
    remote = re.sub(r"^https?://", "", remote, flags=re.I)
    return remote.lower()


def is_git_repo(vault: Path) -> bool:
    result = git(vault, ["rev-parse", "--is-inside-work-tree"], check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def validate_vault(vault: Path) -> dict[str, object] | None:
    validator = vault / "99_System" / "validate_vault.py"
    if not validator.is_file():
        return None
    result = run([sys.executable, str(validator)], cwd=vault, check=False)
    if result.returncode != 0:
        detail = (result.stdout or result.stderr).strip()
        raise SyncError(f"知识库核验未通过，已停止上传。\n{detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"status": "PASS", "raw": result.stdout.strip()}


def initialize_repo(vault: Path, branch: str) -> bool:
    if is_git_repo(vault):
        return False
    result = git(vault, ["init", "-b", branch], check=False)
    if result.returncode != 0:
        git(vault, ["init"])
        git(vault, ["branch", "-M", branch])
    return True


def ensure_branch(vault: Path, branch: str) -> None:
    result = git(vault, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False)
    current = result.stdout.strip()
    if result.returncode != 0 or not current:
        raise SyncError("当前 Git 处于 detached HEAD，为避免破坏历史已停止上传。")
    if current != branch:
        raise SyncError(f"当前分支是 {current}，配置分支是 {branch}，已停止上传。")


def ensure_remote(vault: Path, remote_name: str, remote_url: str) -> bool:
    result = git(vault, ["remote", "get-url", remote_name], check=False)
    if result.returncode != 0:
        git(vault, ["remote", "add", remote_name, remote_url])
        return True
    existing = result.stdout.strip()
    if normalize_remote(existing) != normalize_remote(remote_url):
        raise SyncError(
            f"已有远程 {remote_name} 指向 {existing}，与配置的 {remote_url} 不一致。"
        )
    return False


def ensure_identity(vault: Path) -> bool:
    name = git(vault, ["config", "--get", "user.name"], check=False).stdout.strip()
    email = git(vault, ["config", "--get", "user.email"], check=False).stdout.strip()
    changed = False
    if not name:
        git(vault, ["config", "user.name", "Obsidian GitHub Sync"])
        changed = True
    if not email:
        git(vault, ["config", "user.email", "obsidian-sync@local"])
        changed = True
    return changed


def scan_sensitive_paths(vault: Path) -> list[str]:
    result = git(vault, ["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    paths = [item for item in result.stdout.split("\0") if item]
    blocked: list[str] = []
    exact = {
        "id_rsa",
        "id_ed25519",
        "credentials.json",
        "secrets.json",
        "secrets.yaml",
        "secrets.yml",
    }
    suffixes = {".pem", ".p12", ".pfx", ".key"}
    for item in paths:
        name = Path(item).name.lower()
        if name == ".env" or name.startswith(".env.") or name in exact or Path(name).suffix in suffixes:
            blocked.append(item)
    return blocked


def has_head(vault: Path) -> bool:
    return git(vault, ["rev-parse", "--verify", "HEAD"], check=False).returncode == 0


def remote_branch_exists(vault: Path, remote_name: str, branch: str) -> bool:
    result = git(
        vault,
        ["ls-remote", "--heads", remote_name, f"refs/heads/{branch}"],
        check=False,
    )
    if result.returncode != 0:
        raise SyncError((result.stderr or result.stdout).strip() or "无法读取远程仓库。")
    return bool(result.stdout.strip())


def rebase_remote(vault: Path, remote_name: str, branch: str) -> None:
    git(vault, ["fetch", remote_name, branch])
    if git(vault, ["merge-base", "HEAD", "FETCH_HEAD"], check=False).returncode != 0:
        raise SyncError("本地与远程历史不相关，已停止上传，不会强制覆盖远程。")
    result = git(vault, ["rebase", "FETCH_HEAD"], check=False)
    if result.returncode != 0:
        git(vault, ["rebase", "--abort"], check=False)
        detail = (result.stderr or result.stdout).strip()
        raise SyncError(f"拉取远程时发生冲突，已自动取消 rebase。\n{detail}")


def friendly_error(message: str) -> str:
    lower = message.lower()
    auth_markers = ("authentication failed", "could not read username", "permission denied", "403")
    if any(marker in lower for marker in auth_markers):
        return (
            "GitHub 认证失败。请先在终端执行：\n"
            "gh auth login -h github.com\n"
            "gh auth setup-git\n"
            "认证成功后再点击同步。"
        )
    if "could not resolve host" in lower or "failed to connect" in lower:
        return "无法连接 GitHub，请检查网络后重试。"
    return message


def status(vault: Path, remote_name: str) -> dict[str, object]:
    if not is_git_repo(vault):
        return {
            "ok": True,
            "initialized": False,
            "vault": str(vault),
            "message": "尚未初始化 Git，首次同步时会自动初始化。",
        }
    branch = git(vault, ["symbolic-ref", "--quiet", "--short", "HEAD"], check=False).stdout.strip()
    remote = git(vault, ["remote", "get-url", remote_name], check=False).stdout.strip()
    changes = [line for line in git(vault, ["status", "--porcelain"]).stdout.splitlines() if line]
    commit = git(vault, ["rev-parse", "--short", "HEAD"], check=False).stdout.strip()
    return {
        "ok": True,
        "initialized": True,
        "vault": str(vault),
        "branch": branch,
        "remote": remote,
        "changes": len(changes),
        "commit": commit or None,
        "message": f"当前有 {len(changes)} 项未同步变更。",
    }


def sync(
    vault: Path,
    remote_url: str,
    remote_name: str,
    branch: str,
    commit_message: str | None,
    run_validation: bool,
) -> dict[str, object]:
    if not vault.is_dir():
        raise SyncError(f"知识库目录不存在：{vault}")

    validation = validate_vault(vault) if run_validation else None
    initialized = initialize_repo(vault, branch)
    ensure_branch(vault, branch)
    remote_added = ensure_remote(vault, remote_name, remote_url)
    identity_added = ensure_identity(vault)

    blocked = scan_sensitive_paths(vault)
    if blocked:
        joined = "\n".join(f"- {path}" for path in blocked)
        raise SyncError(f"发现可能包含密钥或凭据的文件，已停止上传：\n{joined}")

    anchor_policy = prepare_upload_anchor_policy(vault)

    git(vault, ["add", "-A"])
    changes = git(vault, ["status", "--porcelain"]).stdout.strip()
    committed = False
    if changes:
        message = commit_message or f"vault sync: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        git(vault, ["commit", "-m", message])
        committed = True

    if not has_head(vault):
        raise SyncError("没有可推送的提交，已停止上传。")

    remote_exists = remote_branch_exists(vault, remote_name, branch)
    if remote_exists:
        rebase_remote(vault, remote_name, branch)

    git(vault, ["push", "--set-upstream", remote_name, branch])
    commit = git(vault, ["rev-parse", "--short", "HEAD"]).stdout.strip()
    return {
        "ok": True,
        "pushed": True,
        "initialized": initialized,
        "remote_added": remote_added,
        "identity_added": identity_added,
        "remote_branch_existed": remote_exists,
        "committed": committed,
        "branch": branch,
        "commit": commit,
        "remote": remote_url,
        "validation": validation,
        "anchor_policy": anchor_policy,
        "message": f"已同步到 GitHub：{branch} @ {commit}",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely sync an Obsidian vault to GitHub.")
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--remote-url", default=DEFAULT_REMOTE)
    parser.add_argument("--remote-name", default="origin")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--commit-message")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    vault = args.vault.expanduser().resolve()
    try:
        if args.status:
            result = status(vault, args.remote_name)
        else:
            result = sync(
                vault,
                args.remote_url,
                args.remote_name,
                args.branch,
                args.commit_message,
                args.validate,
            )
        print(json.dumps(result, ensure_ascii=False) if args.json else result["message"])
        return 0
    except (SyncError, subprocess.TimeoutExpired) as exc:
        message = friendly_error(str(exc))
        payload = {"ok": False, "pushed": False, "message": message}
        print(json.dumps(payload, ensure_ascii=False) if args.json else message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
