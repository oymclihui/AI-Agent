"""Agent Evolution 阶段四 L4：评估体系与持续进化闭环。

- categories: 问题类目分类器（弱项分布 / 主动学习缺口共用）
- builder:    回归测试集构建（golden 查询 + 正例示例 + 人工补充）
- runner:     回归评估执行（SQL 成功率 / 结果一致率 / LLM judge / 图表匹配）
- judge:      LLM-as-judge 答案质量评分（走 ModelRouter 统一网关）
- gaps:       主动学习：识别未覆盖问题类目，推荐补问方向
- evolution:  每周进化闭环：蒸馏 → 候选版本 → 回归评估 → 达标晋升
数据真实性红线：考题全部来自真实交互（golden/正例/人工），签名基线取自真实轨迹，禁止合成。
"""
