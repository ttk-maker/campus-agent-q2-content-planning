# 题目2 · 内容任务规划 Agent：设计说明

交付日期：2026-11-07（Asia/Shanghai）。提交题号：2。仓库：https://github.com/ttk-maker/campus-agent-q2-content-planning。固定交付标签：`q2-submission-20261107`。配套文档：https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/docs/submission/02-delivery-and-acceptance.md 。

本文件供评审理解业务、动态决策、工程边界与实际证据。最终提交 SHA 由固定标签解析：`git rev-parse q2-submission-20261107^{commit}`；本地独立交付副本首页附最终完整 SHA。文档不把自身所属 commit 的 SHA 写入自身正文，以避免自引用改变 commit。

## 1. 用户、需求与范围

帮助运营人员在预算和截止时间内完成内容活动方案；失败时保留已成功步骤并给出未完成原因。

- 输入：主题、预算、截止时间，合成素材和工具费用/耗时目录。预算与截止时间是硬约束。
- 输出：任务计划、步骤与依赖状态、工具结果、实际费用合计、保存方案或未完成原因；失败步骤与保存状态分别显示。
- 成功标准：覆盖题目全部必须验收点，至少两条不同工具观察后的真实模型决策路径；硬约束由程序复验，工具实际失败不得虚报成功。
- 范围：CLI 与本机 HTTP/Web 工作台均可运行。业务工具使用合成资料、本地函数和SQLite；真实模型使用Ollama `qwen2.5:7b-instruct`。Mock只验证流程，不证明真实决策能力。

## 2. 动作流与模型职责

选择初始计划 → 成本/时间估算 → 模型观察超限后更换套餐或停止 → 素材检索 → 脚本生成 → 保存 → 结束；工具错误后模型重试、换方案或停止，已成功结果留存。

动作接口：`select_plan(package)`、`estimate_cost()`、`search_materials()`、`generate_script()`、`save_plan()`、`finish(outcome)`。

每轮模型输出一个动作、参数及简短决策依据；执行器校验后执行工具，将实际观察回传模型，再产生下一动作或结束。Trace保存步骤、工具参数、返回结果和后续动作，不收集模型内部思维过程。预设状态骨架限定合法动作，模型负责范围内的具体选择；最终状态以工具证据为准。

参考预算10：初始premium估算12，模型读取超额后选择basic，复估8并保存。工具失败路径中premium脚本失败后改basic，保留成功检索，最终费用8。目录有premium时先评估premium属于预设骨架，后续替代动作来自模型对观察的响应。

默认单次16个模型动作，可配置1–100；单次模型HTTP90秒，执行租约120秒；上限返回 `budget_exhausted`，已花费用与成功步骤保留。

## 3. 架构与可靠性

CLI/Web → Agent循环与模型适配器 → 确定性工具与守卫 → SQLite；工具观察返回模型，输出状态由实际持久结果构造。无需多Agent或生产Runtime。

检索成功→对应套餐脚本成功→保存；付费工具先观察估算，执行前重算硬预算与截止。费用采用整数分记账，成功产物与费用在同一事务提交；失败尝试0费但计模拟时间。工具+输入/套餐缓存成功结果，方案按request_id唯一；跨进程租约防并发。重规划保留已消费费用，不能把失败记成成功。

Python 3.10+标准库承担CLI、HTTP、模型请求与测试，SQLite承担本地事务和持久化。未使用第三方Agent框架。选择原生实现是为了使状态、授权、失败与重试边界容易检查；代价是需要自行维护协议与持久化逻辑。Node.js/Playwright仅用于浏览器自动化，不是应用启动依赖。

Web只监听本机，包含同源/Host/会话令牌与请求大小守卫；这是本机演示边界，不是生产账号认证。完整执行Trace应及时导出；网页内存任务记录有限，业务结果仍持久化。

默认费用表：检索2、premium脚本8/basic脚本4、估算0、保存2个模拟单位；高级总12、基础总8。默认耗时：检索3分钟、高级20/基础8、估算1、保存2；失败尝试0费用但1分钟。费用与耗时来自目录，执行守卫使用实际目录值，不能仅因模型声称可行就放行。

## 4. 原型与前端

[可导入Figma的动作流与痛点SVG](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/docs/prototypes/planning-flow.svg)。图稿已交付，本项目没有Figma在线文件。前端为桌面结果画布+参数侧栏，窄屏先输入后结果；显示设置即时变更主题色、明暗、字号、密度和动效，偏好按项目保存在本地浏览器。业务参数只更新预览，显式点击运行才调用Agent，已有结果不会随预览改写。设计参考Open Design Tweaks，代码按本项目业务独立实现。

[实时调参设计与验证](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/docs/11-live-tweaks.md)；[网页使用手册](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/docs/07-user-manual.md)。

## 5. 验收点与证据

