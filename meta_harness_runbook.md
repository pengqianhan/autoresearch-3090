# Meta-Harness 操作手册

这份手册只讲怎么操作，不重复解释设计背景。原理和数据流说明见 [`meta_harness.md`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness.md)。

## 1. 目标

在当前仓库中运行自动化 Meta-Harness 外循环，优化 [`program.md`](/home/phan635/AI_researcher/autoresearch-pq/program.md)，并把每轮候选、评估结果和 trace 记录到 `meta_harness/` 目录下。

## 2. 你会用到的文件

- 设计文档：[`meta_harness.md`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness.md)
- 外循环脚本：[`scripts/run_meta_harness.py`](/home/phan635/AI_researcher/autoresearch-pq/scripts/run_meta_harness.py)
- trace 结构化脚本：[`scripts/extract_claude_experience.py`](/home/phan635/AI_researcher/autoresearch-pq/scripts/extract_claude_experience.py)
- proposer wrapper：[`scripts/run_claude_proposer.sh`](/home/phan635/AI_researcher/autoresearch-pq/scripts/run_claude_proposer.sh)
- evaluator wrapper：[`scripts/run_claude_evaluator.sh`](/home/phan635/AI_researcher/autoresearch-pq/scripts/run_claude_evaluator.sh)
- 示例配置：[`meta_harness/config.example.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.example.json)
- 本机配置：[`meta_harness/config.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.json)
- smoke test 配置：[`meta_harness/config.smoke.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.smoke.json)
- 原始经验库：[`experience/claude-session`](/home/phan635/AI_researcher/autoresearch-pq/experience/claude-session)
- 结构化经验库：[`experience/structured`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured)

## 3. 运行前检查

### 3.1 检查 Claude CLI

```bash
which claude
claude --help | head -40
```

期望：

- `claude` 可执行
- CLI 帮助正常输出

### 3.2 检查经验库是否存在

```bash
find experience/claude-session -maxdepth 2 -type f | head
find experience/structured -maxdepth 1 -type f | sort
```

期望：

- 有主会话 JSONL
- 有 `manifest.json`、`summary.json`、`experiments.json`

如果 `experience/structured/` 缺失，先运行：

```bash
python scripts/extract_claude_experience.py
```

### 3.3 检查 Python 脚本语法

```bash
python -m py_compile scripts/extract_claude_experience.py scripts/run_meta_harness.py
```

期望：

- 无输出，无报错

## 4. 第一阶段：先验证 Claude CLI adapter

在直接跑 Meta-Harness 之前，先验证 Claude CLI 的非交互调用是否可靠。

### 4.1 最小返回测试

```bash
/home/phan635/.local/bin/claude -p \
  --permission-mode bypassPermissions \
  --tools "" \
  "Reply with exactly: ok"
```

期望：

- 在较短时间内返回
- 输出 `ok`

如果卡住，不要继续跑 Meta-Harness，先调 CLI adapter。

### 4.1.1 wrapper 自检

推荐优先直接测试 wrapper，因为正式配置已经改成通过 wrapper 调用。

```bash
python scripts/run_meta_harness.py --config meta_harness/config.json --iterations 0

MH_REPO_ROOT=$(pwd) \
MH_CANDIDATE_DIR=$(pwd)/meta_harness/runs/seed \
MH_CANDIDATE_PROGRAM=$(pwd)/meta_harness/runs/seed/candidate_program.md \
./scripts/run_claude_proposer.sh
```

说明：

- `--iterations 0` 现在会正确覆盖配置，只做 seed 初始化
- 如果要测试 adapter 模式切换，可以临时加：

```bash
MH_CLAUDE_PROPOSER_MODE=stdin ...
MH_CLAUDE_PROPOSER_MODE=json ...
```

### 4.2 只读文件测试

```bash
/home/phan635/.local/bin/claude -p \
  --permission-mode bypassPermissions \
  --add-dir /home/phan635/AI_researcher/autoresearch-pq \
  --allowedTools "Read" \
  "Read program.md and reply with its first heading only."
```

期望：

- Claude 可以读 [`program.md`](/home/phan635/AI_researcher/autoresearch-pq/program.md)
- 有稳定输出

### 4.3 单文件编辑测试

在临时目录中：

```bash
mkdir -p /tmp/meta-harness-adapter-test
printf '# note\n' > /tmp/meta-harness-adapter-test/note.txt
cd /tmp/meta-harness-adapter-test

/home/phan635/.local/bin/claude -p \
  --permission-mode bypassPermissions \
  --allowedTools "Read Edit Write" \
  "Edit note.txt and append one line: smoke test"
```

期望：

- `note.txt` 被修改
- 进程正常结束

## 5. 第二阶段：运行 smoke test

smoke test 的目的不是优化出最优 harness，而是验证整条链路：

- proposer 能返回
- candidate 能被改写
- evaluator workspace 能创建
- evaluator 能跑
- score 能被提取

### 5.1 启动 smoke test

```bash
python scripts/run_meta_harness.py --config meta_harness/config.smoke.json
```

### 5.2 观察运行目录

```bash
find meta_harness/runs_smoke -maxdepth 3 | sort
find meta_harness/workspaces_smoke -maxdepth 3 | sort
```

重点看：

- `meta_harness/runs_smoke/iter_001/candidate_program.md`
- `meta_harness/runs_smoke/iter_001/proposer_stdout.txt`
- `meta_harness/runs_smoke/iter_001/proposer_stderr.txt`
- `meta_harness/runs_smoke/iter_001/result.json`
- `meta_harness/runs_smoke/iter_001/evaluation_summary.json`

### 5.3 smoke test 判定标准

成功至少要满足：

1. `candidate_program.md` 被 proposer 实际修改
2. `workspaces_smoke/iter_001` 被创建
3. workspace 中出现 `results.tsv` 或 `run.log`
4. `result.json` 被写出
5. `result.json` 中 `score` 非空

## 6. 第三阶段：运行正式 Meta-Harness

如果 smoke test 跑通，再运行正式配置。

### 6.1 启动正式 run

```bash
python scripts/run_meta_harness.py --config meta_harness/config.json
```

### 6.2 指定迭代数覆盖配置

```bash
python scripts/run_meta_harness.py --config meta_harness/config.json --iterations 1
```

这个命令适合做短验证。

### 6.3 正式运行时看哪里

每轮目录：

- [`meta_harness/runs`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/runs)

典型结构：

- `seed/`
- `iter_001/`
- `iter_002/`
- `state.json`

每轮重点文件：

- `candidate_program.md`
- `history.json`
- `proposer_prompt.txt`
- `proposer_stdout.txt`
- `proposer_stderr.txt`
- `evaluator_stdout.txt`
- `evaluator_stderr.txt`
- `evaluation_summary.json`
- `result.json`
- `claude_trace/`（如果 trace copy 成功）

## 7. 如何看结果

### 7.1 看当前全局状态

```bash
sed -n '1,240p' meta_harness/runs/state.json
```

关注：

- `seed_initialized`
- `candidates`
- 每轮 candidate 的 `score`
- `status`

### 7.2 看某一轮 proposer 是否成功

```bash
sed -n '1,240p' meta_harness/runs/iter_001/proposer_stdout.txt
sed -n '1,240p' meta_harness/runs/iter_001/proposer_stderr.txt
diff -u program.md meta_harness/runs/iter_001/candidate_program.md | sed -n '1,200p'
```

### 7.3 看某一轮 evaluator 是否成功

```bash
sed -n '1,240p' meta_harness/runs/iter_001/evaluator_stdout.txt
sed -n '1,240p' meta_harness/runs/iter_001/evaluator_stderr.txt
sed -n '1,240p' meta_harness/runs/iter_001/evaluation_summary.json
sed -n '1,240p' meta_harness/runs/iter_001/result.json
```

### 7.4 看 workspace 内真实产物

```bash
find meta_harness/workspaces/iter_001 -maxdepth 2 | sort | sed -n '1,200p'
sed -n '1,80p' meta_harness/workspaces/iter_001/results.tsv
tail -n 80 meta_harness/workspaces/iter_001/run.log
```

## 8. 常见故障和处理方法

### 故障 1：proposer 卡住，没有 stdout/stderr

症状：

- `proposer_stdout.txt` 为空
- `proposer_stderr.txt` 可能只有 wrapper 自己打印的启动信息
- `candidate_program.md` 没变化
- 没进入 workspace/evaluator

处理顺序：

1. 先单独手工跑最小 `claude -p`
2. 再通过 wrapper 试 `MH_CLAUDE_PROPOSER_MODE=stdin`
3. 再通过 wrapper 试 `MH_CLAUDE_PROPOSER_MODE=json`
4. 再试更小工具集
5. 读 wrapper 输出，必要时直接修改 wrapper 脚本

### 故障 2：proposer 成功，但 evaluator 没出结果

症状：

- `candidate_program.md` 已修改
- workspace 已创建
- `result.json` 没有 `score`

处理：

1. 读 `evaluator_stdout.txt`
2. 读 `evaluator_stderr.txt`
3. 检查 workspace 里的 `results.tsv`
4. 检查 workspace 里的 `run.log`

### 故障 3：score extractor 读不到分数

症状：

- `evaluation_summary.json` 中是 `missing_results` 或 `results_no_positive_score`

处理：

1. 看 workspace 是否真的生成了 `results.tsv`
2. 看 `results.tsv` 格式是否仍是 tab-separated
3. 看 `run.log` 中是否有 `val_bpb:` 行
4. 必要时修改 [`scripts/run_meta_harness.py`](/home/phan635/AI_researcher/autoresearch-pq/scripts/run_meta_harness.py) 中的 `extract_score()`

### 故障 4：trace copy 没有带回新 trace

症状：

- `iter_xxx/claude_trace/` 不存在

处理：

1. 检查 `claude_projects_dir` 是否正确
2. 检查 `sanitize_project_dir(workspace_dir)` 生成的目录名是否匹配 `.claude/projects/` 下真实目录
3. 检查新 trace 的 mtime 是否晚于该轮 `started_at`

## 9. 推荐的日常运行方式

最稳妥的工作流：

1. 更新结构化经验库

```bash
python scripts/extract_claude_experience.py
```

2. 先做 adapter 最小验证

3. 运行 smoke test

```bash
python scripts/run_meta_harness.py --config meta_harness/config.smoke.json
```

4. smoke test 成功后，再跑正式配置

```bash
python scripts/run_meta_harness.py --config meta_harness/config.json --iterations 1
```

5. 确认第一轮正式 run 正常，再放开到多轮

```bash
python scripts/run_meta_harness.py --config meta_harness/config.json
```

## 10. 当前已知现实情况

截至当前仓库状态：

- 结构化经验库已经准备好
- Meta-Harness outer-loop 脚本已经可运行
- 本机专用 [`meta_harness/config.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.json) 已生成
- 一次真实 smoke test 已经证明：
  - outer-loop 初始化没问题
  - wrapper 已接入并能暴露更具体的 proposer 启动信息
  - proposer CLI adapter 仍需继续调通

所以当前最优先动作仍然是：

`先调通 Claude CLI adapter，再把 smoke test 跑通。`
