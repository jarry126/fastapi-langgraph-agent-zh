# 评测说明

## 概览

`evals/` 目录提供 LLM 输出评测能力，可以基于 Langfuse trace 或指定数据集评估模型回答质量。

## 常见指标

评测 prompt 位于：

```text
evals/metrics/prompts/
```

常见指标包括：

- 相关性
- 有用性
- 简洁性
- 幻觉风险
- 毒性风险

这些 prompt 会直接影响评测结果，因此默认保持原始语言，不建议随意翻译。

## 运行评测

```bash
make eval
make eval-quick
```

或直接运行：

```bash
uv run python -m evals.main
```

## 输出结果

评测会生成 JSON 报告，包含每条 trace 的指标结果和总体成功率。

## 注意事项

- 评测依赖 Langfuse trace
- 评测 prompt 属于运行时语义，不只是普通文档
- 修改评测 prompt 后，历史评测结果可能不可直接对比