| 验收点 | 实际证据 | 核对重点 |
|---|---|---|
| 正常完成 | [输入、输出与运行记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/mock/normal) | 费用12、保存成功；真实正常网页证据另见examples/browser-real/ |
| 缺预算或截止 | [输入、输出与运行记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/real/missing) | needs_information，0费用、0模型动作；属于入口守卫 |
| 预算超限后替代 | [输入、输出与运行记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/real/reference) | 估算12→选basic→估算8→保存，8动作 |
| 无可行方案 | [输入、输出与运行记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/real/over_budget) | infeasible，0实际费用，最小预算缺口1 |
| 工具失败与重规划 | [输入、输出与运行记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/real-tool-retest/tool_failure) | premium脚本失败→basic，保留检索，实际费用8 |
| 重复执行 | [输入、输出与运行记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/examples/real/reference/run-2-output.json) | 同方案ID，0新模型动作，费用事件不增加 |
| 失败续跑 | [输入、输出与运行记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/mock/resume) | 首次失败费用2；同输入同数据库重跑完成，总费用8 |
| 保存失败续跑 | [输入、输出与运行记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/mock/save_failure) | 失败时费用6，恢复后8；真实失败状态不伪装成功 |
| 困难期限冲突 | [输入、输出与运行记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/hardening/real-deadline-retest/deadline_forces_basic) | 实际观察premium超时3分钟后转basic，费用8 |

至少两条真实模型循环的直接入口：

- [预算重规划](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/examples/real/reference/run-1-trace.jsonl)
- [工具失败后重规划](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/examples/real-tool-retest/tool_failure/run-1-trace.jsonl)

证据同时保存输入、实际输出、Trace；目录中的JSON/JSONL是实际运行记录，截图只是补充。缺输入的入口守卫和Mock不计作真实模型决策证明。

## 6. 测试、失败与改进

本次交付从Git源码归档解压到独立目录，重跑全量Python测试 **70项**、离线CLI与历史证据校验；结果见 [交付前检查](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/examples/submission/preflight.json)。历史前端回归：业务22项、展示35项、实时调参38项通过；最终文档提交还将执行GitHub CI。CI只运行工程/Mock验证，不声称在runner上运行真实Qwen。

真实首轮出现超时、参数错误和重复调用已成功工具。压缩模型观察，明确工具契约，再加入JSON Schema与按持久状态开放动作。困难场景验证自定义套餐、期限迫使降级、预算精度与续跑。首轮失败、直接选basic而缺少冲突观察的诊断均保留，不冒充有效重规划证据。

原始失败：[examples/real-initial-failure/](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/real-initial-failure)、[examples/real/tool_failure/](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/real/tool_failure)、[examples/hardening/real/](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/hardening/real)、[examples/hardening/real-retest/](https://github.com/ttk-maker/campus-agent-q2-content-planning/tree/q2-submission-20261107/examples/hardening/real-retest)。最新综合证据入口：[验收结果](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/examples/acceptance.json)。历史目录里保留false报告是审计事实，不应删除，也不能仅选旧报告推断最新复测结果。

本次是交付封装，未修改后端、模型或前端运行逻辑，未再次调用模型生成整套真实结果；真实决策记录来自先前实际执行，本次程序重新核对留存证据。

## 7. 已知限制与下一步

检索、脚本生成、估算、保存均为本地合成业务工具；脚本工具的模板不冒充外部模型内容生产。模拟收费和耗时不等于真实账单；真实延迟也会影响截止可行性。生产外部服务仍需幂等键和对账。没有真实采购、投放、发布、创意质量评测或公网服务。

样本为小规模合成场景，不代表生产成功率。模型可能返回非法动作、反复尝试、超时或达到步数上限，系统须诚实报告未完成。下一步优先扩展真实资料和模型重复评估，再根据业务接入生产服务、身份权限与可观测性。

## 8. AI辅助、个人贡献和用时

用户实际贡献：提供题目、规则、验收要求，决定项目优先级、额外边缘测试和前端方向，提供参考模板。AI承担需求梳理、原型、代码、测试、实际模型试验、失败分析、文档与GitHub操作。没有把AI生成内容记为候选人独立编码，也没有虚构用户已手工验收的记录。详见 [AI使用记录](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/docs/04-ai-usage.md) 与 [复盘](https://github.com/ttk-maker/campus-agent-q2-content-planning/blob/q2-submission-20261107/docs/05-retrospective.md)。

首次交付2026-11-06 16:05–17:00，约55分钟；题二/题四共同追加困难测试20:35–21:30，约55分钟（共同投入，不重复计为各题独立时长）。 三项目共同前端精简2026-11-06 22:25–22:41约16分钟；共同Tweaks改造23:43至11-07 00:01约18分钟。实际累计已超过官方建议3小时，应按实际报告；这些是开发会话跨度，包含AI、推理与CI等待，不等于候选人个人独立工作时长。此次封装自2026-11-07 15:28开始，结束与耗时附最终交付副本。
