# 结果索引

报告是既有实验的发布整理版，数值、负结果、成本和结论边界保留。它们没有因本次打包重新运行。归档依赖及路径归一化范围见 [复核范围](../REPRODUCIBILITY.md)。

| 报告 | 实验范围 |
| --- | --- |
| [full-validation.md](full-validation.md) | 2026-10-05 最新全规则八阶段实际运行 |
| [nontraining-research.md](nontraining-research.md) | 有限语义、引导、反馈、几何和密度研究 |
| [fixed-comparison.md](fixed-comparison.md) | 14 任务、三提示、五组固定候选对照 |
| [ihp-ablation.md](ihp-ablation.md) | 2026-10-04 首轮 IHP 7 项固定消融 |
| [repair-review.md](repair-review.md) | 2026-10-05 既有候选上的定向修复核对 |

`full-validation-summary.json` 是最新全规则报告对应的结构化摘录。`metrics/` 按实验分类保留全部汇总组别，包含缺失和失败，不只保留通过项。

补充附件中同名 CSV 与仓库表格一致。部分报告提到的逐槽 JSON 随补充附件发布；完整物理报告、原始响应和旧封存依赖不随该附件提供。
