---
name: track-dev-work
description: Track a very small set of high-value software development nodes that can reconstruct the whole workflow—goal, decisive analysis or root cause, chosen solution, key verified result, and final summary—in append-only Markdown records, then produce a complete work narrative, multidimensional 10-point assessment, and 1–2 verified resume bullets. Use when the user explicitly asks to start, update, summarize, finish, or review a development record, and while an active record exists to observe progress without writing unless omitting a node would make the final workflow materially harder to reconstruct. Never append merely because another conversation turn, tool call, code edit, intermediate attempt, or routine test occurred.
---

# Track Development Work

## Core rules

- Treat a record as append-only evidence. Never rewrite, truncate, replace, or automatically delete it.
- Permit renaming only to change the status suffix. Require an explicit, unambiguous user request naming the deletion scope before any deletion; this skill and its script intentionally provide no delete command.
- Never equate a conversation turn with a recordable event. Most turns must produce no log write.
- Keep low-level progress in conversational context. Merge it into a later indispensable node instead of persisting it separately.
- Prefer one start record, zero to two important-process nodes, and one final summary for an ordinary requirement.
- Allow at most three automatic process nodes even for a complex task. After that, wait for completion unless the user explicitly requests another record.
- Prefer one node for each narrative role. Wait until the conclusion stabilizes; do not repeatedly record the same analysis, solution, or result.
- Record settled conclusions, decisive judgments, verified root causes, chosen solutions, coherent results, and reusable highlights. Omit command-by-command and edit-by-edit narration.
- Never record passwords, tokens, private keys, credentials, personal sensitive data, or unnecessary proprietary details.
- Never invent impact, scale, latency, revenue, adoption, or percentage metrics. Use `TODO：补充可验证指标` in analysis when evidence is missing.
- Generalize internal names in resume bullets unless the user confirms they are public.

## Locate the script and project

Set `WORKLOG_SCRIPT` to this skill's `scripts/worklog.py`. Pass the current working directory through `--root`; the script resolves the Git top-level directory automatically and otherwise uses the supplied directory.

The script creates `work-records/` at the project root. In Git repositories it appends `/work-records/` to local `.git/info/exclude` without modifying `.gitignore`.

## Start a record

Start only after the user explicitly asks to record a requirement or task. Infer the title, goal, background, scope, success criteria, and constraints from the conversation. Ask only when the title or intended outcome cannot be determined safely; use `待补充` for non-blocking unknowns.

```bash
python3 "$WORKLOG_SCRIPT" start \
  --root "$PROJECT_PATH" \
  --title "$TITLE" \
  --goal "$GOAL" \
  --background "$BACKGROUND" \
  --scope "$SCOPE" \
  --success "$SUCCESS_CRITERIA" \
  --constraints "$CONSTRAINTS"
```

Keep the returned `record_id`. Files use `<标题>_<YYYYMMDD-HHmmss>_<状态>.md`. Support several active requirements without mixing them.

## Select an active record

Use the known ID when context is clear. Otherwise run:

```bash
python3 "$WORKLOG_SCRIPT" list --root "$PROJECT_PATH" --active
```

Use the only active record automatically. If several plausibly match, ask the user which one to update.

## Apply the indispensable-node gate

Allow only these process-node roles:

- `关键判断`: A decisive judgment, tradeoff, scope pivot, or implementation direction becomes stable.
- `根因与方向`: Investigation establishes the actual problem or root cause and the direction that follows from it.
- `解决方案`: The chosen method becomes clear enough to explain what was done, why it worked, and why meaningful alternatives were not used.
- `关键结果`: A coherent result or verification outcome materially changes delivery confidence.
- `用户要求`: The user explicitly asks to record or summarize; consolidate everything important since the prior node.

Before any automatic write, answer all three questions internally:

1. Does the candidate contain a settled conclusion rather than an activity, hypothesis, or temporary attempt?
2. Would deleting it make the final goal → problem → analysis → solution → result workflow materially harder to reconstruct?
3. Will the final summary rely on it to explain the solution, result, highlight, or resume value?

Require three “yes” answers. An explicit user request bypasses the gate, but still produces one consolidated summary instead of a turn transcript.

Never append solely because of:

