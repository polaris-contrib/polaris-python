# 集成测试 Fixture

[English](README.md)

本目录程序只用于集成验证，可以包含故障注入、兼容性检查、长时间生命周期控制或其他会
让公开示例难以理解的复杂行为。

Fixture 可以依赖 `integration/`；`examples/` 中的公开代码不得导入 Fixture，也不得
依赖 Fixture 专用环境开关。
