# 有限非训练研究结果

本报告记录 2026-10-05 完成的有限非训练研究。实验使用固定的两个本地模型、两套 PDK 和 KLayout 0.30.7，未进行模型训练。报告中的本轮和当前均指该历史研究；部分逐槽数据随补充附件提供，完整原始响应与物理归档未随精简包发布。
工程与研究流程完成不等于原生生成质量、泛化收益或工业完整性全部达标；以下表格保留负结果、原分母、输入/分支和其他命中。

累计真实模型1380/2400调用，逐调用耗时6097.10/21600秒；官方物理703/2400图、1535.88/10800秒（含失败探针）。
主任务24项，12 known/12 holdout；保留任务只指本评测划分，不表示预训练未见过。

## 实际调用与解析

| 实验 | 实际调用 | 严格返回 | 响应错误 | 逐调用秒 | 新token |
| --- | --- | --- | --- | --- | --- |
| model_preflight01 | 9 | 0 | 9 | 46.20 | 802 |
| controlled01 | 18 | 0 | 18 | 626.87 | 12229 |
| semantic_matrix01 | 252 | 252 | 0 | 542.25 | 9755 |
| tiny_matrix01 | 72 | 0 | 72 | 776.79 | 22111 |
| semantic_assist01 | 288 | 288 | 0 | 513.15 | 9148 |
| reasoning_preflight01 | 6 | 4 | 2 | 489.01 | 9482 |
| reasoning_preflight02 | 6 | 5 | 1 | 478.40 | 9198 |
| guided01 | 288 | 288 | 0 | 1696.04 | 42315 |
| unprimed02 | 72 | 72 | 0 | 174.88 | 3377 |
| adaptive02 | 369 | 351 | 18 | 753.50 | 14881 |

严格返回表示解析得到候选，不表示几何或物理通过；JSON固定头及推理剥离范围分别在逐调用元数据保留。候选池返回与自由生成分开，不用混合汇总推断原生质量。

## 五组固定候选对照

每实验固定24任务/72意图槽/24有效目标对分母，按工艺各12任务。只用该实验seed17，同一选择先计算一次，再独立改变修复和回退开关；包含缺失槽。四个模型组共享同一批调用，不能重复计模型成本。

