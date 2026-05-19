# Format Guide for Standard Daily Reports

This guide is read **on demand** by the daily-report skill when producing a standard report.

## Section Order (strict)

1. **日期 / Date** — top of the document
2. **今日完成 / Done Today** — finished items
3. **进行中 / In Progress** — ongoing items with status
4. **遇到的问题 / Blockers** — only include if there are real blockers; otherwise omit the section
5. **明日计划 / Plan for Tomorrow** — 2-4 items
6. **备注 / Notes** — optional, only if relevant

## Bullet Formatting

- Each bullet is **one sentence**, ≤ 25 Chinese characters or 20 English words
- Start each bullet with a **verb** (完成 / 推进 / 修复 / 调研 / 评审)
- Add a status tag in parentheses when relevant: `(已上线)` / `(待 review)` / `(blocked)`

### Good examples

```
- 完成订单中心 V2 接口联调（已上线灰度）
- 修复支付回调重复扣款 bug（等待 QA 验证）
- 调研 Kafka 分区数对吞吐的影响（结论已同步到群）
```

### Bad examples

```
- 今天我做了订单中心的接口联调，过程中遇到一些问题，最后解决了  ← 太长，无动词开头
- 订单中心  ← 太短，看不出做了什么
- 调研、开会、写代码  ← 笼统，没有具体产出
```

## Code / Link Embedding

- Reference PRs / issues with the platform syntax: `[#1234](url)` or `MR!567`
- Inline code uses single backticks: `OrderService.calculateTotal()`
- Multi-line code blocks are **discouraged in daily reports** — link to the PR instead

## Table Usage

Use a table **only** when there are 4+ parallel items with the same dimensions, e.g.:

| 项目 | 状态 | 备注 |
|------|------|------|
| 订单中心 V2 | 灰度中 | 5% 流量 |
| 支付回调修复 | QA 验证 | — |

For fewer items, use bullets — tables for 1-2 rows look wrong.

## Length Targets

- **Total length**: 200-400 Chinese characters / 150-300 English words
- **Done Today**: 3-6 bullets
- **In Progress**: 1-3 bullets
- **Plan for Tomorrow**: 2-4 bullets

If the user's raw input produces a report longer than 400 chars, compress similar items together.
