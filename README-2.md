# Auto DRC Pattern 后续工作方案

这份文档基于 `plan.docx` 的原始研究目标，并结合当前仓库的真实进展，给出一份**适合继续推进、也适合交给别人接手执行**的后续工作方案。

它不是重复 `README.md`，而是回答下面三个问题：

1. 这个项目接下来最值得做什么？
2. 应该按什么顺序做，才是靠谱的？
3. 每一阶段做到什么程度，才算真正完成？

---

## 1. 当前真实基线

在继续做新工作之前，必须先明确当前已经完成到哪里。

### 1.1 已经完成的核心结果

当前项目已经在 `SKY130A` runset 的 `.output(...)` 规则口径下，实现：

- `total_rules = 279`
- `supported_rules = 279`
- `covered_rules (strict) = 279`
- `covered_rules_relaxed = 279`
- `unique_rule_ids_covered = 261 / 261`

推荐作为基线查看的文件：

- `artifacts/repro_after_cleanup_20260308/coverage_summary.json`
- `artifacts/runset_coverage_llm_full_fresh_20260308_coldstart_verify_v2/coverage_summary.json`

### 1.2 当前系统的真实形态

当前系统不是一个“纯模板系统”，也不是一个“纯 LLM 端到端系统”。

它的真实结构是：

- runset 规则抽取
- runset 语义增强
- LLM 候选几何生成
- policy 评分 / repair / fallback
- KLayout 转 GDS
- KLayout DRC 闭环验证
- 批量 benchmark 与结果汇总

所以当前成果应被定义为：

> 一个已经完成 strict 全覆盖的 **LLM + 规则工程 + DRC 闭环系统**。

### 1.3 当前最重要的事实

如果后续要继续推进研究，最重要的不是“继续把 strict 从 279 提到更高”，因为目前已经没有更高可提。

当前真正要解决的问题，已经从“补覆盖”变成了下面四类：

1. **固化现有成果，防止回退**
2. **弄清楚系统为什么能成功，以及 LLM 到底贡献了多少**
3. **把 `plan.docx` 中提到的训练路线真正做实**
4. **把项目做成别人能接手、能复现、能继续扩展的研究平台**

---

## 2. 与 `plan.docx` 的对齐关系

`plan.docx` 的核心路线是：

1. `LPL` 表示法
2. 三阶段训练策略
   - Rule-to-Runset 预训练
   - Instruction Tuning
   - 验证驱动的数据增强
3. 判别器引导解码
4. 泛化与鲁棒性
5. 轻量化与更复杂几何扩展

### 2.1 当前已经较好落地的部分

这些部分已经具备明确实现：

- `LPL` 表示与合法性检查
- `Rule-to-Runset` 抽取
- `Instruction` / `Feedback` 数据集构建
- `closed_loop` DRC 验证
- `runset_coverage` 全量 benchmark
- `corner_mining` / `discriminator` 的基础框架
- LoRA / Q-LoRA 训练入口

### 2.2 当前还没有完全做实的部分

这些部分是接下来最值得推进的：

- 把三阶段训练真正跑成闭环收益，而不仅仅是“有入口、有脚本”
- 定量拆分 `LLM`、`template`、`repair`、`fallback` 各自的贡献
- 做更强模型的系统 A/B，而不是只停留在 TinyLlama 基线
- 把判别器从“后验打分 / 扫参”推进到更强的在线引导生成
- 把泛化范围从当前有限集合扩展到更多未知规则
- 把几何能力从主要曼哈顿场景扩展到更复杂约束

### 2.3 因此，后续工作的正确方向

最靠谱的路线不是盲目继续改生成逻辑，而是：

> 先固化基线与可复现性，再做归因，再做模型训练与泛化扩展。

这是因为：

- 当前 strict `279 / 279` 很强，但如果没有归因和复现实验，科研说服力仍然不够；
- 如果现在直接大改训练或生成逻辑，很容易把现有成果搞丢；
- 先做“证明为什么成立”和“建立实验纪律”，后面的训练与扩展才有意义。

---

## 3. 后续工作总原则

在执行下面的路线图时，建议严格遵守以下原则。

### 原则 A：先保住 `279 / 279`