| 实验 | 工艺 | 方案 | 有图/36 | GOOD/12 | BAD/12 | 有效对/12 | ILLEGAL拒绝/12 | 其他命中槽 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| semantic_matrix01 | sky130 | template | 36 | 12 | 12 | 12 | 12 | 17 |
| semantic_matrix01 | sky130 | raw_model | 36 | 0 | 2 | 0 | 11 | 10 |
| semantic_matrix01 | sky130 | hybrid | 36 | 12 | 12 | 12 | 12 | 17 |
| semantic_matrix01 | sky130 | no_repair | 36 | 0 | 2 | 0 | 11 | 10 |
| semantic_matrix01 | sky130 | no_fallback | 36 | 12 | 12 | 12 | 12 | 17 |
| semantic_matrix01 | ihp_sg13g2 | template | 36 | 12 | 12 | 12 | 12 | 3 |
| semantic_matrix01 | ihp_sg13g2 | raw_model | 36 | 0 | 1 | 0 | 11 | 3 |
| semantic_matrix01 | ihp_sg13g2 | hybrid | 36 | 12 | 12 | 12 | 12 | 3 |
| semantic_matrix01 | ihp_sg13g2 | no_repair | 36 | 0 | 1 | 0 | 11 | 3 |
| semantic_matrix01 | ihp_sg13g2 | no_fallback | 36 | 12 | 12 | 12 | 12 | 3 |
| tiny_matrix01 | sky130 | template | 36 | 12 | 12 | 12 | 12 | 17 |
| tiny_matrix01 | sky130 | raw_model | 0 | 0 | 0 | 0 | 0 | 0 |
| tiny_matrix01 | sky130 | hybrid | 36 | 12 | 12 | 12 | 12 | 18 |
| tiny_matrix01 | sky130 | no_repair | 36 | 12 | 12 | 12 | 12 | 17 |
| tiny_matrix01 | sky130 | no_fallback | 0 | 0 | 0 | 0 | 0 | 0 |
| tiny_matrix01 | ihp_sg13g2 | template | 36 | 12 | 12 | 12 | 12 | 3 |
| tiny_matrix01 | ihp_sg13g2 | raw_model | 0 | 0 | 0 | 0 | 0 | 0 |
| tiny_matrix01 | ihp_sg13g2 | hybrid | 36 | 12 | 12 | 12 | 12 | 3 |
| tiny_matrix01 | ihp_sg13g2 | no_repair | 36 | 12 | 12 | 12 | 12 | 3 |
| tiny_matrix01 | ihp_sg13g2 | no_fallback | 0 | 0 | 0 | 0 | 0 | 0 |
| semantic_assist01 | sky130 | template | 36 | 12 | 12 | 12 | 12 | 17 |
| semantic_assist01 | sky130 | raw_model | 36 | 0 | 5 | 0 | 1 | 35 |
| semantic_assist01 | sky130 | hybrid | 36 | 12 | 12 | 12 | 12 | 17 |
| semantic_assist01 | sky130 | no_repair | 36 | 0 | 5 | 0 | 1 | 35 |
| semantic_assist01 | sky130 | no_fallback | 36 | 12 | 12 | 12 | 12 | 17 |
| semantic_assist01 | ihp_sg13g2 | template | 36 | 12 | 12 | 12 | 12 | 3 |
| semantic_assist01 | ihp_sg13g2 | raw_model | 36 | 0 | 3 | 0 | 0 | 24 |
| semantic_assist01 | ihp_sg13g2 | hybrid | 36 | 12 | 12 | 12 | 12 | 3 |
| semantic_assist01 | ihp_sg13g2 | no_repair | 36 | 0 | 3 | 0 | 0 | 24 |
| semantic_assist01 | ihp_sg13g2 | no_fallback | 36 | 12 | 12 | 12 | 12 | 3 |
| unprimed02 | sky130 | template | 36 | 12 | 12 | 12 | 12 | 17 |
| unprimed02 | sky130 | raw_model | 36 | 0 | 2 | 0 | 12 | 8 |
| unprimed02 | sky130 | hybrid | 36 | 12 | 12 | 12 | 12 | 17 |
| unprimed02 | sky130 | no_repair | 36 | 0 | 2 | 0 | 12 | 8 |
| unprimed02 | sky130 | no_fallback | 36 | 12 | 12 | 12 | 12 | 17 |
| unprimed02 | ihp_sg13g2 | template | 36 | 12 | 12 | 12 | 12 | 3 |
| unprimed02 | ihp_sg13g2 | raw_model | 36 | 0 | 1 | 0 | 10 | 2 |
| unprimed02 | ihp_sg13g2 | hybrid | 36 | 12 | 12 | 12 | 12 | 3 |
| unprimed02 | ihp_sg13g2 | no_repair | 36 | 0 | 1 | 0 | 10 | 2 |
| unprimed02 | ihp_sg13g2 | no_fallback | 36 | 12 | 12 | 12 | 12 | 3 |

混合与纯模板11处逐槽非目标命中差异已归因于既有SKY修复默认60nm偏移（模板20nm），详见OTHER_HIT_DIFFERENCES.json：四批via2.5 BAD载体位移使包围65→25nm，新增via2.4=2；四批via.4a BAD包围35→1nm，Metal1边界299nm离5nm网格，新增m1_OFFGRID=3。三个Qwen批次Metal2 GOOD高度160→200nm、面积64000→80000nm²，消除m2.6=1。增减可抵消汇总槽数，必须逐图比较；这些图自身目标仍通过，不能称全局DRC清洁或将已有修复行为当作本轮新增生产退化。

## 自由模型与语义消融

