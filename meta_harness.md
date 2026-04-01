# Meta-Harness 自动化方案说明

本文档说明本仓库中如何把 [`Lee et al. - Meta-Harness End-To-End Optimization of Model Harnesses.pdf`](/home/phan635/AI_researcher/autoresearch-pq/Lee%20et%20al.%20-%20Meta-Harness%20End-To-End%20Optimization%20of%20Model%20Harnesses.pdf) 的核心思想，落到当前 `autoresearch` 项目里，并解释：

- 什么是本项目里的 “harness”
- 历史 trace 从哪里来
- 这些数据如何被读取、清洗、结构化
- 自动化 outer-loop 如何组织
- 当前实现和论文原始系统的一致点与差异
- 这套流程最终应该怎么运行

## 1. 本项目里什么是 Harness

在论文里，`harness` 指的是模型外面的那层程序逻辑，也就是：

- 给模型看什么信息
- 什么时候看
- 如何组织上下文
- 如何利用记忆、检索、工具调用和历史经验

在当前仓库里，最接近这个定义的不是 [`train.py`](/home/phan635/AI_researcher/autoresearch-pq/train.py)，而是 [`program.md`](/home/phan635/AI_researcher/autoresearch-pq/program.md)。

原因很直接：

- `train.py` 是被 agent 优化的研究对象
- `program.md` 定义了 agent 如何搜索 `train.py`
- Claude / Codex 的行为路径，本质上由 `program.md` 决定

所以本项目里的 Meta-Harness 目标是：

`优化 program.md，使固定底层 agent 在固定预算内找到更好的 train.py 改动。`

这正对应论文里的 “optimize the harness around a fixed model”。

## 2. 论文方法的核心要点

结合论文第 3 节和 Appendix A / D，可以把 Meta-Harness 的核心抽成四句话：

1. 不直接优化模型权重，而是优化 harness 代码。
2. proposer 不是只看分数，而是读取历史候选的代码、trace、分数。
3. 历史经验不是压缩成单条 summary，而是保存在可检索 filesystem 中。
4. outer-loop 尽量简单，把诊断和 proposal 决策交给 coding agent。

论文里反复强调几个实现原则，这里直接对应到当前仓库：

- “full history through a filesystem”
  - 对应当前的 [`experience/`](/home/phan635/AI_researcher/autoresearch-pq/experience)

- “stores source code, scores, and execution traces”
  - 对应当前的 [`experience/claude-session`](/home/phan635/AI_researcher/autoresearch-pq/experience/claude-session) 和 [`experience/structured`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured)

- “proposer selectively inspects prior code and traces rather than consuming a fixed summary”
  - 对应当前 proposer prompt 里要求优先检查 `summary.json`、`experiments.json`、`file_reads.json`

- “write a good skill”
  - 对应当前 seed harness [`program.md`](/home/phan635/AI_researcher/autoresearch-pq/program.md) 和 proposer 对 `candidate_program.md` 的修改目标

- “automate evaluation outside the proposer”
  - 对应当前 [`scripts/run_meta_harness.py`](/home/phan635/AI_researcher/autoresearch-pq/scripts/run_meta_harness.py) 的外层 orchestrator

## 3. 当前仓库中的数据来源

### 3.1 原始 trace

高价值原始 trace 来自此前 Claude Code 的运行目录：

- `/home/phan635/.claude/projects/-home-phan635-AI-researcher-autoresearch-pq`

已经复制到仓库内：

- [`experience/claude-session/main`](/home/phan635/AI_researcher/autoresearch-pq/experience/claude-session/main)
- [`experience/claude-session/subagents`](/home/phan635/AI_researcher/autoresearch-pq/experience/claude-session/subagents)
- [`experience/claude-session/tool-results`](/home/phan635/AI_researcher/autoresearch-pq/experience/claude-session/tool-results)

其中最重要的是：

