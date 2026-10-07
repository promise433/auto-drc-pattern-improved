# 运行说明

推荐在 Linux 或 WSL 下使用 Python 3.12。先查看 ENVIRONMENT.md；基础 JSON 生成使用标准库，不需要模型或 KLayout。已有环境应直接复用，模型实验须使用与模型相容的依赖，避免无意切换 CPU/GPU 或 TinyLlama/Qwen3 环境。

## 物理检查配置

使用固定 KLayout 0.30.7 和相应官方 PDK。以下路径是配置示例，按实际安装位置填写：

```bash
export AUTO_DRC_KLAYOUT_BIN=/path/to/klayout-0.30.7/usr/bin/klayout
export AUTO_DRC_KLAYOUT_LD_LIBRARY_PATH=/path/to/klayout-0.30.7/usr/lib/klayout
export KLAYOUT_PATH="$HOME/.klayout:/path/to/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout"
export AUTO_DRC_IHP_RUNSET=/path/to/IHP-Open-PDK/ihp-sg13g2/libs.tech/klayout/tech/drc/rule_decks/sg13g2_maximal.drc
export PYTHONHASHSEED=0
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
```

`AUTO_DRC_IHP_RUNSET` 用于可选 PDK 测试；业务覆盖入口仍须显式传入 `--runset`。SKY 官方脚本通常位于 KLayout 的 `salt/Efabless_sky130/tech/sky130/drc/sky130A_mr.drc`。

以下命令会进行有限官方 DRC，不是 README 的零物理检查示例：

```bash
python3 -B -s scripts/run_isolated.py --entry coverage \
  --run-dir artifacts/runs/ihp_one_rule -- \
  --runset "$AUTO_DRC_IHP_RUNSET" --generator template --max-rules 1 --max-iters 1
```

输出必须使用 `artifacts/runs/` 下的新目录。隔离入口会拒绝覆盖既有目录，并管理输出参数；不要在其 `--` 之后另加 `--out-dir` 或 `--out-root`。

## 模型与研究入口

模型权重必须已存在本地。模型实验在隔离入口 `--` 之前设置 `--model-path /path/to/local-model`，之后使用 `--generator llm`。离线环境变量用于防止缺失权重触发自动下载。

模型参数、候选数、修复/回退开关和种子应显式记录。`--llm-disable-repair`、`--llm-fallback auto|enabled|disabled`、提示格式及严格响应开关的语义见模块帮助；独立固定候选消融与自适应闭环是不同实验。

```bash
python3 -B -s -m autodrc.runset_coverage --help
python3 -B -s -m autodrc.closed_loop --help
python3 -B -s -m autodrc.research_compare --help
python3 -B -s -m autodrc.physical_evaluation --help
```

统一流程使用隔离入口的 `--entry pipeline`，单规则闭环用 `--entry closed-loop`。渲染使用 `scripts/render_gds_to_png.py` 和 `scripts/klayout_render_gds.rb`；转换使用 `scripts/lpl_to_gds.rb`。

`scripts/run_coverage_llm_gpu_fast.sh` 是保留的旧便利入口，可能选择旧模型、远程模型 ID 或原地配置。新实验优先使用隔离入口，不把运行旧脚本当成发布核验步骤。训练工具与配方保留，但已有成绩没有实际训练成果。

## 测试与历史工具

`python3 -B -s scripts/verify_release.py` 仅核对发布文件，不执行模型或 DRC。
`PYTHONHASHSEED=0 python3 -B -s -m unittest discover -s tests -v` 为功能回归。未配置官方 IHP 规则脚本时，一项 PDK 测试会跳过，应按实际输出记录跳过数量。

`scripts/project_quality.py` 默认复核原始迁移档案、受保护环境和旧封存；这些材料未随精简包分发，直接运行其默认复核会失败。`scripts/replay_candidates.py` 同样依赖原始 PATH_INDEX 与原始响应。附录中的归一化路径只是历史位置标签，不是可执行路径，不能直接用于重放。