后续任何实验都不能破坏当前基线。

建议保留一个永久不动的回归口径：

- 默认模型：`TinyLlama`
- 默认参数：
  - `AUTO_DRC_LLM_BAD_CANDIDATES=4`
  - `AUTO_DRC_LLM_CANDIDATE_GROWTH=2`
  - `AUTO_DRC_LLM_MAX_CANDIDATES_PER_INTENT=8`
- 默认 benchmark 命令：

```bash
source .venv-gpu/bin/activate
AUTO_DRC_LLM_MODEL="models/TinyLlama-1.1B-Chat-v1.0" \
AUTO_DRC_LLM_BAD_CANDIDATES=4 \
AUTO_DRC_LLM_CANDIDATE_GROWTH=2 \
AUTO_DRC_LLM_MAX_CANDIDATES_PER_INTENT=8 \
./scripts/run_coverage_llm_gpu_fast.sh \
  --out-dir artifacts/regression_full_baseline \
  --initial-delta-nm 100 \
  --max-iters 3
```

以后任何大改动，最终都要回到这个口径上复验。

### 原则 B：先做可解释，再做更复杂

目前系统虽然强，但存在一个天然问题：

- 外人会问：这到底是 LLM 自己学会了，还是模板 / repair / fallback 把结果托起来了？

所以后续必须补“归因实验”。

### 原则 C：先补实验纪律，再追求更多功能

优先级顺序应该是：

1. 可复现
2. 可归因
3. 可比较
4. 可扩展

而不是反过来。

---

## 4. 路线图总览

推荐分成 **六个阶段** 推进：

1. **阶段 0：固化基线与回归纪律**
2. **阶段 1：做系统归因与消融实验**
3. **阶段 2：推进更强模型 A/B 测试**
4. **阶段 3：真正做实三阶段训练路线**
5. **阶段 4：扩展泛化、边界案例与更复杂几何**
6. **阶段 5：把项目打磨成长期维护平台**

下面逐阶段展开。

---

## 5. 阶段 0：固化基线与回归纪律

这是最优先阶段。

### 5.1 目标

把当前 `279 / 279 strict` 变成一个真正可回归、可比较、可长期维护的稳定基线。

### 5.2 为什么先做这个

如果不先固化基线，后面的训练、A/B、泛化实验都会失去参照物。

### 5.3 具体工作

#### 任务 0-1：建立“官方基线配置”

明确一组官方默认配置：

- 模型
- 候选数
- candidate growth
- max iters
- initial delta
- runset 路径约定

建议把这套配置写进：

- `README.md`
- `README-2.md`
- 单独的 baseline JSON 或 shell 配置文件

#### 任务 0-2：建立回归 benchmark 目录规范

建议统一命名：

- `artifacts/regression_full_baseline_*`
- `artifacts/ablation_*`
- `artifacts/model_compare_*`
- `artifacts/training_eval_*`

这样以后结果目录不会再次失控。

#### 任务 0-3：建立最小回归集

除了全量 `279` 规则，还建议维护一个**小型快速回归集**，例如：

- 10 条代表性规则
- 覆盖 `min_width / min_spacing / via_enclosure / forbidden_angle / offgrid / must_interact / context-sensitive` 等类型

目标是：

- 日常修改先跑小集；
- 重要改动再跑全量。

#### 任务 0-4：记录 provenance

当前系统是混合式的，所以必须给每条规则补 provenance 信息，例如：

- 最终 GOOD / BAD / ILLEGAL 是来自 LLM 原始候选，还是 repair 后结果？
- 是否发生 template fallback？
- 候选数最终加到了多少？
- 是第几轮迭代收敛的？

这是后续做归因实验的前置条件。

### 5.4 阶段完成标准

满足以下条件，才算阶段 0 完成：

- 有一套明确的官方基线命令
- 有一个快速回归子集
- 有一份回归目录规范
- 每条规则的结果都有 provenance 信息
- 基线全量复验仍为 `279 / 279`

---

## 6. 阶段 1：做系统归因与消融实验

这是当前最有研究价值的一步。

### 6.1 目标

回答下面这些关键问题：

