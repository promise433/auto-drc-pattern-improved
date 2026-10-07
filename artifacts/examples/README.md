# 两工艺代表图样

例子来自 2026-10-05 的全规则模板运行：SKY130A 的 `dnwell.1` 和 IHP SG13G2 的 `NW.a`。每工艺保留同一规则的 GOOD/BAD/ILLEGAL 三个 JSON；两个几何合法样本另有 GDS 和官方 DRC 报告，ILLEGAL 在转换前拒绝，没有 GDS。

GOOD/BAD 的“合法”表示数学几何合法，不表示没有其他 DRC 命中。GOOD 只要求自身规则不命中，BAD 有意触发目标规则；使用 KLayout 打开 `.lyrdb` 可查看其他类别。JSON 单位为整数纳米。

GDS 保持来源字节。JSON 与 `.lyrdb` 采用公开导出序列化，报告中的本机路径以 `/workspace` 归一化，不影响类别和违规点内容。来源与导出哈希记录在 RELEASE_METADATA.json；这些例子只用于展示，不代表模型独立生成效果或全规则覆盖证明。
