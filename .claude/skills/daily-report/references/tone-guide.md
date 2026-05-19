# Tone Guide for Executive Daily Reports

This guide is read **on demand** when producing an executive-style report. Executive reports go to people who have 30 seconds, not 3 minutes — every word must earn its place.

## Core Principles

1. **Outcome first, process last** — start with the business result, not the technical detail
2. **Numbers beat adjectives** — "提升了 12%" beats "显著提升"
3. **No jargon without context** — if a manager won't recognize a term, replace or briefly explain
4. **No filler phrases** — drop "经过努力 / 总的来说 / 值得一提的是"

## Translation: technical → executive

| Engineer phrasing | Executive phrasing |
|-------------------|--------------------|
| 完成 RPC 接口联调 | 订单中心 V2 已上线，订单创建延迟降低 30% |
| 修复支付回调 bug | 修复支付重复扣款，挽回潜在客诉约 50 单/日 |
| 调研 Kafka 分区数 | 完成消息中间件容量评估，下季度可承接 3 倍流量 |
| 优化 SQL 查询 | 关键报表查询从 8 秒降到 1 秒，运营投诉减少 |

Notice the pattern: **what + measurable impact**, never just "what".

## Word Limit

**150 words / 200 Chinese characters maximum.** This is a hard cap. If raw input doesn't fit, prioritize:

1. Items with measurable business impact
2. Items affecting current quarter goals
3. Blockers requiring management attention

Drop everything else, or compress two items into one summary line.

## Tone

- **Direct, not defensive** — "blocked by X" is fine, "I tried but couldn't" is not
- **Confident, not boastful** — "上线了" beats "成功上线了"
- **Specific, not vague** — name the system, the metric, the date

## Structure (rigid)

```
今日要点（3 行）
风险 / 需支持（0-2 行，无则省略）
明日重点（1-2 行）
```

That's the entire structure. No "今日完成"+"进行中"+"明日计划"+"备注" sections — too granular for executive consumption.

## Example

```
今日要点：
- 订单中心 V2 完成灰度（5% 流量），核心指标平稳，预计周五全量
- 修复支付重复扣款问题，挽回客诉约 50 单/日
- 与 SRE 团队对齐了 Q3 容量规划

需支持：申请扩容 2 台订单服务器用于全量上线（已提工单）

明日重点：监控全量灰度并完成事故复盘文档
```

Count: 约 120 字。Tight, action-oriented, business-relevant.
