# 环境记录

历史验证运行在 WSL Ubuntu、Python 3.12.3、固定 KLayout 0.30.7 上，采用现有 Qwen3 环境；模型为本地 TinyLlama-1.1B-Chat-v1.0 和 Qwen3-1.7B。独立 TinyLlama 环境也保留，但两套环境不能任意互换。

发布时读取的 Qwen3 环境主要版本：

| 依赖 | 版本 |
| --- | --- |
| torch / torchvision / torchaudio | 2.5.1+cu124 / 0.20.1+cu124 / 2.5.1+cu124 |
| transformers | 4.55.4 |
| datasets / peft / accelerate / trl | 3.1.0 / 0.13.2 / 1.1.1 / 0.12.1 |
| sentencepiece / safetensors | 0.2.0 / 0.4.5 |
| numpy / pandas / pyarrow / scipy | 1.26.4 / 2.2.3 / 18.1.0 / 1.14.1 |

`requirements.txt` 沿用上游 CPU 基线，其中 PyTorch 为 CPU 构建，transformers 为 4.46.3。它不是最新 GPU/Qwen3 验证环境的锁文件，不能把安装该文件等同于复现上述模型成绩。

发布验证使用既有解释器与依赖，没有安装、升级或自动下载。运行时模块从本发布目录的 `autodrc/` 导入，依赖从现有环境的 `lib/python3.12/site-packages/` 导入；具体参数和检查结果见 RELEASE_VALIDATION.md。

`PYTHONHASHSEED=0` 控制 Python 哈希种子，不代替模型种子。历史全规则模型根种子为 17；有限研究还登记了 31、47 及部分批次的 61。CUDA 确定性警告、冷/热调用、加载时间与成本口径应分别解读，不承诺 GPU 逐字确定。

官方规则脚本身份、调用参数和历史哈希见补充结果附件；不同 PDK 修订、模型权重、依赖或引擎可能改变结果。官方 PDK 与模型须另行按其许可获取，发布包不自动准备这些依赖。
