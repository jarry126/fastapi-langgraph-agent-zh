---
name: daily-report
description: "当用户需要撰写、生成、整理工作日报、日总结、下班前汇报、standup 更新时使用本 skill。触发关键词包括：日报、写日报、今日总结、下班日报、daily report、EOD report、end of day summary、standup update，以及任何要求总结今天做了什么的请求。支持两种风格：面向团队同步的『标准日报』，以及面向领导的『精简日报』。当用户在代码仓库环境中提到 git 提交时，可自动从 git 日志中抽取工作内容。不要用于周报（请使用 weekly-report skill）、会议纪要或一般写作任务。"
---

# 日报生成器（Daily Report Generator）

## 概述

本 skill 用于生成一份排版规整的 Markdown 日报，支持两种场景：

1. **标准日报** —— 面向团队同步的完整日志
2. **精简日报** —— 面向领导/管理者的高密度摘要

当用户身处 git 仓库时，可自动从 git 提交中抽取工作内容作为原始素材。

## 路由表

| 用户意图 | 处理方式 |
|---------|---------|
| 「写一份日报」/ 默认请求 | 使用 `templates/standard.md`，并阅读 `references/format-guide.md` |
| 「给领导看的日报」/「精简日报」 | 使用 `templates/executive.md`，并阅读 `references/tone-guide.md` |
| 「把今天的 git 提交整理成日报」 | 先运行 `scripts/extract_git_commits.py`，再走标准日报流程 |
| 需要排版细节（表格、代码块等） | 阅读 `references/format-guide.md` |
| 需要把握专业语气 | 阅读 `references/tone-guide.md` |

## 核心流程

请**严格按顺序**执行下面 6 步：

### 第 1 步：确认日报类型

主动询问用户（或从上下文判断）想要哪种日报：

- **standard（标准）** —— 默认值，面向团队的详细日报
- **executive（精简）** —— 给领导看的浓缩版（≤ 200 字）

### 第 2 步：收集原始素材

按以下优先级获取今天的工作项：

1. 如果用户直接粘贴了工作清单 → 直接使用
2. 如果用户处于 git 仓库中，并且提到「git」或「提交」 → 运行：
   ```bash
   python scripts/extract_git_commits.py --since "today 00:00"
   ```
   脚本会返回一段 JSON，包含每条提交的标题、涉及文件和时间戳
3. 以上都没有 → 主动询问用户「今天主要做了哪 3-5 件事」

### 第 3 步：加载对应模板

读取匹配的 template 作为骨架：

```bash
# 标准日报
cat templates/standard.md

# 精简日报
cat templates/executive.md
```

### 第 4 步：填充模板

把模板里所有 `{{占位符}}` 替换成真实内容。**绝不允许**留下空占位符——如果信息缺失，必须先向用户补齐。

### 第 5 步：按规范打磨

- **标准日报** → 严格按 `references/format-guide.md` 中的排版规范处理
- **精简日报** → 严格按 `references/tone-guide.md` 中的语气与字数控制处理

### 第 6 步：交付

将最终日报以 Markdown 代码块的形式呈现给用户，然后主动询问是否需要调整。

## 关键规则（必须遵守）

- **绝不编造工作项** —— 用户没说做了什么，就主动问；凭空捏造比多问一句更糟糕
- **绝不留下 `{{占位符}}`** —— 交付前必须检查所有占位符已替换完成
- **精简日报字数硬性限制 ≤ 200 字** —— 超出必须压缩
- **使用与用户一致的语言** —— 用户用中文沟通就产出中文日报，反之亦然
- **未指定类型时默认 standard** —— 绝大多数日报是给团队看的，不是给领导看的
- **git 提交只是原始素材，不是最终成果** —— 必须把技术语言（"重构 OrderService"）翻译成业务结果（"订单中心 V2 完成重构，性能提升 30%"）

## 依赖说明

- Python 3.8+（用于运行 `scripts/extract_git_commits.py`）
- 系统已安装 Git 命令行工具（仅在使用 git 提取功能时必需）