semantic_matrix01使用四层语义（描述、表达式、上下文、完整契约）及无坐标JSON固定头；known每profile36调用，holdout完整语义108调用/三种子。TinyLlama用同24任务、seed17、同768token上限与固定头；unprimed02复制原语义矩阵源码，保持同提示，只取消固定头。unprimed01因启动器误导入新模块失败于加载阶段（0模型调用）；adaptive01受前置门禁停止（0模型调用），原失败保留，新目录仅补未执行项。
semantic_assist01新增官方纳米阈值/必要输入事实辅助，24任务×四种子×三意图=288调用，无模板坐标。它不是原始无辅助输出；额外seed61在调用前登记。
两轮推理探测只在m1.1/NW.a/Rsil.f的GOOD/BAD上各6调用、2048token；完整think结束后的最终JSON严格解析，推理原文/截断保持。第二轮修正明确的意图占位符歧义，未据此推广全量模型质量。
RAW_METRICS.csv分别报告strict/permissive、known/holdout、工艺、语义深度。宽松解析含截取/隐式转换，只做诊断；缺失不是非法拒绝成功。

| 实验 | 模型 | 语义 | 划分 | 工艺 | 严格有图/槽 | 有效对/任务样本 | GOOD通过 | BAD通过 | 非法拒绝 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| semantic_matrix01 | Qwen3-1.7B | description | known | sky130 | 18/18 | 0/6 | 0 | 0 | 5 |
| semantic_matrix01 | Qwen3-1.7B | expression | known | sky130 | 18/18 | 0/6 | 0 | 1 | 6 |
| semantic_matrix01 | Qwen3-1.7B | context | known | sky130 | 18/18 | 0/6 | 0 | 1 | 6 |
| semantic_matrix01 | Qwen3-1.7B | full | known | sky130 | 18/18 | 0/6 | 0 | 1 | 6 |
| semantic_matrix01 | Qwen3-1.7B | full | holdout | sky130 | 54/54 | 0/18 | 0 | 3 | 15 |
| semantic_matrix01 | Qwen3-1.7B | description | known | ihp_sg13g2 | 18/18 | 0/6 | 0 | 0 | 5 |
| semantic_matrix01 | Qwen3-1.7B | expression | known | ihp_sg13g2 | 18/18 | 0/6 | 0 | 0 | 5 |
| semantic_matrix01 | Qwen3-1.7B | context | known | ihp_sg13g2 | 18/18 | 0/6 | 0 | 0 | 4 |
| semantic_matrix01 | Qwen3-1.7B | full | known | ihp_sg13g2 | 18/18 | 0/6 | 0 | 0 | 6 |
| semantic_matrix01 | Qwen3-1.7B | full | holdout | ihp_sg13g2 | 54/54 | 0/18 | 0 | 3 | 15 |
| tiny_matrix01 | TinyLlama-1.1B-Chat-v1.0 | full | known | sky130 | 0/18 | 0/6 | 0 | 0 | 0 |
| tiny_matrix01 | TinyLlama-1.1B-Chat-v1.0 | full | holdout | sky130 | 0/18 | 0/6 | 0 | 0 | 0 |
| tiny_matrix01 | TinyLlama-1.1B-Chat-v1.0 | full | known | ihp_sg13g2 | 0/18 | 0/6 | 0 | 0 | 0 |
| tiny_matrix01 | TinyLlama-1.1B-Chat-v1.0 | full | holdout | ihp_sg13g2 | 0/18 | 0/6 | 0 | 0 | 0 |
| semantic_assist01 | Qwen3-1.7B | full_with_verified_nm_facts | known | sky130 | 72/72 | 0/24 | 0 | 7 | 3 |
| semantic_assist01 | Qwen3-1.7B | full_with_verified_nm_facts | holdout | sky130 | 72/72 | 0/24 | 0 | 12 | 0 |
| semantic_assist01 | Qwen3-1.7B | full_with_verified_nm_facts | known | ihp_sg13g2 | 72/72 | 0/24 | 0 | 8 | 0 |
| semantic_assist01 | Qwen3-1.7B | full_with_verified_nm_facts | holdout | ihp_sg13g2 | 72/72 | 0/24 | 0 | 4 | 1 |
| unprimed02 | Qwen3-1.7B | full | known | sky130 | 18/18 | 0/6 | 0 | 1 | 6 |
| unprimed02 | Qwen3-1.7B | full | holdout | sky130 | 18/18 | 0/6 | 0 | 1 | 6 |
| unprimed02 | Qwen3-1.7B | full | known | ihp_sg13g2 | 18/18 | 0/6 | 0 | 0 | 5 |
| unprimed02 | Qwen3-1.7B | full | holdout | ihp_sg13g2 | 18/18 | 0/6 | 0 | 1 | 5 |
| reasoning_preflight01 | Qwen3-1.7B | reasoning_preflight01 | known | sky130 | 1/2 | 0/1 | 0 | 1 | 0 |
| reasoning_preflight01 | Qwen3-1.7B | reasoning_preflight01 | known | ihp_sg13g2 | 3/4 | 0/2 | 1 | 1 | 0 |
| reasoning_preflight02 | Qwen3-1.7B | reasoning_preflight02 | known | sky130 | 1/2 | 0/1 | 0 | 0 | 0 |
| reasoning_preflight02 | Qwen3-1.7B | reasoning_preflight02 | known | ihp_sg13g2 | 4/4 | 0/2 | 1 | 1 | 0 |