1. `LLM` 本身贡献了多少？
2. `repair` 和 `fallback` 对最终 `279 / 279` 的贡献有多大？
3. runset 语义增强到底提升了多少？
4. feedback boost / candidate growth 的边际收益是多少？

### 6.2 为什么这个阶段关键

如果没有这些结果，项目虽然能跑出强数字，但别人会很难判断：

- 到底是模型能力强，还是规则工程堆出来的；
- 哪些模块是必须的，哪些模块只是锦上添花；
- 下一步最值得优化的是模型还是工程。

### 6.3 推荐的消融实验矩阵

至少做下面几组：

#### 实验组 A：模板 vs LLM

- `template` only
- `llm` + no repair
- `llm` + repair
- `llm` + repair + fallback（当前最强配置）

#### 实验组 B：语义增强消融

- 只用原始 description
- description + expression
- description + expression + context
- description + expression + context + upstream chain（当前完整语义）

#### 实验组 C：候选策略消融

- 固定 1 个候选
- 固定 2 / 4 个候选
- 开 / 关 `candidate_growth`
- 开 / 关 `feedback_boost`

#### 实验组 D：strict 来源归因

统计下面这些比例：

- strict covered 中有多少是 LLM 原生成功
- 有多少依赖 repair
- 有多少依赖 template fallback
- 哪些 rule family 对 fallback 依赖最重

### 6.4 产出形式

建议产出：

- 一份总表：`artifacts/ablation_summary.json`
- 一份可读 Markdown：`artifacts/ablation_report.md`
- 每个实验组单独目录

### 6.5 阶段完成标准

满足以下条件才算完成：

- 能清楚回答“LLM 在系统中的真实贡献”
- 能按 rule family 看出依赖 repair / fallback 的分布
- 能用数据支撑后续是否值得继续训练模型

---

## 7. 阶段 2：推进更强模型 A/B 测试

这一步对应 `plan.docx` 中“尝试更强或更高效模型”的方向。

### 7.1 目标

验证在当前工程框架不变的前提下，更强模型是否能：

- 减少 repair / fallback 依赖
- 提高原生 strict 命中率
- 减少迭代轮数
- 生成更简洁、几何更自然的 case

### 7.2 建议测试的模型路线

按性价比分层：

#### 第一层：轻量开源模型

- `TinyLlama-1.1B-Chat`
- `Qwen2.5-3B-Instruct`

#### 第二层：中等规模模型

- `Qwen2.5-7B-Instruct`
- 其他 7B 左右 instruction 模型

#### 第三层：高性能参考模型（如资源允许）

- 更强 14B / 32B 级开源模型

### 7.3 推荐指标

除了最终 strict 覆盖率，还应记录：

- 原生 LLM 通过率
- repair 比例
- fallback 比例
- 平均迭代轮数
- 平均候选数
- 推理耗时
- GPU 占用

### 7.4 推荐执行顺序

不要一开始就全量跑大模型。

建议顺序：

1. 先跑小型回归子集
2. 再跑 50 条代表规则
3. 通过后再跑全量 279

### 7.5 阶段完成标准

至少获得一组明确结论：

- 哪个模型在“strict 质量 / 成本 / 稳定性”三者之间最平衡
- 是否存在比 TinyLlama 更值得作为新默认基线的模型

---

## 8. 阶段 3：真正做实三阶段训练路线

这是最直接对应 `plan.docx` 的核心科研任务。

### 8.1 目标

把当前“有训练脚本”升级为“训练确实带来 measurable gain”。

### 8.2 当前问题

目前项目已经有：

- `runset_corpus`
- `instruction_dataset`
- `feedback` 数据构建
- `train_sft.py`
- `training_recipes.py`

但还没有形成一个完整的、被严格证明有效的训练闭环。

### 8.3 推荐训练路线

#### 子阶段 3-1：Rule-to-Runset 预训练验证

目标：

- 验证预训练是否能提升模型对 rule text / runset expression 的理解

建议做法：

- 使用 `runset_corpus` 导出的数据训练一个小模型或 adapter
- 评估其对 rule_type / layer / threshold 抽取的准确率
- 比较训练前后在 `runset_coverage` 小回归集上的表现差异