- 主会话 JSONL
  - [`experience/claude-session/main/cb0c7479-9630-4814-b0d0-b97fa80352a5.jsonl`](/home/phan635/AI_researcher/autoresearch-pq/experience/claude-session/main/cb0c7479-9630-4814-b0d0-b97fa80352a5.jsonl)

它包含：

- user / assistant 消息
- tool_use
- tool_result
- 时间戳
- cwd
- git branch
- 工具调用参数和工具输出

这正是论文里所说的 execution traces。

### 3.2 本仓库已有的显式实验结果

除了 Claude trace，本仓库还有两个关键结果源：

- [`results.tsv`](/home/phan635/AI_researcher/autoresearch-pq/results.tsv)
- [`run.log`](/home/phan635/AI_researcher/autoresearch-pq/run.log)

它们提供：

- 每次实验的 `val_bpb`
- `peak_vram_mb`
- `keep / discard / crash`
- 实验说明文字

论文里把这类信息归入 scores。

### 3.3 代码状态

还需要用到：

- 当前 harness 种子：[`program.md`](/home/phan635/AI_researcher/autoresearch-pq/program.md)
- 当前研究对象：[`train.py`](/home/phan635/AI_researcher/autoresearch-pq/train.py)
- 历史版本：git commit / git log

这对应论文里的 prior source code。

## 4. 数据如何被读取和处理

### 4.1 第一步：复制高价值 trace 到仓库内

目的：

- 把仓库外的 Claude 运行数据变成项目内可管理资产
- 保证后续 proposer 可以在同一 repo 中检索历史经验

结果目录：

- [`experience/README.md`](/home/phan635/AI_researcher/autoresearch-pq/experience/README.md)
- [`experience/claude-session`](/home/phan635/AI_researcher/autoresearch-pq/experience/claude-session)

保留这些文件的理由：

- 主 JSONL 是最完整的执行轨迹
- `subagents/` 保留了分支探索
- `tool-results/` 保留了部分大输出

没有优先保留的内容：

- 单纯的 progress/hook 事件

理由：

- 它们对“为什么某个 harness 更好”帮助较小
- 容易制造大量噪声

这和论文的结论一致：关键不是所有原始日志，而是保留对 credit assignment 有帮助的 trace。

### 4.2 第二步：把原始 JSONL 结构化

使用脚本：

- [`scripts/extract_claude_experience.py`](/home/phan635/AI_researcher/autoresearch-pq/scripts/extract_claude_experience.py)

生成目录：

- [`experience/structured`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured)

生成文件：

- [`manifest.json`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured/manifest.json)
- [`summary.json`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured/summary.json)
- [`events.jsonl`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured/events.jsonl)
- [`file_reads.json`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured/file_reads.json)
- [`experiments.json`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured/experiments.json)
- [`README.md`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured/README.md)

#### 4.2.1 `events.jsonl`

这是主会话的扁平事件流。

提取的事件类型主要是：

- `assistant_tool_use`
- `tool_result`
- `assistant_text`
- `user_text`

理由：

- 这是把 Claude 内部 JSONL 变成可检索流水账的第一层
- 方便后续按时间、工具、命令过滤

#### 4.2.2 `file_reads.json`

专门抽出读取过哪些文件、何时读的。

理由：

- 论文 Appendix A 专门统计 proposer 的 file access
- 在 Meta-Harness 里，“读了哪些历史文件”本身就是重要信号
- 这能回答：agent 在诊断时真正依赖了什么

#### 4.2.3 `experiments.json`

这是最关键的结构化文件。

它围绕每次：

- `uv run train.py`

构建一个 experiment record，并尽量关联：

- preceding commit
- grep metrics
- run command
- branch / cwd
- 附近的 edit 上下文

当前 record 的核心字段包括：

- `train_command`
- `train_timestamp`
- `commit_command`
- `commit_hash`
- `commit_message`
- `val_bpb`
- `peak_vram_mb`
- `results_updates`
- `reset_commands`

理由：

- 论文关心的是 harness 修改后的最终 rollout outcome
- 在本项目中，最接近 rollout 单位的就是一次完整实验运行
- 因此 `experiments.json` 是 proposer 最该看的 “structured history”

