#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG_INDEX = ROOT / "00_HOME" / "标签索引.md"
CONTENT_INDEX = ROOT / "00_HOME" / "内容索引.md"
CORE_DIRS = {"01_人物资产", "02_创作工作流", "03_模型与工具", "04_项目", "05_审核", "06_模板", "07_任务记录"}
EXCLUDED_ROOTS = {"08_原始项目副本", "attachments", "plugins", ".obsidian", ROOT.name}

def frontmatter(text: str) -> str | None:
    match = re.match(r"^---\n(.*?)\n---(?:\n|$)", text, re.S)
    return match.group(1) if match else None

def field(block: str, name: str) -> str | None:
    match = re.search(rf"^{re.escape(name)}:\s*(.*?)\s*$", block, re.M)
    return match.group(1).strip("\"'") if match else None

def tags(block: str) -> list[str]:
    match = re.search(r"^tags:\s*\n((?:\s+-\s+.*\n?)*)", block, re.M)
    return [item.strip() for item in re.findall(r"^\s+-\s+(.+)$", match.group(1), re.M)] if match else []

def resolve_wikilink(source: Path, raw: str, markdown_files: list[Path]) -> Path | None:
    target = raw.replace("\\|", "|").split("|", 1)[0].split("#", 1)[0].strip()
    if not target:
        return source
    suffix = Path(target).suffix.lower()
    if suffix and suffix != ".md":
        candidate = (source.parent / target).resolve()
        return candidate if candidate.is_file() else None
    target = target.removesuffix(".md")
    if "/" in target:
        candidate = (source.parent / f"{target}.md").resolve()
        return candidate if candidate.is_file() else None
    candidates = [path for path in markdown_files if path.stem == target]
    if len(candidates) == 1:
        return candidates[0]
    same_dir = source.parent / f"{target}.md"
    return same_dir if same_dir.is_file() else None

def main() -> int:
    errors: list[str] = []
    markdown_files = sorted(path for path in ROOT.rglob("*.md") if path.relative_to(ROOT).parts[0] not in EXCLUDED_ROOTS)
    tag_index_text = TAG_INDEX.read_text(encoding="utf-8") if TAG_INDEX.is_file() else ""
    content_index_text = CONTENT_INDEX.read_text(encoding="utf-8") if CONTENT_INDEX.is_file() else ""
    if not tag_index_text: errors.append("缺少标签索引")
    if not content_index_text: errors.append("缺少内容索引")
    used_tags: set[str] = set()
    for path in markdown_files:
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        block = frontmatter(text)
        if block is None:
            errors.append(f"{rel}: 缺少 YAML frontmatter")
            continue
        if not field(block, "title"): errors.append(f"{rel}: 缺少 title")
        note_tags = tags(block)
        if not note_tags: errors.append(f"{rel}: 缺少 tags")
        used_tags.update(note_tags)
        for raw_link in re.findall(r"!?\[\[([^\]]+)\]\]", text):
            if resolve_wikilink(path, raw_link, markdown_files) is None: errors.append(f"{rel}: 断链 [[{raw_link}]]")
        if rel.parts and rel.parts[0] in CORE_DIRS and path.stem not in content_index_text: errors.append(f"{rel}: 未登记到内容索引")
        if re.search(r"\b(?:sk|key)-[A-Za-z0-9_.-]{20,}\b", text): errors.append(f"{rel}: 疑似包含明文 API 密钥")
    for tag in sorted(used_tags):
        if f"#{tag}" not in tag_index_text and f"`{tag}`" not in tag_index_text: errors.append(f"标签 #{tag} 未登记到标签索引")
    for config in sorted((ROOT / ".obsidian").glob("*.json")):
        try: json.loads(config.read_text(encoding="utf-8"))
        except Exception as exc: errors.append(f"{config.relative_to(ROOT)}: JSON 无效 ({exc})")
    result = {"status": "PASS" if not errors else "FAIL", "markdown_files": len(markdown_files), "used_tags": sorted(used_tags), "errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1

if __name__ == "__main__":
    raise SystemExit(main())
