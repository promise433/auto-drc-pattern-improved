# 定向修复与固定候选核对（2026-10-05）

工程核对涵盖 SKY 保护、工艺隔离、IHP 支持、统一流程和独立验证与对照消融，范围限定于固定环境与已支持规则。
模型独立质量与任意未知规则能力尚未由这些工程检查证明。本报告记录历史定向修复，选定逐槽观察随补充附件提供，完整物理归档未随精简包分发。

本轮279测试；3914历史原始响应与提示保持；两工艺三偏移模板保持；显式旧修复策略保持。
新增模型调用0；定向官方DRC 4/60图、6.99/1800秒。
默认BAD策略在两条已验证分支使用20nm构造；变化图独立核对，其他剩余命中照实保留。

| 候选批次 | 工艺 | 方案 | 有效目标对 | 有其他命中的槽 |
| --- | --- | --- | --- | --- |
| semantic_matrix01 | sky130 | template | 12/12 | 17 |
| semantic_matrix01 | sky130 | raw_model | 0/12 | 10 |
| semantic_matrix01 | sky130 | hybrid | 12/12 | 16 |
| semantic_matrix01 | sky130 | no_repair | 0/12 | 10 |
| semantic_matrix01 | sky130 | no_fallback | 12/12 | 16 |
| semantic_matrix01 | ihp_sg13g2 | template | 12/12 | 3 |
| semantic_matrix01 | ihp_sg13g2 | raw_model | 0/12 | 3 |
| semantic_matrix01 | ihp_sg13g2 | hybrid | 12/12 | 3 |
| semantic_matrix01 | ihp_sg13g2 | no_repair | 0/12 | 3 |
| semantic_matrix01 | ihp_sg13g2 | no_fallback | 12/12 | 3 |
| tiny_matrix01 | sky130 | template | 12/12 | 17 |
| tiny_matrix01 | sky130 | raw_model | 0/12 | 0 |
| tiny_matrix01 | sky130 | hybrid | 12/12 | 17 |
| tiny_matrix01 | sky130 | no_repair | 12/12 | 17 |
| tiny_matrix01 | sky130 | no_fallback | 0/12 | 0 |
| tiny_matrix01 | ihp_sg13g2 | template | 12/12 | 3 |
| tiny_matrix01 | ihp_sg13g2 | raw_model | 0/12 | 0 |
| tiny_matrix01 | ihp_sg13g2 | hybrid | 12/12 | 3 |
| tiny_matrix01 | ihp_sg13g2 | no_repair | 12/12 | 3 |
| tiny_matrix01 | ihp_sg13g2 | no_fallback | 0/12 | 0 |
| semantic_assist01 | sky130 | template | 12/12 | 17 |
| semantic_assist01 | sky130 | raw_model | 0/12 | 35 |
| semantic_assist01 | sky130 | hybrid | 12/12 | 16 |
| semantic_assist01 | sky130 | no_repair | 0/12 | 35 |
| semantic_assist01 | sky130 | no_fallback | 12/12 | 16 |
| semantic_assist01 | ihp_sg13g2 | template | 12/12 | 3 |
| semantic_assist01 | ihp_sg13g2 | raw_model | 0/12 | 24 |
| semantic_assist01 | ihp_sg13g2 | hybrid | 12/12 | 3 |
| semantic_assist01 | ihp_sg13g2 | no_repair | 0/12 | 24 |
| semantic_assist01 | ihp_sg13g2 | no_fallback | 12/12 | 3 |
| unprimed02 | sky130 | template | 12/12 | 17 |
| unprimed02 | sky130 | raw_model | 0/12 | 8 |
| unprimed02 | sky130 | hybrid | 12/12 | 16 |
| unprimed02 | sky130 | no_repair | 0/12 | 8 |
| unprimed02 | sky130 | no_fallback | 12/12 | 16 |
| unprimed02 | ihp_sg13g2 | template | 12/12 | 3 |
| unprimed02 | ihp_sg13g2 | raw_model | 0/12 | 2 |
| unprimed02 | ihp_sg13g2 | hybrid | 12/12 | 3 |
| unprimed02 | ihp_sg13g2 | no_repair | 0/12 | 2 |
| unprimed02 | ihp_sg13g2 | no_fallback | 12/12 | 3 |

CASES.csv逐图列出来源、解析后是否有图、几何、必要输入、分支、目标及其他命中；OBSERVATIONS.json保留完整图形及输入数量。
此历史修复核对的IHP模型证据沿用旧完整推理＋全部原始续写回放＋7项补证；组合功能不代表原生模型质量同等。后续最新全规则真实推理验收另见 full-validation.md，不能混淆两次检查。
本轮重放同一批旧候选，不重新采样，不能拿它当最新模型推理成绩。
固定候选对照仍保留1440槽与所有失败。source计数描述最终来源，不当因果贡献。
FIXED_MODEL_COSTS.json记录原候选采样调用、响应错误与耗时；五方案共用候选，不能把共享成本当各方案独立在线成本。