### 4.3 第三步：用结构化数据给 proposer 提供检索入口

当前 proposer prompt 明确要求优先看：

- `experience/structured/summary.json`
- `experience/structured/experiments.json`
- `experience/structured/file_reads.json`

这是一个刻意的折中。

理由：

- 论文强调 full-history filesystem access
- 但在工程上，直接让 proposer 从 40MB+ JSONL 开始检索很低效
- 所以当前实现保留 raw trace，同时再做一层轻量结构化索引

这里的原则是：

- raw trace 不能丢
- 但 proposer 不需要每次都从 raw trace 开始

这和论文 Appendix D 的建议一致：history grows 后，最好有一层更容易查询的 CLI 或结构化摘要。

## 5. 自动化 outer-loop 的设计

### 5.1 外循环脚本

主脚本：

- [`scripts/run_meta_harness.py`](/home/phan635/AI_researcher/autoresearch-pq/scripts/run_meta_harness.py)

它做的事情不是“替代 agent”，而是做 orchestration。

这是论文明确建议的做法：

- proposer 负责 diagnosis 和 proposal
- evaluator 负责实际评分
- outer-loop 保持尽量简单

### 5.2 当前 outer-loop 的运行步骤

每一轮 iteration：

1. 从历史结果中选当前 best candidate
2. 复制父 harness，生成新的 `candidate_program.md`
3. 生成 proposer prompt 和 history snapshot
4. 调 proposer 命令，让它修改 `candidate_program.md`
5. 复制整个 repo 到隔离 workspace
6. 用新 `candidate_program.md` 覆盖 workspace 里的 `program.md`
7. 调 evaluator 命令，让 agent 在 workspace 中实际跑一轮 autoresearch
8. 从 `results.tsv` 和 `run.log` 提取得分
9. 如果开启 trace copy，则把新产生的 Claude trace 一起复制回本轮 run 目录
10. 把结果写入 `meta_harness/runs/...`

### 5.3 为什么必须复制到独立 workspace

理由：

- 每轮候选需要隔离运行
- 不能让不同候选互相污染 repo 状态
- 不能让新的 `program.md` 直接覆盖主仓库

这对应论文里 “evaluate candidate harnesses separately and store artifacts per candidate” 的思想。

### 5.4 为什么 score extractor 先看 `results.tsv`，再回退到 `run.log`

理由：

- `results.tsv` 是 agent 自己承认的实验日志
- 它包含 keep/discard 语义和实验说明
- `run.log` 是更底层但更原始的 fallback

在当前 repo 中，这样最稳。

处理逻辑：

- 如果 `results.tsv` 存在，扫描正数 `val_bpb`，取最优值
- 如果 `run.log` 里有 `val_bpb` 但 `results.tsv` 缺失，则回退到 `run.log`
- 同时尝试抽取 `peak_vram_mb`

注释：

- 这不是论文唯一合法做法
- 只是最贴合本仓库已有实验格式的 evaluator summarization

## 6. 当前配置文件的作用

### 6.1 示例配置

- [`meta_harness/config.example.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.example.json)

作用：

- 保留一个通用模板
- 不假设本机 Claude CLI 路径
- 作为移植参考

### 6.2 本机专用配置

- [`meta_harness/config.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.json)

它针对本机做了这些本地化：

- proposer / evaluator 都通过 wrapper 调用：
  - [`scripts/run_claude_proposer.sh`](/home/phan635/AI_researcher/autoresearch-pq/scripts/run_claude_proposer.sh)
  - [`scripts/run_claude_evaluator.sh`](/home/phan635/AI_researcher/autoresearch-pq/scripts/run_claude_evaluator.sh)

- wrapper 内部再调用本机 Claude CLI：
  - `/home/phan635/.local/bin/claude`

- proposer wrapper 现在支持 adapter 调试模式：
  - `MH_CLAUDE_PROPOSER_MODE=prompt`
  - `MH_CLAUDE_PROPOSER_MODE=stdin`
  - `MH_CLAUDE_PROPOSER_MODE=json`

