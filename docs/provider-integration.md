# 供应商适配边界

ProviderRegistry 集中注册 MarineTraffic / Flightradar24、能力和新鲜度策略。Store 和 rules 只处理标准化 Observation，规则不依赖供应商私有字段。内部创建模型必须显式指定已注册供应商；外部创建由 EnrollmentService 确定供应商。

Provider 实现 fetch(target, now) 与 normalize(payload, target)。原始响应先写 raw_records，再解析；失败携带 FetchError 证据。SDK 调用细节见 sdk-integration.md。测试替身仅在 tests 中显式注册。