## 真实在线解码与反馈

guided01实际在model.generate每token屏蔽候选池外路径，并在分叉处加入分数。24任务×三意图×两模型×strength0/8=288调用，池、种子及参数逐项配对；所有输出精确匹配已独立物理核对的完整点列/标签，因等价复用其物理证据。
候选来自模板/刚性变换与反意图挑战，分数为已物理检查的oracle。它证明有限池实时引导的接口与有限效果，不是自由坐标生成，不证明未知规则预测或模型独立质量。ILLEGAL池全部是已知非法候选，不把这部分机械成功夸大为判别收益。

| 模型 | 工艺 | strength | 有效对/12 | GOOD | BAD | 非法拒绝 |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen3-1.7B | sky130 | 0.0 | 0 | 5 | 7 | 12 |
| Qwen3-1.7B | sky130 | 8.0 | 10 | 11 | 11 | 12 |
| Qwen3-1.7B | ihp_sg13g2 | 0.0 | 0 | 3 | 8 | 12 |
| Qwen3-1.7B | ihp_sg13g2 | 8.0 | 11 | 11 | 12 | 12 |
| TinyLlama-1.1B-Chat-v1.0 | sky130 | 0.0 | 0 | 6 | 6 | 12 |
| TinyLlama-1.1B-Chat-v1.0 | sky130 | 8.0 | 12 | 12 | 12 | 12 |
| TinyLlama-1.1B-Chat-v1.0 | ihp_sg13g2 | 0.0 | 0 | 6 | 5 | 12 |
| TinyLlama-1.1B-Chat-v1.0 | ihp_sg13g2 | 8.0 | 12 | 12 | 12 | 12 |

adaptive02在8固定任务×两根种子×五方案=80个运行上，只评价BAD生成，真正逐轮调用模型并独立官方检查。每轮失败反馈只在指定方案进入下一次提示；增长1/2改变下一轮候选数，上限4，三轮/8调用硬上限。固定、仅反馈、仅增长、增长+反馈、增长2+反馈分开，实际早停与成本保留。选择器使用实际官方检查结果选择本轮最佳候选，无模板修复或回退；这不是学习得到的判别器，也不是GOOD/BAD有效目标对评价。各组调用上限相同，但增长组实际调用可能更多，成功差异不能脱离成本解释。

| 方案 | BAD成功/16 | 实际调用 | 实际轮数 |
| --- | --- | --- | --- |
| fixed | 1/16 | 46 | 46 |
| feedback | 3/16 | 44 | 44 |
| growth | 2/16 | 88 | 45 |
| growth_feedback | 4/16 | 82 | 43 |
| growth2_feedback | 4/16 | 109 | 43 |

CANDIDATE_COUNT_REPLAY.json另复用每任务/意图四次真实事实辅助候选，对比1/2/4候选的oracle最佳选择；这是固定候选重放，不当实际自适应因果实验。