- proposer 仍保留超时：
  - `timeout_sec = 900`

理由：

- 减少 PATH 和目录访问的不确定性
- 把 CLI adapter 问题和 outer-loop 逻辑分开
- 提高 CLI 在自动化子进程里运行时的可诊断性

### 6.3 smoke test 配置

- [`meta_harness/config.smoke.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.smoke.json)

用途：

- 只做一轮受限测试
- evaluator prompt 明确要求：
  - setup if needed
  - run at most one completed training experiment
  - then stop

理由：

- 原始 `program.md` 有 “LOOP FOREVER”
- 如果不人为约束，smoke test 可能会无限跑

这属于论文之外、但在当前项目里必须补的工程安全约束。

## 7. 这套实现与论文的一致点

一致点：

- 优化对象是 harness，而不是模型权重
- proposer 访问历史经验而不是只看标量分数
- 保留 raw traces 到 filesystem
- outer-loop 保持简单
- evaluator 和 proposer 解耦
- 每轮 run 有独立 artifact 目录

## 8. 这套实现与论文的差异

差异主要有四个：

### 8.1 Harness 载体不同

论文中的 harness 多是 Python 程序。

当前项目里：

- harness 是 `program.md`

这不是违背论文，只是当前任务域的自然适配。

### 8.2 经验存储是后补的

论文从一开始就把 code / score / trace 都系统化存盘。

当前项目里：

- 很多历史实验先发生了
- 后来才把 Claude trace 从 `.claude/projects` 中复制回仓库并结构化

所以现在的 `experience/` 是 “retrofit experience store”。

### 8.3 proposer/evaluator 都通过外部 CLI 调用

论文里 proposer 本身就是 coding agent。

当前实现里：

- outer-loop 脚本只管调外部命令
- 真正的 proposer/evaluator 还是 Claude CLI

这是更现实的工程做法，因为它把 agent 视为黑盒。

### 8.4 当前阻塞点是 CLI 自动化，而不是 Meta-Harness 逻辑

已经做过真实 smoke test，结果是：

- outer-loop 初始化成功
- proposer 阶段卡住
- evaluator 尚未开始

这说明：

- Meta-Harness scaffolding 本身已经成形
- 当前最需要调的是 Claude CLI 的非交互自动化适配

## 9. 当前 smoke test 的实际结论

受限 smoke test 使用：

- [`meta_harness/config.smoke.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.smoke.json)

结果：

- 成功创建：
  - [`meta_harness/runs_smoke/seed`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/runs_smoke/seed)
  - [`meta_harness/runs_smoke/iter_001`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/runs_smoke/iter_001)

- 成功写出：
  - `history.json`
  - `proposer_prompt.txt`

- 未成功完成：
  - proposer 没有返回
  - `candidate_program.md` 没被修改
  - 没进入 evaluator workspace
  - 没写出 `result.json`

这说明当前还不能宣称整条自动化链已 fully operational。

## 10. 整个 Meta-Harness 流程应该如何运行

### 10.1 先准备经验存储

如果你是第一次在新历史数据上运行：

```bash
python scripts/extract_claude_experience.py
```

这一步会更新：

- [`experience/structured`](/home/phan635/AI_researcher/autoresearch-pq/experience/structured)

### 10.2 检查配置

通用模板：

