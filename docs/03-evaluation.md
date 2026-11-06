# 评估

58 项 Python 测试覆盖基础、边缘、困难和 HTTP；22 项真实 Chrome 交互检查覆盖前后端、续跑、重复、导出、刷新、手机布局。详细结果为 [tests/report.json](../examples/tests/report.json)、[逐项测试输出](../examples/tests/unittest.txt)、[browser/report.json](../examples/browser/report.json)。最终证据汇总通过 `python -m scripts.verify_evidence` 从实际输出重新核查，见 [acceptance.json](../examples/acceptance.json)。

## 必验映射与实际结果

| 验收点 | 实际结果与证据 | 边界 |
| --- | --- | --- |
| 正常完成 | [离线 normal](../examples/mock/normal/)、[真实网页 normal](../examples/browser-real/) | 预算 20、费用 12；网页由真实 Qwen 逐步决策，本地合成工具 |
| 缺预算或截止 | [missing 输入/输出/空 Trace](../examples/real/missing/)，Python 分别测试单独缺预算、缺截止 | 直接 needs_information、0 费用、0 模型动作；不把这条守卫路径当成真实决策证据 |
| 预算超限重规划 | [真实 reference](../examples/real/reference/) 第 2 步估算 12，第 3 步改 basic，第 4 步估算 8，第 7 步保存 | 8 个动作；工具实际计算预算缺口，模型选择替代，执行前守卫重算 |
| 无可行方案 | [真实 over_budget](../examples/real/over_budget/) 最终 infeasible，0 费用，最小缺口 1 | 模型 6 步后停止；严格停止不收费。时间不足另有 [mock/deadline](../examples/mock/deadline/) |
| 工具失败并保留成果 | [真实修复后 tool_failure](../examples/real-tool-retest/tool_failure/) premium 脚本失败 → basic → 保存，费用 8 | 10 步；模型额外调用一次检索，返回 existing 且收费 0。原失败脚本状态仍 failed |
| 重复执行 | [reference 第 2 次](../examples/real/reference/run-2-output.json) 同方案 ID，0 新模型动作，事件完全一致 | 同输入、同目录、同 request_id；不同输入同 ID 拒绝 |
| 失败步骤续跑（加分） | [mock/resume](../examples/mock/resume/) 失败费用 2 → 新 Agent/Store 续跑后总费 8；[mock/save_failure](../examples/mock/save_failure/) 6 → 8 | `test_true_subprocess_failure_resume` 额外实际启动两次 CLI 子进程，确认持久化；不将其标成真实模型续跑 |

离线 8 类场景、11 次运行记录；每类包含原始输入目录、真实输出、每步 Trace 和执行时间/保存份数 meta。真实独立路径包括预算观察后的替代与工具失败后的替代；正常真实网页路径另行留存。所有素材与工具为合成实现；Qwen 负责实际动作选择。

## 未掩盖的失败与修复

1. [real-initial-failure](../examples/real-initial-failure/)：首轮将完整产物重复加入模型上下文，在脚本生成后模型 HTTP 超时。实际花费 6、未保存、保留成功检索和脚本。将传入模型的内容缩为最新状态与最近两条观察摘要，完整产物和 Trace 仍持久保存；单次请求等待从 45 秒调整为 90 秒。上下文过长是优化假设，单个 TimeoutError 不能独立证明唯一根因。
2. [real-compact-attempt](../examples/real-compact-attempt/)：压缩后的运行完成，但模型直接选 basic，且保存后重复调用保存两次。唯一键与工具缓存防重复收费；随后明确初始提案评估、当前状态优先和结束动作。保留原记录，不把它作为“12→8”证据。
3. [real/tool_failure](../examples/real/tool_failure/)：首轮模型正确切换 basic，却反复向无参数脚本工具传 `package`。工具拒绝并保留成功检索，16 步后 budget_exhausted、费用 2、无保存。修复为错误观察明确返回 `expected_arguments: {}` 与解释，并补充提示词；[real-tool-retest](../examples/real-tool-retest/acceptance.json) 复测 10 步完成、费用 8。原 `examples/real/acceptance.json` 仍为 false，表示这次历史整组运行确有失败；最终汇总显式引用复测，不覆盖历史结论。
4. [tests-before-http-fix](../examples/tests-before-http-fix/)：一次 Windows HTTP 403 测试出现连接中断，单独复测未再出现。为避免关闭连接时未读取 POST 正文造成重置，服务改为先限长读取正文，再判断 Host/Origin/会话，未改变拒绝规则。后续全量 58 项通过。历史栈路径做占位脱敏，异常类型与测试结果保持原样。

## 效果边界

小模型可能重复缓存调用、错误参数、过早停止或达到上限。工具保护约束和状态，但不保证每次都找出最优计划。本机 CPU 推理需要数分钟，时间预算紧时有可能因真实延迟而不可行。

样本没有测量内容创意质量、生产素材检索召回或真实服务计费。业务工具是允许的本地合成工具，模型真实参与计划调整；不得把脚本模板称为外部大模型内容生产。离线测试和真实样例分别记录，当前结果不能推广为大规模生产成功率。

CI 验证 Python 3.10/3.12、离线场景、Chromium 交互；没有在 GitHub runner 上运行真实 Qwen。网页运行记录最多内存 100 条，重启后 Trace 需靠导出留存；业务步骤、账本和保存方案持续存在 SQLite。