## 几何、密度与保护

576不同候选逐图验证：468合法、108几何非法；三个偏移、原始/旋转/镜像与反意图挑战分组。geometry01完成532记录后测量探针类型错误，geometry02只继续44未完成候选；失败图计费，原日志保留，已完成DRC未重跑。全部合法原生点列/层/标签/报告核对，Gat.c额外25候选补选中分支计数，避免把同类别另一分支命中当成功。
DIVERSITY_CORRECTED.json对已通过合法图排除意图与闭合环起点/遍历方向造成的伪差异；另排除平移。旧geometry01/DIVERSITY.json保留为中间统计，不用旧数字夸大多样性。
官方IHP density.drc六张独立构造图：Metal1比例34/35/36%验证下限35%，59/60/61%验证上限60%；等阈值无自身违规，34%命中M1.j、61%命中M1.k。真实chip面积/比例/边界数量与原生点列通过。其他八类密度违规保留；prboundary189/0仅加入实验层表，不声称生产全密度支持或原生模型密度泛化。
272项测试、SKY279/IHP272三个偏移与原model03保持，3914旧响应/legacy提示与SKY选择策略保持。没有新全量DRC或旧全量模型重启；SKY精确278/279、IHP有效268/272及官方/引擎限制不变。IHP旧完整推理+修复后全部原始续写回放+7项补证的组合边界保持，不等于最新原生模型质量追平。
EFFICIENCY.json保留逐调用tokens、耗时、中位数、冷/热调用及可测显存峰值。自由模型第一调用包含加载；在线池预加载不含在逐调用时间中、包含在worker时间中，不能直接拿这种不同计时口径宣称倍数加速。GPU种子配对不表示逐字确定；无新机器部署或跨引擎证明。

| 实验 | 模型 | 调用 | 逐调用总秒 | 新token | 热调用中位秒 | CUDA峰值MiB |
| --- | --- | --- | --- | --- | --- | --- |
| semantic_matrix01 | Qwen3-1.7B | 252 | 542.25 | 9755 | 2.152 | 未测 |
| tiny_matrix01 | TinyLlama-1.1B-Chat-v1.0 | 72 | 776.79 | 22111 | 8.834 | 未测 |
| semantic_assist01 | Qwen3-1.7B | 288 | 513.15 | 9148 | 1.684 | 3875.8 |
| guided01 | Qwen3-1.7B | 144 | 956.95 | 19399 | 4.765 | 3591.2 |
| guided01 | TinyLlama-1.1B-Chat-v1.0 | 144 | 739.09 | 22916 | 3.513 | 2215.1 |
| unprimed02 | Qwen3-1.7B | 72 | 174.88 | 3377 | 2.311 | 3875.8 |
| adaptive02 | Qwen3-1.7B | 369 | 753.50 | 14881 | 1.957 | 3875.8 |
| reasoning_preflight01 | Qwen3-1.7B | 6 | 489.01 | 9482 | 67.664 | 3875.8 |
| reasoning_preflight02 | Qwen3-1.7B | 6 | 478.40 | 9198 | 75.479 | 3875.8 |

## 根因与结论边界

1. 格式与意图：TinyLlama严格响应失效，Qwen3虽可输出合法JSON仍反复生成单位方块；REQUESTED_INTENT歧义已修并保留前后探测，格式成功不代表理解物理阈值。
2. 有效域与数量：间距少第二对象、派生/高压输入、阵列及器件文字缺失，造成空域伪GOOD或错误BAD；新增官方输入/选中分支核对按实际表达式评价，不按说明文字猜测。
3. 原生能力与构造依赖：当前高覆盖主要靠可信模板、修复/回退或显式oracle候选池；应以自由生成的独立物理有效对评价原生质量。未执行训练，不能用模板成功替代模型学习目标。
本轮完成有限非训练工程与研究执行，正向模型质量、未知规则自主泛化、工业任意复杂约束能力未因此全部达标。失败、缺失、来源与成本保留在相应统计及原始归档中。