- [`meta_harness/config.example.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.example.json)

本机版本：

- [`meta_harness/config.json`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/config.json)

如果你要做真实 run，用：

```bash
python scripts/run_meta_harness.py --config meta_harness/config.json
```

### 10.3 如果只是做安全验证

用 smoke test：

```bash
python scripts/run_meta_harness.py --config meta_harness/config.smoke.json
```

### 10.4 查看运行产物

真实 run：

- [`meta_harness/runs`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/runs)
- [`meta_harness/workspaces`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/workspaces)

smoke test：

- [`meta_harness/runs_smoke`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/runs_smoke)
- [`meta_harness/workspaces_smoke`](/home/phan635/AI_researcher/autoresearch-pq/meta_harness/workspaces_smoke)

每轮 iteration 下你会看到：

- `candidate_program.md`
- `history.json`
- `proposer_prompt.txt`
- `proposer_stdout.txt`
- `proposer_stderr.txt`
- `evaluator_stdout.txt`
- `evaluator_stderr.txt`
- `evaluation_summary.json`
- `result.json`
- 可选的 `claude_trace/`

### 10.5 如何判断 run 成功

至少需要满足：

1. proposer 修改了 `candidate_program.md`
2. evaluator workspace 被创建
3. workspace 里出现 `results.tsv` 或 `run.log`
4. `result.json` 被写出
5. `result.json` 中有 `score`

### 10.6 当前最推荐的实际执行顺序

现阶段最推荐：

1. 先确认 Claude CLI 非交互子进程行为
2. 再用 `config.smoke.json` 跑通一轮 proposer + evaluator
3. 再切到 `config.json` 做真实多轮 run

原因：

- 当前 outer-loop 已经搭好
- 真正的不确定性在 Claude CLI adapter
- 不先打通 adapter，直接长跑只会浪费时间

## 11. 后续最值得继续完善的点

按优先级排序：

1. 修 proposer CLI adapter
2. 把 `results.tsv` 对齐成更干净的 keep/discard/crash 字段
3. 把 subagent traces 也结构化进统一 schema
4. 给 `experiments.json` 增加更干净的 parent / decision / intent 字段
5. 增加一个专门的 search index，减少 proposer 导航成本

## 11.1 如何继续调通 Claude CLI adapter

当前最现实的下一步，不是继续扩 outer-loop，而是把 `claude -p` 在自动化子进程里的行为调通。

### A. 当前已知现象

从真实 smoke test 看：

- outer-loop 已经能启动
- `proposer_prompt.txt` 已成功生成
- proposer 子命令启动后，没有：
  - stdout
  - stderr
  - 文件编辑
  - evaluator 后续动作

这说明问题大概率出在：

- Claude CLI 非交互调用被阻塞
- Claude CLI 等待某种交互式前置条件
- 当前命令模板对 `-p` 模式并不稳

### B. 推荐的排查顺序

建议按从小到大、从无工具到有工具的顺序排查。

#### B1. 先验证最小只读调用

目标：

- 确认 `claude -p` 本身能在非交互模式下返回

建议命令：

```bash
/home/phan635/.local/bin/claude -p \
  --permission-mode bypassPermissions \
  --tools "" \
  "Reply with exactly: ok"
```

如果这一步都卡住，说明问题和 Meta-Harness 无关，而是 CLI 本身的：

- 认证状态
- 非交互模式
- 本机环境

#### B2. 再验证带结构化输出的最小调用

目标：

- 确认 `--output-format json` 或 `stream-json` 是否可用

建议命令：

```bash
/home/phan635/.local/bin/claude -p \
  --output-format json \
  --permission-mode bypassPermissions \
  --tools "" \
  "Reply with exactly: ok"
```

理由：

- 如果 text 输出卡住而 json 正常，后续 adapter 最好直接切到 JSON 输出
- 如果 `stream-json` 更稳，后续 wrapper 也可以改成流式解析

#### B3. 再验证只读文件访问

目标：

- 确认 CLI 能在 `-p` 模式下访问 repo 文件

建议命令：

```bash
/home/phan635/.local/bin/claude -p \
  --permission-mode bypassPermissions \
  --add-dir /home/phan635/AI_researcher/autoresearch-pq \
  --allowedTools "Read" \
  "Read program.md and reply with its first heading only."
```

理由：

- proposer 真正需要的第一能力不是编辑，而是读历史经验和当前 harness
- 先打通只读链路，能把问题范围缩小很多

#### B4. 最后验证单文件编辑

目标：

- 确认 CLI 能在当前模式下完成可控编辑

建议在一个临时目录中放一个简单文本文件，再执行：

```bash
/home/phan635/.local/bin/claude -p \
  --permission-mode bypassPermissions \
  --allowedTools "Read Edit Write" \
  "Edit note.txt and append one line: smoke test"
```

理由：

- proposer 最核心的动作是改 `candidate_program.md`
- 如果简单编辑都不稳定，outer-loop 不可能稳定

### C. 优先尝试的 CLI 选项

结合当前 CLI 帮助和 smoke test 结果，优先建议测试这几个方向：

#### C1. 加 `--bare`

建议测试：

```bash
/home/phan635/.local/bin/claude -p --bare ...
```

理由：

- `--bare` 会关掉 hooks、自动发现、额外预取等行为
- 在自动化子进程里，这通常更接近论文里的 “minimal outer loop”

注释：

- 当前 smoke test 没用 `--bare`
- 很可能值得作为下一个最优先实验

#### C2. 缩小工具集

当前 proposer 已经限制了工具，但还可以更保守：

- 第一轮只给 `Read`
- 第二轮再加 `Edit`
- 第三轮再加有限 `Bash`

理由：

- 工具面越大，CLI 可能做的启动检查越多
- 论文强调的是 selective retrieval，不是大而全的工具箱

#### C3. 显式指定输出格式

建议尝试：

- `--output-format json`
- `--output-format stream-json`

理由：

- 自动化环境里，结构化输出通常比默认 text 更稳、更易诊断

#### C4. 显式指定模型和 effort

建议尝试：

- `--model opus`
- `--effort low`

理由：

- 避免 CLI 默认值在本机环境中引入不必要变动
- smoke test 的目标是“尽快返回”，不是最好答案

### D. 推荐增加一个专门的 wrapper 脚本

当前 `config.json` 里直接把长命令写进 JSON。

更推荐下一步改成：

- `scripts/run_claude_proposer.sh`
- `scripts/run_claude_evaluator.sh`

理由：

- 更容易单独调试
- 可以在 wrapper 里：
  - 打印真实命令
  - 打印环境变量
  - 打印开始/结束时间
  - 记录 exit code
  - 增加 fallback 选项

比如 proposer wrapper 可以做：

1. 先运行一个最小 `claude -p --tools "" "ok"` 自检
2. 自检通过后再跑真正 proposer
3. 如果超时或无输出，落一个明确错误文件

这会比现在的黑盒 shell 字符串更容易定位问题。

### E. 推荐的 adapter 验收标准

只有同时满足以下条件，才算 CLI adapter 调通：

1. 最小 `-p` 调用可在几十秒内稳定返回
2. 只读文件调用可稳定返回
3. 单文件编辑调用可稳定完成
4. 在 `candidate_program.md` 上能产生实际改动
5. `run_meta_harness.py` 能在 proposer 完成后继续进入 evaluator
6. smoke test 最终能写出：
   - `result.json`
   - `evaluation_summary.json`

### F. 一条最推荐的实际推进路线

建议严格按下面顺序推进：

1. 先手工在 shell 里跑最小 `claude -p`
2. 再手工跑只读 `Read`
3. 再手工跑小编辑
4. 把成功命令固化进 wrapper 脚本
5. 再把 `config.smoke.json` 改为调用 wrapper
6. 再重跑 smoke test

这是当前最省时间、最少误判的路径。

## 12. 总结

这套 Meta-Harness 方案已经具备论文方法的核心骨架：

- harness 优化对象明确
- raw trace 已保留
- structured experience store 已建立
- outer-loop 已实现
- proposer / evaluator 已解耦

当前最大的工程阻塞点不是方法论，而是：

`Claude CLI 在自动化非交互子进程中的稳定返回行为仍需调通。`

补充说明：

- `run_meta_harness.py` 中 `--iterations 0` 覆盖配置的 bug 已修复
- 现在可以可靠地用 `--iterations 0` 只做 seed 初始化

只要这个 adapter 打通，这套系统就可以从“理论上可运行”进入“实际自动化搜索 program.md”的阶段。