#### 子阶段 3-2：Instruction Tuning

目标：

- 提升 `GOOD / BAD / ILLEGAL` 三种意图的原生几何生成质量

建议做法：

- 用 `instruction_dataset` 训练 adapter
- 对比训练前后的：
  - geometry_valid
  - BAD 命中率
  - GOOD 误报率
  - strict 原生成功率

#### 子阶段 3-3：Feedback Augmentation

目标：

- 把 DRC 反馈真正转化成下一轮训练收益

建议做法：

- 从 `iteration_summary.json` 中抽失败案例
- 做专门的 reject / accept 学习数据
- 对比是否能减少 hard rules 上的 fallback 依赖

### 8.4 建议优先使用的训练模式

先从最现实的路线开始：

- LoRA
- Q-LoRA
- 小规模数据 + 小规模回归验证

先证明“有增益”，再扩大规模。

### 8.5 阶段完成标准

以下任意一条若能稳定成立，就算训练路线开始做实：

- 在相同工程配置下，训练后模型的原生 strict 成功率显著提升
- 在相同 strict 结果下，repair / fallback 比例显著下降
- 在相同结果下，平均迭代轮数或候选数显著下降

---

## 9. 阶段 4：扩展泛化、边界案例与更复杂几何

这一阶段对应 `plan.docx` 的“泛化性、鲁棒性和复杂几何扩展”。

### 9.1 目标

从“把 SKY130A 的已知 runset 跑通”推进到“对更广泛规则具备可迁移能力”。

### 9.2 子方向 A：扩展 unknown tasks

当前 unknown tasks 还比较有限，建议扩展到：

- 更多 density 类规则
- enclosure / overlap 的更多组合
- length / area / notch / slot 类规则
- 更复杂上下文过滤条件

### 9.3 子方向 B：边界案例挖掘

把当前 `corner_mining` 做得更像真正的科研实验：

- 扩大权重搜索空间
- 对 corner cases 做自动聚类
- 统计哪些 rule family 最容易出现边界不稳定
- 输出代表性 corner gallery

### 9.4 子方向 C：在线 guided decoding

当前判别器更偏后验评分。

更进一步的目标是：

- 在生成阶段就引入更强的中间筛选
- 把“候选后选优”进一步推进到“生成时约束”

这是难点，但很有研究价值。

### 9.5 子方向 D：非曼哈顿与多层复杂约束

当前主力仍是曼哈顿几何。

后续可以按这条顺序扩展：

1. 先支持更明确的多层联动规则
2. 再支持受控非曼哈顿非法 / 边界样例
3. 最后再探索更一般的复杂几何生成

### 9.6 阶段完成标准

- unknown rule 集合明显扩大
- corner mining 产出具有分析价值的报告
- 至少完成一类更复杂几何约束的实验性支持

---

## 10. 阶段 5：把项目打磨成长期维护平台

这一步是工程化收尾，但非常重要。

### 10.1 目标

让别人接手这个项目时，不需要重新猜项目结构和实验方式。

### 10.2 建议补齐的内容

#### 任务 5-1：标准实验报告模板

建议统一产出：

- 配置
- 模型
- 数据
- 指标
- 结论
- 已知风险

#### 任务 5-2：结果目录自动汇总

建议新增一个汇总脚本，把不同实验目录汇总成：

- CSV
- Markdown 表格
- 对比图

#### 任务 5-3：接手说明与发布规范

建议明确：

- 哪些目录不提交 GitHub
- 哪些结果目录保留
- 哪些文件是“官方推荐入口”
- 如何从零复现 benchmark

#### 任务 5-4：CI / 回归自动化（可选）

如果条件允许，可以考虑：

- CPU 单测上 CI
- 小回归集作为 nightly / manual regression

### 10.3 阶段完成标准

- 新接手者能在 1 天内跑通最小 smoke
- 新接手者能在 2~3 天内复现完整 benchmark
- 新接手者能看懂每类实验目录的意义

---

## 11. 推荐的执行顺序（最靠谱版本）

如果只能选一条最靠谱的执行顺序，我建议按下面来。

### 第一步：先做阶段 0

原因：

- 不先固化基线，后续所有实验都没有稳定参照