- A new user or assistant message.
- Reading files, searching code, running commands, or describing planned work.
- A minor edit, rename, formatting change, or routine implementation step.
- An early hypothesis, partial solution, or failed attempt that has not produced a reusable conclusion.
- A repeated build or test without a materially new result.
- Percentage progress, “still working”, or unchanged status.
- Information already represented by an existing node of the same narrative role.

If removing the candidate would not damage workflow reconstruction, do not write it and do not announce a log update.

## Append an indispensable node

When the gate is met, merge related work since the previous node into one concise entry:

```markdown
- 里程碑：一句话说明真正发生了什么重要变化
- 重要过程：只保留关键分析、根因、取舍和决定性步骤
- 结果与证据：说明结果及可复核的代码、测试、日志、联调或验收证据
- 亮点与价值：说明技术难点、工程价值、复用性或简历价值；没有则写“暂无明确亮点”
- 风险与下一步：保留真实风险和下一项关键动作；没有则写“无”
```

```bash
python3 "$WORKLOG_SCRIPT" append \
  --root "$PROJECT_PATH" \
  --id "$RECORD_ID" \
  --milestone "$MILESTONE_TYPE" \
  --title "$CONCISE_NODE_TITLE"
```

The script rejects incomplete fields, duplicate automatic node roles, more than three automatic process nodes, and writes after completion. Use `用户要求` only for an actual user-requested update.

## Change status

Use `进行中`, `受阻`, `待验证`, and `已完成`. Transition only when delivery state materially changes; do not use status changes as progress narration.

```bash
python3 "$WORKLOG_SCRIPT" transition --root "$PROJECT_PATH" --id "$RECORD_ID" --status "待验证"
```

Do not mark work complete merely because code was written. Keep it `待验证` while required integration, rollout, or acceptance evidence remains.

## Complete and reconstruct the workflow

Treat “完成”, “完成记录”, “结束记录”, or “总结并完成” as the signal to build the complete final narrative.

Before finalizing:

1. Resolve the active record and read the entire Markdown file, not only the latest node.
2. Review the current conversation and available code or verification evidence for important facts intentionally left out of process nodes.
3. Reconstruct one causal workflow: goal → problem → analysis → proposed directions → chosen solution → result.
4. Give `解决方法` the most detail—roughly one third of the narrative. Explain the actual method, key implementation steps, why it worked, and meaningful tradeoffs.
5. Score conservatively from evidence. Do not inflate a simple task merely because it was completed successfully.
6. Produce exactly one or two resume bullets from verified facts. Do not invent metrics. Keep unfinished `TODO` placeholders out of the final bullets.

If automated verification is absent but the user explicitly confirms completion, treat that confirmation as acceptance evidence and disclose which technical checks were not run.

Prepare this exact structure:

```markdown
### 开发/工作目标
说明背景、目标、范围和成功标准。

### 工作流程复原
用少量有因果关系的节点还原从开始到完成的全过程。

### 遇到的问题
说明真正影响推进的问题、限制和难点，省略无意义的试错。

### 中间分析与方向
说明关键判断、有效排除过程、提出过的方向和选择依据。

### 解决方法
重点说明最终方法、关键实现步骤、原理、取舍，以及它为什么解决问题。

### 最终结果与验证
说明交付效果、成功标准达成情况、测试/联调/验收证据及未验证项。

### 整体亮点
提炼技术难点、工程质量、业务或团队价值、可复用性和面试展开价值。

### 简历价值评分
- 技术难度：X/10 — 依据
- 内容丰富度：X/10 — 依据
- 证据真实度：X/10 — 依据
- 技术精彩度：X/10 — 依据
- 简历价值：X/10 — 依据
- 综合评分：X/10 — 综合说明

### 建议写进简历的部分
- 第一条可直接使用的简历描述
- 可选的第二条；没有足够独立事实时只输出一条
```

Run:

```bash
python3 "$WORKLOG_SCRIPT" finalize --root "$PROJECT_PATH" --id "$RECORD_ID"
```

The script validates all workflow sections, six scores, one or two resume bullets, and result evidence before appending the final summary and renaming the file to `已完成`. After a successful write, output the same narrative directly to the user.

## Report writes

After a successful indispensable-node write, briefly state which requirement and node were updated and provide the path. Say nothing about logging on turns where no write occurred. If a write fails, preserve the record and report the exact failure.
