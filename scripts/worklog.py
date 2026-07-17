#!/usr/bin/env python3
"""Append-only development work-record manager for the track-dev-work skill."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator
from uuid import uuid4


STATUSES = ("进行中", "受阻", "待验证", "已完成")
ACTIVE_STATUSES = set(STATUSES) - {"已完成"}
MILESTONE_TYPES = ("关键判断", "根因与方向", "解决方案", "关键结果", "用户要求")
MAX_AUTOMATIC_MILESTONES = 3
REQUIRED_EVENT_FIELDS = (
    "- 里程碑：",
    "- 重要过程：",
    "- 结果与证据：",
    "- 亮点与价值：",
    "- 风险与下一步：",
)
REQUIRED_FINAL_SECTIONS = (
    "### 开发/工作目标",
    "### 工作流程复原",
    "### 遇到的问题",
    "### 中间分析与方向",
    "### 解决方法",
    "### 最终结果与验证",
    "### 整体亮点",
    "### 简历价值评分",
    "### 建议写进简历的部分",
)
PLACEHOLDER_VERIFICATION = {"", "无", "暂无", "待补充", "未验证", "todo", "todo：补充可验证指标"}
REQUIRED_SCORE_LABELS = ("技术难度", "内容丰富度", "证据真实度", "技术精彩度", "简历价值", "综合评分")
INDEX_NAME = ".record-index.jsonl"
LOCK_NAME = ".worklog.lock"
EXCLUDE_PATTERN = "/work-records/"


class WorklogError(RuntimeError):
    pass


def now() -> datetime:
    return datetime.now().astimezone()


def display_time(value: datetime | None = None) -> str:
    return (value or now()).strftime("%Y-%m-%d %H:%M:%S %z")


def filename_time(value: datetime | None = None) -> str:
    return (value or now()).strftime("%Y%m%d-%H%M%S")


def run_git(candidate: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def resolve_project_root(raw_root: str) -> tuple[Path, bool]:
    candidate = Path(raw_root).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise WorklogError(f"项目路径不存在或不是目录：{candidate}")
    git_root = run_git(candidate, "rev-parse", "--show-toplevel")
    if git_root:
        return Path(git_root).resolve(), True
    return candidate, False


def ensure_local_git_exclude(project_root: Path) -> bool:
    exclude_raw = run_git(project_root, "rev-parse", "--git-path", "info/exclude")
    if not exclude_raw:
        return False
    exclude_path = Path(exclude_raw)
    if not exclude_path.is_absolute():
        exclude_path = project_root / exclude_path
    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude_path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        content = handle.read()
        existing = {line.strip() for line in content.splitlines()}
        if EXCLUDE_PATTERN in existing:
            return False
        handle.seek(0, os.SEEK_END)
        if content and not content.endswith("\n"):
            handle.write("\n")
        handle.write(EXCLUDE_PATTERN + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return True


def ensure_records_dir(project_root: Path, is_git: bool) -> Path:
    records_dir = project_root / "work-records"
    records_dir.mkdir(parents=True, exist_ok=True)
    try:
        records_dir.chmod(0o700)
    except OSError:
        pass
    if is_git:
        ensure_local_git_exclude(project_root)
    return records_dir


@contextmanager
def project_lock(records_dir: Path) -> Iterator[None]:
    lock_path = records_dir / LOCK_NAME
    with open(lock_path, "a+", encoding="utf-8") as handle:
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_text(path: Path, text: str) -> None:
    if not text.strip():
        raise WorklogError("不能追加空内容。")
    with open(path, "a", encoding="utf-8") as handle:
        handle.write("\n" + text.rstrip() + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def append_index(records_dir: Path, event: dict[str, Any]) -> None:
    index_path = records_dir / INDEX_NAME
    with open(index_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        index_path.chmod(0o600)
    except OSError:
        pass


def load_events(records_dir: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    index_path = records_dir / INDEX_NAME
    if index_path.exists():
        for line_number, line in enumerate(index_path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise WorklogError(f"索引第 {line_number} 行损坏：{exc}") from exc
            events.append(event)
    return events


def load_states(records_dir: Path) -> dict[str, dict[str, Any]]:
    states: dict[str, dict[str, Any]] = {}
    for event in load_events(records_dir):
        record_id = event.get("record_id")
        if record_id:
            states[record_id] = event
    return states


def sanitize_title(title: str) -> str:
    cleaned = re.sub(r"[\\/:\x00-\x1f\x7f]+", "-", title.strip())
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip(" .-_")
    if not cleaned:
        cleaned = "未命名需求"
    return cleaned[:80].rstrip(" .-_") or "未命名需求"


def unique_record_path(records_dir: Path, title: str, created: str, status: str) -> Path:
    candidate = records_dir / f"{title}_{created}_{status}.md"
    counter = 2
    while candidate.exists():
        candidate = records_dir / f"{title}-{counter}_{created}_{status}.md"
        counter += 1
    return candidate


def unique_status_path(current_path: Path, status: str) -> Path:
    matched = re.match(r"^(.*)_([^_]+)\.md$", current_path.name)
    if not matched:
        raise WorklogError(f"记录文件名不符合约定：{current_path.name}")
    prefix = matched.group(1)
    candidate = current_path.with_name(f"{prefix}_{status}.md")
    counter = 2
    while candidate.exists() and candidate != current_path:
        candidate = current_path.with_name(f"{prefix}-{counter}_{status}.md")
        counter += 1
    return candidate


def status_from_path(path: Path) -> str:
    for status in STATUSES:
        if path.name.endswith(f"_{status}.md"):
            return status
    raise WorklogError(f"无法从文件名识别状态：{path.name}")


def find_path_by_record_id(records_dir: Path, record_id: str) -> Path | None:
    needle = f"> 记录 ID：`{record_id}`"
    for path in records_dir.glob("*.md"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                head = "".join(handle.readline() for _ in range(8))
        except OSError:
            continue
        if needle in head:
            return path
    return None


def resolve_record(records_dir: Path, requested_id: str | None) -> tuple[str, dict[str, Any], Path]:
    states = load_states(records_dir)
    if requested_id:
        matches = [record_id for record_id in states if record_id == requested_id or record_id.startswith(requested_id)]
        if len(matches) != 1:
            if not matches:
                raise WorklogError(f"未找到记录 ID：{requested_id}")
            raise WorklogError(f"记录 ID 前缀不唯一：{requested_id}")
        record_id = matches[0]
    else:
        active = [record_id for record_id, state in states.items() if state.get("status") in ACTIVE_STATUSES]
        if len(active) != 1:
            raise WorklogError("未指定记录 ID，且活动记录数量不是 1。请先运行 list --active。")
        record_id = active[0]
    state = states[record_id]
    path = records_dir / state["path"]
    if not path.exists():
        recovered = find_path_by_record_id(records_dir, record_id)
        if recovered is None:
            raise WorklogError(f"索引指向的记录文件不存在：{path}")
        path = recovered
        state = {**state, "path": path.name, "status": status_from_path(path)}
    return record_id, state, path


def read_stdin() -> str:
    if sys.stdin.isatty():
        return ""
    return sys.stdin.read().strip()


def validate_event_body(body: str) -> None:
    missing = [field for field in REQUIRED_EVENT_FIELDS if field not in body]
    if missing:
        raise WorklogError("阶段记录缺少字段：" + "、".join(missing))


def section_content(body: str, heading: str) -> str:
    pattern = re.compile(rf"^{re.escape(heading)}\s*$\n(.*?)(?=^###\s|\Z)", re.MULTILINE | re.DOTALL)
    match = pattern.search(body)
    return match.group(1).strip() if match else ""


def validate_final_body(body: str) -> None:
    missing = [heading for heading in REQUIRED_FINAL_SECTIONS if heading not in body]
    if missing:
        raise WorklogError("最终总结缺少章节：" + "、".join(missing))
    empty = [heading for heading in REQUIRED_FINAL_SECTIONS if not section_content(body, heading)]
    if empty:
        raise WorklogError("最终总结存在空章节：" + "、".join(empty))
    verification = section_content(body, "### 最终结果与验证")
    normalized_verification = re.sub(r"^[\s>*-]+", "", verification).strip().lower()
    if normalized_verification in PLACEHOLDER_VERIFICATION:
        raise WorklogError("最终结果与验证为空或仍是占位内容，不能标记为已完成。")
    score_section = section_content(body, "### 简历价值评分")
    score_pattern = r"(?:10(?:\.0)?|[1-9](?:\.\d)?)\s*/\s*10"
    missing_scores = [
        label
        for label in REQUIRED_SCORE_LABELS
        if not re.search(rf"{re.escape(label)}\s*：\s*{score_pattern}", score_section)
    ]
    if missing_scores:
        raise WorklogError("简历价值评分缺少合法的 1–10 分评分：" + "、".join(missing_scores))
    resume_section = section_content(body, "### 建议写进简历的部分")
    resume_bullets = [line for line in resume_section.splitlines() if re.match(r"^\s*-\s+\S", line)]
    if not 1 <= len(resume_bullets) <= 2:
        raise WorklogError("建议写进简历的部分必须包含 1–2 条 Markdown 列表描述。")


def render_template(values: dict[str, str]) -> str:
    template_path = Path(__file__).resolve().parent.parent / "assets" / "worklog-template.md"
    template = template_path.read_text(encoding="utf-8")
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", value)
    unresolved = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", template)))
    if unresolved:
        raise WorklogError("模板存在未替换字段：" + "、".join(unresolved))
    return template.rstrip() + "\n"


def event_base(record_id: str, title: str, status: str, path: Path, event: str) -> dict[str, Any]:
    return {
        "event": event,
        "record_id": record_id,
        "title": title,
        "status": status,
        "path": path.name,
        "updated_at": display_time(),
    }


def command_start(args: argparse.Namespace) -> dict[str, Any]:
    project_root, is_git = resolve_project_root(args.root)
    records_dir = ensure_records_dir(project_root, is_git)
    created_at = now()
    created_name = filename_time(created_at)
    title = sanitize_title(args.title)
    display_title = " ".join(args.title.split()) or "未命名需求"
    record_id = created_at.strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]
    with project_lock(records_dir):
        path = unique_record_path(records_dir, title, created_name, "进行中")
        content = render_template(
            {
                "TITLE": display_title,
                "RECORD_ID": record_id,
                "CREATED_AT": display_time(created_at),
                "PROJECT_ROOT": str(project_root),
                "GOAL": args.goal.strip() or "待补充",
                "BACKGROUND": args.background.strip() or "待补充",
                "SCOPE": args.scope.strip() or "待补充",
                "SUCCESS": args.success.strip() or "待补充",
                "CONSTRAINTS": args.constraints.strip() or "暂无",
            }
        )
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            path.chmod(0o600)
        except OSError:
            pass
        event = event_base(record_id, display_title, "进行中", path, "start")
        event["created_at"] = display_time(created_at)
        append_index(records_dir, event)
    return {**event, "project_root": str(project_root), "record_path": str(path)}


def command_append(args: argparse.Namespace) -> dict[str, Any]:
    project_root, is_git = resolve_project_root(args.root)
    records_dir = ensure_records_dir(project_root, is_git)
    body = read_stdin()
    validate_event_body(body)
    with project_lock(records_dir):
        record_id, state, path = resolve_record(records_dir, args.id)
        status = status_from_path(path)
        if status == "已完成":
            raise WorklogError("记录已经完成；如需继续工作，请先使用 transition 将其明确重新开启。")
        prior_events = [
            event
            for event in load_events(records_dir)
            if event.get("record_id") == record_id and event.get("event") == "append"
        ]
        automatic_events = [event for event in prior_events if event.get("milestone") != "用户要求"]
        if args.milestone != "用户要求":
            if len(automatic_events) >= MAX_AUTOMATIC_MILESTONES:
                raise WorklogError(
                    "已经达到 3 条自动关键节点上限。请停止自动追加并等待最终总结；"
                    "只有用户明确要求记录时才能使用“用户要求”。"
                )
            if any(event.get("milestone") == args.milestone for event in automatic_events):
                raise WorklogError(
                    f"已经记录过“{args.milestone}”节点。请把同类信息保留到最终总结，"
                    "不要生成重复过程节点。"
                )
        title = " ".join(args.title.split())
        if not title:
            raise WorklogError("里程碑标题不能为空。")
        entry = f"### {display_time()} | {args.milestone}：{title} | {status}\n\n{body}"
        append_text(path, entry)
        event = event_base(record_id, state["title"], status, path, "append")
        event["milestone"] = args.milestone
        event["milestone_title"] = title
        append_index(records_dir, event)
    return {**event, "project_root": str(project_root), "record_path": str(path)}


def command_transition(args: argparse.Namespace) -> dict[str, Any]:
    project_root, is_git = resolve_project_root(args.root)
    records_dir = ensure_records_dir(project_root, is_git)
    note = read_stdin() or "无补充说明。"
    if args.status == "已完成":
        raise WorklogError("不能通过 transition 标记已完成；请使用 finalize 提供完整流程总结与结果验证。")
    with project_lock(records_dir):
        record_id, state, path = resolve_record(records_dir, args.id)
        old_status = status_from_path(path)
        if old_status == args.status:
            return {
                **event_base(record_id, state["title"], old_status, path, "transition-noop"),
                "project_root": str(project_root),
                "record_path": str(path),
                "message": "状态未变化。",
            }
        new_path = unique_status_path(path, args.status)
        os.rename(path, new_path)
        next_step = {
            "进行中": "继续推进需求并记录下一关键阶段。",
            "受阻": "明确解除阻塞所需的输入、权限或外部变化。",
            "待验证": "完成尚未取得的联调、验收或运行验证。",
            "已完成": "记录已完成；后续如有范围变化应明确重新开启。",
        }[args.status]
        entry = (
            f"### {display_time()} | 状态变更 | {args.status}\n\n"
            f"- 里程碑：需求状态从“{old_status}”变更为“{args.status}”。\n"
            f"- 重要过程：根据实际交付条件确认状态发生了实质变化。\n"
            f"- 结果与证据：记录文件已重命名为 `{new_path.name}`。\n"
            f"- 亮点与价值：保持状态、证据和历史记录一致。\n"
            f"- 风险与下一步：{note}；{next_step}"
        )
        append_text(new_path, entry)
        event = event_base(record_id, state["title"], args.status, new_path, "transition")
        event["previous_status"] = old_status
        append_index(records_dir, event)
    return {**event, "project_root": str(project_root), "record_path": str(new_path)}


def command_finalize(args: argparse.Namespace) -> dict[str, Any]:
    project_root, is_git = resolve_project_root(args.root)
    records_dir = ensure_records_dir(project_root, is_git)
    body = read_stdin()
    validate_final_body(body)
    with project_lock(records_dir):
        record_id, state, path = resolve_record(records_dir, args.id)
        old_status = status_from_path(path)
        marker = f"<!-- TRACK-DEV-WORK:FINALIZED:{record_id} -->"
        existing = path.read_text(encoding="utf-8")
        if marker not in existing:
            final_entry = f"## 最终总结\n\n> 完成时间：{display_time()}\n\n{body}\n\n{marker}"
            append_text(path, final_entry)
        final_path = path
        if old_status != "已完成":
            final_path = unique_status_path(path, "已完成")
            os.rename(path, final_path)
        event = event_base(record_id, state["title"], "已完成", final_path, "finalize")
        event["previous_status"] = old_status
        append_index(records_dir, event)
    return {**event, "project_root": str(project_root), "record_path": str(final_path)}


def command_list(args: argparse.Namespace) -> dict[str, Any]:
    project_root, is_git = resolve_project_root(args.root)
    records_dir = ensure_records_dir(project_root, is_git)
    with project_lock(records_dir):
        states = load_states(records_dir)
        records = []
        for record_id, state in states.items():
            path = records_dir / state["path"]
            if not path.exists():
                recovered = find_path_by_record_id(records_dir, record_id)
                if recovered:
                    path = recovered
                    state = {**state, "path": path.name, "status": status_from_path(path)}
            if args.active and state.get("status") not in ACTIVE_STATUSES:
                continue
            records.append({**state, "record_path": str(path)})
        records.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return {"project_root": str(project_root), "records": records}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="管理追加式研发过程记录。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="创建一份新需求记录。")
    start.add_argument("--root", default=os.getcwd(), help="项目目录；Git 项目会解析到仓库根目录。")
    start.add_argument("--title", required=True, help="需求或开发标题。")
    start.add_argument("--goal", required=True, help="开发目标。")
    start.add_argument("--background", default="待补充", help="需求背景。")
    start.add_argument("--scope", default="待补充", help="工作范围。")
    start.add_argument("--success", default="待补充", help="成功标准。")
    start.add_argument("--constraints", default="暂无", help="已知约束。")
    start.set_defaults(handler=command_start)

    append = subparsers.add_parser("append", help="从标准输入追加一条重大里程碑记录。")
    append.add_argument("--root", default=os.getcwd())
    append.add_argument("--id", help="完整记录 ID 或唯一前缀；仅有一个活动记录时可省略。")
    append.add_argument("--milestone", required=True, choices=MILESTONE_TYPES, help="重大里程碑类型。")
    append.add_argument("--title", required=True, help="精炼的里程碑标题。")
    append.set_defaults(handler=command_append)

    transition = subparsers.add_parser("transition", help="追加状态事件并重命名记录文件。")
    transition.add_argument("--root", default=os.getcwd())
    transition.add_argument("--id", help="完整记录 ID 或唯一前缀；仅有一个活动记录时可省略。")
    transition.add_argument("--status", required=True, choices=STATUSES)
    transition.set_defaults(handler=command_transition)

    finalize = subparsers.add_parser("finalize", help="校验并追加最终总结，然后标记已完成。")
    finalize.add_argument("--root", default=os.getcwd())
    finalize.add_argument("--id", help="完整记录 ID 或唯一前缀；仅有一个活动记录时可省略。")
    finalize.set_defaults(handler=command_finalize)

    list_parser = subparsers.add_parser("list", help="列出需求记录。")
    list_parser.add_argument("--root", default=os.getcwd())
    list_parser.add_argument("--active", action="store_true", help="仅列出未完成记录。")
    list_parser.set_defaults(handler=command_list)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = args.handler(args)
    except (WorklogError, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
