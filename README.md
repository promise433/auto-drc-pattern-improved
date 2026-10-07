# Auto DRC Pattern

面向 SKY130A 和 IHP SG13G2 的设计规则测试图样生成与验证工具。根据规则文本或官方规则脚本生成 GOOD、BAD、ILLEGAL 候选，支持模板、模型候选、修复与回退、GDS 转换、KLayout 检查，以及固定候选对照和有限非训练研究。

本版本基于 [zhangce410-crypto/auto-drc-pattern](https://github.com/zhangce410-crypto/auto-drc-pattern) 扩展。上游参考版本为 [`2ad91d5`](https://github.com/zhangce410-crypto/auto-drc-pattern/tree/2ad91d53138a94055f014ba3c2bf3f28f6f7cc01)。版本差异见 [CHANGELOG.md](CHANGELOG.md)，来源与许可说明见 [NOTICE.md](NOTICE.md)。

## 快速开始

在仓库根目录运行。以下命令只生成 JSON 图样，不调用模型或物理 DRC；输出目录必须是新目录。

```bash
PYTHONHASHSEED=0 python3 -B -s scripts/run_isolated.py --entry cli \
  --run-dir artifacts/runs/sky_width_example -- \
  --rule-type min_width --layer met1 --min-width-nm 140

PYTHONHASHSEED=0 python3 -B -s scripts/run_isolated.py --entry cli \
  --run-dir artifacts/runs/ihp_width_example -- \
  --rule-type min_width --layer Metal1 --min-width-nm 160 --tech-name ihp_sg13g2
```

隔离入口复制源码和配置后执行，避免覆盖率流程写回仓库层映射。运行参数、源码哈希、解释器、环境及日志写入新运行目录。

模型生成与物理验证需要另外准备本地模型、官方 PDK 和 KLayout 0.30.7。这些依赖不包含在仓库中。配置和命令见 [运行说明](docs/RUNNING.md)；历史验证环境见 [环境记录](docs/ENVIRONMENT.md)。

## 已验证结果

以下为 2026-10-05 完成的固定环境全规则实际运行，发布打包未重新进行推理、训练或物理检查。

| 运行 | 有效自身目标对 | 模型调用 / 解析错误 |
| --- | --- | --- |
| SKY 全规则模板 | 278/279 | 0/0 |
| SKY 全规则混合 | 278/279 | 1953/1388 |
| IHP 全规则模板 | 268/272 | 0/0 |
| IHP 全规则混合 | 268/272 | 1903/1650 |
| SKY 统一流程模板 / 混合 | 各 16/16 | 0/0、20/6 |
| IHP 统一流程模板 / 混合 | 各 9/9 | 0/0、42/35 |

该运行包含 3918 次真实模型调用和 3719 次官方及追加物理检查，失败成本包含在统计中。原有 279 项测试通过；后续迁移及隔离检查扩展到 283 项。发布副本的验证范围与结果记录在 [发布核验记录](docs/RELEASE_VALIDATION.md)。

五项已知限制保留固定分母：SKY `m1.4a_a` 为官方同层空减集；IHP `npn13G2.a`、`npn13G2L.a`、`npn13G2V.a` 为官方空执行区间，`CntB.g1` 为固定引擎角度限制。

GOOD 只表示自身目标规则通过，不表示没有其他违规；BAD 有意触发目标规则；ILLEGAL 为数学几何拒绝样本。混合流程通过和最终修复/回退比例不能作为模型独立成功率或因果贡献。

已执行有限非训练研究，但四批原始模型固定对照均为 0/24 有效目标对。未选原始候选没有全量物理成功率结论；未执行实际训练，未证明未知规则自主泛化、跨机器复现或跨引擎等价。早期 279/279 的兼容统计不能替代精确 278/279。

## 发布内容

| 位置 | 内容 |
| --- | --- |
| `autodrc/` | 生成、工艺契约、物理评价与研究模块 |
| `config/` | 两工艺图层映射 |
| `scripts/` | 运行、转换、渲染、训练配方及核验工具 |
| `tests/` | 业务、研究与完整性测试 |
| `data/seed_cases/` | 基础种子图样 |
| [artifacts/examples/](artifacts/examples/README.md) | 两工艺 GOOD/BAD/ILLEGAL JSON 及合法图的 GDS、DRC 报告 |
| [docs/results/](docs/results/README.md) | 日期明确的结果报告和完整组别的汇总表 |
| [MANIFEST.json](MANIFEST.json) | 发布文件的大小及 SHA-256 |

补充文件 `auto-drc-pattern-evaluation-data-20261007.zip` 供作为同版本 Release 附件发布，包含选定实验的任务、成本账本、逐槽观察和负结果。它是经过路径归一化的结果摘录，未包含所有原始响应、完整物理产物、冻结源码或历史档案，不能独立复核完整历史封存。详见 [复核范围](docs/REPRODUCIBILITY.md)。

## 核验

```bash
python3 -B -s scripts/verify_release.py
PYTHONHASHSEED=0 python3 -B -s -m unittest discover -s tests -v
```

未设置 `AUTO_DRC_IHP_RUNSET` 时，一项依赖官方 PDK 的测试会明确跳过；测试通过不等于重新执行全部模型或 DRC。`scripts/project_quality.py` 和 `scripts/replay_candidates.py` 保留历史完整性与迁移读取能力，依赖未随此精简版本分发的原始归档及迁移索引，不属于精简包的直接复现入口。
