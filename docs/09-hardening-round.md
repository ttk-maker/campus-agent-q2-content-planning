# 追加边缘与困难场景：预算、期限与恢复

本轮由用户要求追加测试及优化，从 2026-11-06 20:35（Asia/Shanghai）开始。原冻结标签 `q2-v1.0.0` 保留，当前分支继续修复。

## 修复前失败与原因

先增加 10 项测试再运行旧实现，出现 2 failures、3 errors（包含参数化子用例）。[原始失败输出](../examples/hardening/before.txt) 仅脱敏本地路径；[修复后输出](../examples/hardening/after.txt) 为 10 项全部通过。

| 场景 | 旧行为与原因 | 修复及预期 |
| --- | --- | --- |
| 预算 `7.999999999999999999999999999999` | Decimal 乘 100 先被默认精度舍入，意外变为合法 8 | 先精确比较两位小数量化值，再转换整数分；拒绝输入 |
| 预算/截止只有空格或制表符 | 缺失判定不一致，抛异常 | 统一空白缺失判定；返回待补信息，不执行付费工具 |
| 工具表为 null、套餐漏费用/时间 | KeyError/TypeError | 在读取前校验完整结构，返回明确输入错误 |
| 自定义套餐只有 economy | 真实模型提示仍要求不存在的 premium | 提示以实际目录为准，目录存在 premium 时才优先评估它 |

## 分层用例与实际证据

全量 [Python 报告](../examples/tests/report.json) 为 **70 项通过**；新增并发线程测试验证同一请求只有一个写入者，独立请求不共享故障次数，零费用工具保持账本精确。既有测试继续覆盖跨进程恢复、恰好截止、跨时区、保存事务失败和输入注入。

[8 组 Mock 实际案例](../examples/hardening/mock/report.json) 全部符合预期，每个目录保存 input.json、run-N.json（输出与 Trace）。

| 案例 | 预期与观察 |
| --- | --- |
| custom_package | 只有 economy 套餐仍可完成 |
| deadline_forces_basic | 预算充裕，但期限迫使选择更快 basic |
| blank_constraints / decimal_attack | 待补信息 / 拒绝输入 |
| one_cent_short | 差 0.01 不得付费执行 |
| save_resume | 保存失败后续跑，保留脚本，总费 8 |
| expired_resume | 保存失败后期限已过，保留成功脚本与费用 6，不保存 |
| free_tools | 零预算、全免费目录可以完成 |

本轮 [Chrome 回归](../examples/hardening/browser/report.json) **22 项通过**。使用隔离数据库，未写入用户工作台库。

## 复现

```powershell
py -3.10 -m scripts.test_report
py -3.10 -m scripts.hardening_examples --output runtime/hardening
# 本地 Ollama，真实结果另存；模型运行可能需数分钟
$env:MODEL_BASE_URL='http://localhost:11434/v1'
$env:MODEL_NAME='qwen2.5:7b-instruct'
py -3.10 -m scripts.hardening_examples --mode real --output runtime/hardening-real
```

CI 已加入离线困难案例运行。Mock 证明流程与守卫，不能证明真实模型决策；真实模型本轮结果见下方追加记录。价格和耗时仍为模拟单位，截止校验包含真实等待时间，不能把成功样例推广为所有模型和任意目录的保证。


真实模型首轮自定义套餐失败：已成功检索和生成脚本，费用 6，但重复执行已有步骤到 16 步上限，未保存。记录保留在 examples/hardening/real/custom_package/。仅修改套餐名提示不足以避免循环，因此增加基于持久状态的动作 JSON Schema：套餐名必须来自当前目录；已成功依赖不再作为当前动作；失败时仍允许重试、换套餐或停止。选择哪一替代套餐、观察估算后是否换计划依然由模型决定，业务工具再次校验预算和期限。新增两项适配器回归，覆盖自定义目录推进保存，以及预算重规划与失败停止的选择空间。此变更要求真实供应商支持 JSON Schema。


首轮真实期限场景也耗尽16步，费用6、未保存，失败记录在 examples/hardening/real/deadline_forces_basic/。原真实 report.json 保持 passed=false；复测另存 real-retest，绝不覆盖首轮失败。


第二次真实运行：custom_package 6步完成，总费8，仅1份方案，证据 examples/hardening/real-retest/custom_package/。deadline_forces_basic 虽保存成功，但直接选择basic，没有先观察到超时，新增路径断言因此保持false。为使默认高级提案可审计，目录包含premium时初始评估固定从premium开始，替代套餐及是否结束由模型依据估算选择；没有premium时仍从实际目录选。该预设起点不冒充动态重规划，动态证据必须包含工具返回deadline_gap_minutes>0后再切换与复估。期限单独复测另存 real-deadline-retest。


最终真实期限复测：8步完成。先估算premium返回deadline_gap_minutes=3，再改basic复估gap=0，检索、生成、保存，总费用8、数据库只有1份方案。证据 [最终期限路径](../examples/hardening/real-deadline-retest/deadline_forces_basic/run-1.json)。最终证据核查组合自定义套餐成功记录与该期限记录，仍保留前两轮false报告。本轮题二本地验证截至21:19，约44分钟（含与题四交替推理、调试及等待）；后续CI等待由总交付记录计入。