### 第二步：马上做阶段 1

原因：

- 当前最缺的不是更高数字，而是系统归因和说服力

### 第三步：再做阶段 2

原因：

- 只有知道“哪些模块最有效”，才知道换更强模型是否真的值得

### 第四步：完成阶段 3

原因：

- 三阶段训练是 `plan.docx` 的核心研究价值，但必须建立在稳定基线和归因结果上

### 第五步：再推进阶段 4

原因：

- 泛化和复杂几何扩展最容易让项目失焦，应该在主线做稳后开展

### 第六步：最后做阶段 5 的整理

原因：

- 当系统和实验框架都稳定之后，再做发布级整理最省成本

---

## 12. 接下来三周的具体执行建议

如果要立刻开始推进，我建议按“三周计划”执行。

### 第 1 周：固化基线 + 建 provenance

本周目标：

- 建官方 baseline 配置
- 建小回归集
- 给每条规则补 provenance 字段
- 再跑一次全量基线确认仍是 `279 / 279`

本周交付物：

- baseline 配置文件
- quick regression 规则集
- provenance 扩展后的 `coverage_rows.jsonl`
- 一份 regression 报告

### 第 2 周：做消融与归因

本周目标：

- 模板 / LLM / repair / fallback 消融
- 语义增强消融
- feedback boost / candidate growth 消融

本周交付物：

- `ablation_summary.json`
- `ablation_report.md`
- 一份“LLM 贡献分析”结论文档

### 第 3 周：做强模型 A/B

本周目标：

- 选 1~2 个比 TinyLlama 更强的开源模型
- 先小回归，再中等规模，再决定是否全量

本周交付物：

- 模型对比表
- 成本 / 效果 / 稳定性分析
- 是否替换默认基线模型的结论

---

## 13. 哪些工作暂时不建议优先做

为了避免项目失焦，下面这些工作不建议现在优先做。

### 不建议优先项 A：直接大规模重写生成器

原因：

- 当前已经有 `279 / 279` 基线
- 贸然大改最容易破坏成果

### 不建议优先项 B：一上来就做非曼哈顿大扩展

原因：

- 工程复杂度高
- 很容易偏离 `plan.docx` 的主线收益

### 不建议优先项 C：没有归因就直接宣布“训练有效”

原因：

- 目前最容易被质疑的正是系统中各模块的贡献边界

### 不建议优先项 D：一开始就全量跑超大模型

原因：

- 成本高
- 若没有小回归与归因框架，结论质量不高

---

## 14. 建议的成功判据

如果这个项目要继续做成一条完整研究路线，建议把成功判据设成三层。

### 第一层：工程成功

- 基线 `279 / 279` 稳定可复现
- 新接手者能跑通
- 结果目录清晰

### 第二层：科研成功

- 能量化说明 LLM 的真实贡献
- 能证明训练确实带来 measurable gain
- 能证明 stronger model 或 guided decoding 带来稳定提升

### 第三层：平台成功

- 能方便加入新模型
- 能方便加入新 rule family
- 能方便加入新评估维度
- 项目可长期维护而不是一次性实验仓库

---

## 15. 最终建议：下一步应该先做什么

如果现在只能选一件事先做，我建议：

> **先做“系统归因与消融实验”。**

原因很简单：

- 当前 `279 / 279` 已经够强；
- 现在最有价值的不是继续追数字，而是回答“为什么这套系统能成功”；
- 只有先回答这个问题，后续训练、模型升级、复杂几何扩展才不会盲目。

因此，最靠谱的优先级排序是：

1. 固化基线
2. 做归因 / 消融
3. 做更强模型 A/B
4. 做三阶段训练闭环
5. 做泛化和复杂几何扩展
6. 做长期维护平台化整理

---

## 16. 给接手者的简短版本

如果你是下一位接手这个项目的人，最短建议如下：

- 不要先乱改生成逻辑
- 先保住当前 `279 / 279 strict` 基线
- 先补 provenance 和消融实验
- 先搞清楚 LLM、repair、fallback 各自贡献
- 再决定是优先做更强模型，还是优先做训练闭环

这是当前阶段最稳、最合理、最有科研价值的推进方式。
