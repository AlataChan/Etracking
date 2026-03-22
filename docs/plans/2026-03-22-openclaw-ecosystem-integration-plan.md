# Etracking MCP 生态集成规划

> 创建日期：2026-03-22
> 最后更新：2026-03-22（v5 实施完成）
> 状态：Phase 0 + 1 + 1.5 已实施，71/71 测试通过

---

## 一、审查结论（v3）

### 1.1 计划是否合理

结论：**方向合理，但 v2 的一期设计过于激进。**

合理之处：

- 以 MCP 而不是 OpenClaw 私有协议为中心，方向正确
- 优先做 MCP Server，再按需做 OpenClaw Skill 和 HTTP API，顺序正确
- 复用现有 `runtime/reports/<job_id>/` 报告体系，思路正确

需要修正之处：

- **不要把 MCP Tasks 作为一期前提**
- **不要让 MCP 直接绑定 `src/main.py` 的 CLI 边界**
- **不要把 `receipts://{order_id}` 当作唯一 artifact 标识**
- **不要在一期放开 `run_single` 和 `run_batch` 并发**

### 1.2 路线是否正确

结论：**大路线正确，内部落地路线需要改。**

正确的大路线：

1. MCP Server
2. OpenClaw Skill
3. HTTP API

建议修正后的内部路线：

```text
AI Agent / CLI / HTTP
        ↓
   Adapter Layer
        ↓
Application Service
        ↓
SessionManager / BatchRunner / PdfFlow / Core Models
```

也就是说：

- `CLI`、`MCP`、`HTTP` 都应该接到同一个 application service
- 不建议让 `MCP` 直接复用 `main.py` 中带有 signal handler 和 CLI 语义的函数

### 1.3 还需要哪些输入

实施前建议先明确：

1. 一期目标客户端是谁：`Claude Code`、`Cursor`、`OpenClaw`，还是多个同时支持
2. 一期是否只做本地 `stdio`，还是需要远程 `streamable-http`
3. 客户端是否必须支持“提交任务后离线轮询结果”
4. artifact 交付方式是什么：本地路径、二进制内容、还是外部存储链接
5. 运行模式是单用户本机，还是多 agent / 多进程共享同一套浏览器资源

---

## 二、背景与目标

Etracking 是一个泰国海关 E-Tracking 系统的浏览器自动化工具，核心能力是批量下载收据 PDF。

本规划的目标不是“为了接 MCP 而接 MCP”，而是：

- 在不破坏现有 CLI 的前提下，对 AI Agent 暴露稳定的调用接口
- 保持浏览器会话、凭证、PDF 下载和报告写入仍由 Etracking 核心负责
- 让后续的 OpenClaw Skill、HTTP API、监控面板都建立在同一套核心服务之上

因此，本规划以 **MCP-first, service-first** 为原则：

- **MCP-first**：面向 AI 编排优先提供 MCP Server
- **service-first**：先抽出可复用的应用服务层，再接 CLI / MCP / HTTP

---

## 三、现状与约束

### 3.1 已有基础

| 已有资产 | 位置 | 说明 |
|---------|------|------|
| CLI 入口 | `src/main.py` | 已支持 single / batch / retry-failed / resume |
| 浏览器执行核心 | `src/session_manager.py` | 当前基于 `playwright.sync_api`，是同步实现 |
| 批处理流程 | `src/workflow/batch_runner.py` | 已有失败重试、resume、skip 语义 |
| 结构化结果模型 | `src/core/models.py` | `to_dict()` 已完善 |
| 运行期路径体系 | `src/core/paths.py` | `runtime/` 下日志、session、reports、receipts 已标准化 |
| 增量状态快照 | `src/integrations/run_ledger.py` | 批处理中已持续写 `summary.json` 和 `results.jsonl` |
| 最终报告写入 | `src/integrations/report_writer.py` | 已输出 `summary.json`、`results.jsonl`、`results.csv` |
| 现有契约草图 | `src/integrations/openclaw_contract.py` | 仅是 payload/response shim，不是运行时桥接 |
| OpenClaw 集成文档 | `docs/openclaw-integration.md` | 已定义 control plane 定位 |

### 3.2 固有约束（仍然存在）

| 约束 | 说明 |
|------|------|
| 浏览器核心是同步实现 | `src/session_manager.py` 基于 `playwright.sync_api`，不是 async |
| artifact 路径不是全局唯一 ID | PDF 文件名为 `order_id_YYYYMMDD.pdf`，需通过 `job_id + order_id` 定位 |
| output dir 可配置 | 不能假定所有文件都固定在 `runtime/receipts/` |

### 3.3 已解决的缺口

| 缺口 | 解决方式 | 实现位置 |
|------|---------|---------|
| application service 边界 | `ReceiptApplicationService` 统一 6 个 API | `src/application/receipt_service.py` |
| MCP adapter | FastMCP stdio server，6 个 tools | `src/mcp/server.py` |
| 浏览器作业锁 | `threading.Lock` 互斥，busy 时返回错误 | `src/mcp/server.py` |
| CLI 与 MCP 解耦 | `main.py` 降为 CLI adapter，`_StopController` 保留在 CLI 层 | `src/main.py` |
| `run_single` 无 job_id | service 层为单票也生成 `run_id` + 写报告 | `receipt_service.py:run_single()` |
| retry 逻辑重复 | service 层使用 `settings.max_retries` + `settings.retry_delay` | `receipt_service.py:_process_single_with_retry()` |

### 3.4 待未来阶段解决

1. **远程访问时的认证与资源限制**（阶段 2）
2. **MCP Tasks 异步能力**（阶段 3）

---

## 四、路径选择

### 路径 1：MCP Server（首选）

```text
AI Agent ←→ MCP Protocol ←→ etracking-mcp-server ←→ Etracking Application Service
```

适用场景：

- Claude Code / Cursor / OpenClaw 等 AI Agent 调用 Etracking
- 用户希望在聊天或 agent 编排中触发单票或批量下载

结论：

- **优先做**
- 但一期先做稳定 MVP，不把 Tasks 当成强依赖

### 路径 2：OpenClaw Skill（按需）

```text
OpenClaw Skill → Etracking MCP Server
```

适用场景：

- 有明确的 OpenClaw 社区分发需求
- 需要把 MCP tools 再包装成 Skill action

结论：

- **不是一期**
- MCP 稳定后再做

### 路径 3：HTTP API（按需）

```text
外部系统 / ERP / Webhook → HTTP API → Etracking Application Service
```

适用场景：

- 非 AI 系统需要触发任务或读取状态

结论：

- **不是一期**
- 也不建议先做成“MCP 的薄转发层”
- 更稳妥的做法是让 HTTP 和 MCP 共享同一个 service 层

---

## 五、推荐路线（v3）

> 阶段 0、1、1.5 已于 2026-03-22 实施完成。

### 阶段 0：抽出 application service（0.5-1 天）  ✅ 已完成

目标：

- 把 `src/main.py` 中可复用的业务编排逻辑下沉到独立服务层
- 保持 `main.py` 只负责 CLI 参数、signal handler 和退出码

具体工作：

1. 创建 `src/application/receipt_service.py`，移入 `process_single_order`、`process_batch_orders`、`retry_failed_orders`
2. 统一 retry 策略（消除 `main.py` 硬编码 3 次 vs `batch_runner` `max_attempts` 的重复）
3. 为 `run_single` 补上 `run_id` + 报告写入（统一 `get_status`/`get_artifact` 查询路径）
4. 明确 `BatchSessionProcessor` 的复用方式
5. 让 `main.py` 改为调用 service 层（CLI 行为不变）

结果：

- CLI 继续可用
- MCP / HTTP 有稳定接入边界

### 阶段 1：稳定版 MCP MVP（1-2 天）  ✅ 已完成

目标：

- 本地 `stdio` 传输
- 暴露稳定的 tool surface
- 不要求 Tasks
- 尽量复用现有 `job_id + reports` 模型

建议的一期范围：

- `run_single`
- `run_batch`
- `retry_failed`
- `get_status`
- `get_artifact`
- `health_check`

一期原则：

- 浏览器作业 **单串行**
- **阻塞式 tool**（一期接受，复杂度最低）
- `get_status` 用于读取已有 `job_id` 的快照
- 浏览器会话 **每次 tool 调用 open/close**（方案 A，与 CLI 一致）

### 阶段 2：远程访问与安全加固

目标：

- 增加 `streamable-http`
- 增加认证
- 增加资源限制和部署策略

### 阶段 3：可选的后台任务能力

目标：

- 在明确目标客户端兼容性后，再决定是否接入 MCP Tasks
- 或者继续保持“应用层 job + 报告快照”的稳定模式

结论：

- **Tasks 不是一期前提**
- **Tasks 是可选增强项**

### 阶段 4：生态封装

按需追加：

- OpenClaw Skill
- HTTP API
- 监控与运维面板

---

## 六、目标架构

### 6.1 推荐架构

```text
CLI ---------------------┐
MCP Server --------------┼──→ Application Service ───→ Browser / Workflow / Core
HTTP API ----------------┘
```

### 6.2 分层职责

| 层 | 职责 |
|----|------|
| CLI Adapter | 参数解析、signal 处理、退出码 |
| MCP Adapter | tool/resource 定义、输入校验、协议适配 |
| HTTP Adapter | 路由、认证、HTTP 响应格式 |
| Application Service | 单票、批量、重试、状态查询、artifact 查询 |
| Execution Core | `SessionManager`、`BatchRunner`、`PdfFlow`、`ReportWriter` |

### 6.3 已实现的模块

| 模块 | 文件 | 说明 |
|------|------|------|
| Application Service | `src/application/receipt_service.py` | 6 个 API 方法，统一 retry，run_single 写报告 |
| MCP Server | `src/mcp/server.py` | 6 个 tools，browser lock，stdio 传输 |
| CLI Adapter | `src/main.py` | 改为调用 service 层的薄包装 |

锁、校验、健康检查逻辑均内联在上述模块中（一期复杂度不足以拆出独立文件）。

---

## 七、MCP Surface 设计（V1）

### 7.1 必备 tools

| Tool | 输入 | 输出 | 说明 |
|------|------|------|------|
| `run_single` | `order_id` | `ReceiptResult` | 单票下载 |
| `run_batch` | `excel_path`、`sheet?`、`resume_results?` | `BatchRunResult` | 批量下载，写入 job 报告 |
| `retry_failed` | `job_id` | `BatchRunResult` | 根据历史 job 报告重跑失败订单 |
| `get_status` | `job_id` | `summary.json` 对应结构 | 读取 job 快照 |
| `get_artifact` | `job_id`、`order_id` | artifact metadata | 返回文件存在性、路径、类型、大小 |
| `health_check` | 无 | 健康状态 | 浏览器、会话、配置、Chrome 可达性 |

### 7.2 artifact 设计

v2 中的 `receipts://{order_id}` 设计不够稳。

建议改为：

- Tool：`get_artifact(job_id, order_id)`
- Optional resource：`receipt://{job_id}/{order_id}`

原因：

- 当前 artifact 的真实定位仍然依赖 job 上下文
- `order_id` 单独不足以表达“这次运行中的哪个 PDF”
- 不同客户端对 resource 的支持成熟度不同，tool 兼容性通常更稳

### 7.3 status 设计

`get_status(job_id)` 直接复用现有报告体系：

- `runtime/reports/<job_id>/summary.json`
- `runtime/reports/<job_id>/results.jsonl`

这与现有代码是对齐的，因为批处理中已经有增量快照写入。

---

## 八、关键设计决策

### 8.1 SDK 策略

一期建议：

- 使用稳定的 MCP Python SDK 能力
- Tool schema、resource、stdio、streamable-http 都可先按稳定 API 做

如果后续启用 Tasks：

- 明确切换到 **standalone FastMCP**
- 依赖形态要写清楚，例如 `fastmcp` 或 `fastmcp[tasks]`

原因：

- `mcp` 包内置的 FastMCP 与 standalone FastMCP 已经是两个演进节奏
- `task=True`、`Progress`、Docket worker 等能力属于后者的重点功能

### 8.2 Tasks 策略

v3 的立场：

- **MCP Tasks 不作为一期依赖**
- **只作为二期可选增强**

原因：

- MCP Tasks 在规范层仍属实验性能力
- Python SDK 对 tasks 的支持也仍以 experimental API 形式暴露
- standalone FastMCP 的 tasks 需要额外依赖，并要求 task-enabled tool 为 async 函数
- 当前 Etracking 的浏览器执行核心是同步 Playwright，实现上需要额外适配

### 8.3 并发策略

一期建议：

- `run_single`、`run_batch`、`retry_failed` 共用同一把“浏览器作业锁”
- 任一浏览器作业执行时，其它浏览器作业直接返回“busy”
- `get_status`、`get_artifact`、`health_check` 允许并发

原因：

- 当前核心执行器不是为并发浏览器会话调度设计的
- 单串行先求稳，再谈吞吐

### 8.4 取消策略

一期：

- CLI 继续使用 `_StopController`
- MCP 先不承诺跨客户端统一取消语义

二期可选：

- 若采用 Tasks，则接入协议级取消
- 若不采用 Tasks，则在应用层定义 job cancel 语义

### 8.5 浏览器会话生命周期

CLI 模式下 `SessionManager` 为 context manager，每次调用 open/close。MCP Server 是长驻进程，需要专门决策。

| 方案 | 说明 | 优劣 |
|------|------|------|
| A：每次 open/close | 与 CLI 一致 | 简单但慢（每次启动浏览器） |
| B：启动时 open，关闭时 close | 常驻浏览器 | 快但需管理状态和异常恢复 |
| C：懒加载 + idle timeout | 首次调用时 open，空闲超时自动 close | 平衡方案 |

**一期选择：方案 A**（与 CLI 一致，零风险）
**二期优化：方案 C**（idle timeout 自动关闭）

### 8.6 浏览器连接策略

保留现有策略：

```text
有 cdp_url → 连接已有 Chrome
无 cdp_url → 启动 Playwright 管理的 Chromium
```

### 8.7 安全策略

一期本地 `stdio`：

- 默认信任本机调用链
- 不让凭证穿过 MCP 参数
- 在 tool 入口做输入校验

二期远程 `streamable-http`：

- 增加 token 或 OAuth 风格认证
- 加入请求级资源限制和超时

---

## 九、与现有代码的映射

### 9.1 应保留复用的核心

| 现有代码 | 角色 |
|---------|------|
| `src/session_manager.py` | 浏览器生命周期与订单处理执行核心（含 `BatchSessionProcessor`） |
| `src/workflow/batch_runner.py` | 批处理、resume、retry 语义 |
| `src/workflow/entry_flow.py` | 订单入口导航流程 |
| `src/workflow/login_flow.py` | E-Tracking 登录流程 |
| `src/workflow/receipt_flow.py` | 收据页面操作流程 |
| `src/workflow/pdf_flow.py` | PDF 下载与验证流程 |
| `src/core/models.py` | MCP 输出结构的基础数据模型 |
| `src/core/paths.py` | runtime 目录定位 |
| `src/integrations/run_ledger.py` | 增量状态快照 |
| `src/integrations/report_writer.py` | 最终报告输出 |

### 9.2 应调整的边界

| 现有代码 | 建议 |
|---------|------|
| `src/main.py` | 保留为 CLI adapter，不再作为 MCP 直接调用入口 |
| `src/integrations/openclaw_contract.py` | 先保留为兼容 shim / 迁移参考，不建议一期立刻删除 |

### 9.3 建议的新映射方式

| MCP Surface | 推荐调用目标 |
|------------|-------------|
| `run_single` | `ReceiptApplicationService.run_single()` |
| `run_batch` | `ReceiptApplicationService.run_batch()` |
| `retry_failed` | `ReceiptApplicationService.retry_failed(job_id)` |
| `get_status` | 读取 `summary.json` 快照 |
| `get_artifact` | 按 `job_id + order_id` 查 artifact |
| `health_check` | 新增应用层健康检查 |

---

## 十、为什么不把 Tasks 放在一期

### 10.1 技术原因

- 规范层：Tasks 仍是 experimental
- SDK 层：Python SDK 的 tasks API 仍属 experimental
- 框架层：standalone FastMCP 的 tasks 能力虽成熟得更快，但它不是 `mcp` 包内置 FastMCP 的同一层能力
- 代码层：当前浏览器执行是同步实现，不是天然适配 task-enabled async tool

### 10.2 产品原因

一期最重要的是：

1. 让 agent 能稳定触发任务
2. 让结果可读
3. 让报告和 artifact 可取回
4. 不破坏现有 CLI

这四件事，不依赖 Tasks 也能完成。

### 10.3 何时再引入 Tasks

只有同时满足以下条件时才建议进入：

1. 一期 MCP MVP 已稳定
2. 目标客户端确实需要 deferred result retrieval
3. 已验证目标客户端对 Tasks 的兼容性
4. 已明确任务持久化、重启恢复和取消语义

---

## 十一、时间线（修订 v5）

| 阶段 | 工作量 | 状态 |
|------|--------|------|
| 阶段 0：抽 application service | 0.5 天 | ✅ 已完成（2026-03-22） |
| 阶段 1：MCP MVP（stdio） | 0.5 天 | ✅ 已完成（2026-03-22） |
| 阶段 1.5：测试与文档 | 0.5 天 | ✅ 已完成（2026-03-22，71 tests passing） |
| 阶段 2：streamable-http + 认证 | 1-2 天 | 待启动 |
| 阶段 3：Tasks 能力 | 1-2 天 | 待验证后启动 |
| 阶段 4：OpenClaw Skill / HTTP API | 0.5-1 天 / 项 | 按需 |

剩余估算：

- **带远程访问与认证**：+1-2 天
- **再加 Tasks**：+2-3 天

---

## 十二、一期实施参数（已确认）

基于本地 stdio MVP 场景，以下参数已有明确默认值：

| 参数 | 一期默认值 | 理由 | 二期可调整方向 |
|------|-----------|------|---------------|
| 目标客户端 | **Claude Code** | 当前用户环境 | 扩展 Cursor / OpenClaw |
| 执行模式 | **阻塞式 tool** | 单串行，复杂度最低 | Tasks 异步 |
| artifact 交付 | **返回文件路径** | stdio 本地模式，路径即可 | base64 / 对象存储 |
| 并发预期 | **单机单用户** | 浏览器作业锁已保证 | 多 agent 队列 |
| 运行环境 | **开发者本机** | 当前使用方式 | 远程服务器 |
| 认证要求 | **不需要** | stdio 模式无网络暴露 | token / OAuth |
| 保留策略 | **不限制，允许覆盖** | 与现有 CLI 行为一致 | 按天保留 / 归档 |
| 浏览器会话 | **每次 open/close** | 方案 A，与 CLI 一致 | 懒加载 + idle timeout |
| 传输协议 | **stdio** | 本地进程通信 | streamable-http |

---

## 十三、修订历史

### v3 修订（审查修正）

1. 保留”MCP 优先”的大方向
2. 将 **Tasks 从一期核心前提降级为可选增强**
3. 引入 **application service** 作为正确的接入边界
4. 将并发策略收紧为 **浏览器作业单串行**
5. 将 artifact 标识从 `order_id` 升级为 `job_id + order_id`
6. 将 `openclaw_contract.py` 从”立即删除”改为”先保留兼容 shim”
7. 将时间估算从乐观值修正为与当前代码结构更匹配的范围

### v4 修订（代码验证 + 实施定稿）

1. 逐一验证计划中所有代码声明（7 项全部准确）
2. 发现并记录 **5 个计划遗漏问题**（run_single 无 job_id、浏览器生命周期、retry 重复、BatchSessionProcessor、workflow 子模块）
3. 将 Phase 0 工作量从 1-2 天**修正为 0.5-1 天**
4. 将 Section 十二 的 7 个待确认项**全部填入默认值**
5. 在 Section 五 Phase 0 中**补充 5 项具体工作内容**
6. 在 Section 八**新增 8.5 浏览器会话生命周期决策**
7. 在 Section 九**补充 4 个 workflow 子模块**到核心复用表
8. 总体时间线从 3-5 天**修正为 2-4 天**
9. 状态从”建议按 v3 路线实施”更新为**”规划完成，准备进入实施”**

### v5 修订（实施完成）

1. Phase 0 + 1 + 1.5 已全部实施，**71/71 测试通过**
2. Section 3.2/3.3 更新为”已解决”+”待未来解决”两部分
3. Section 五标注各阶段完成状态
4. Section 6.3 从”建议”更新为**实际已实现的模块列表**
5. Section 十一从”估算”更新为**实际完成记录**
6. Section 14.3 从”可以开始实施”更新为**实施结果和产出清单**
7. 新增文件：`src/application/receipt_service.py`、`src/mcp/server.py`、2 个测试文件、`mcp-config.example.json`
8. 修改文件：`src/main.py`（CLI adapter）、`requirements.txt`（+mcp）

---

## 十四、代码验证审查（v4）

> 审查方法：逐一比对计划中的代码声明与实际 `src/` 目录

### 14.1 代码事实验证

| 计划声明 | 实际情况 | 结论 |
|---------|---------|------|
| `src/main.py` 支持 single/batch/retry-failed/resume | 确认：`process_single_order`、`process_batch_orders`、`retry_failed_orders` 均存在，`--resume-results` 参数已实现 | **准确** |
| `src/session_manager.py` 基于 `playwright.sync_api` 同步实现 | 确认：`SessionManager` 为 context manager，同步 API | **准确** |
| `src/workflow/batch_runner.py` 有 resume/retry/skip | 确认：`BatchRunner.run()` 接收 `previous_results` 做 skip，`retry_failed_job()` 提取失败订单 | **准确** |
| `src/core/models.py` 的 `to_dict()` 已完善 | 确认：`PdfArtifact`、`ReceiptResult`、`BatchRunResult` 均有 `to_dict()`，输出 camelCase JSON | **准确** |
| `src/core/paths.py` 的 runtime 路径标准化 | 确认：`RuntimePaths` 包含 receipts_dir、reports_dir、logs_dir 等，`report_paths_for(run_id)` 生成 summary/results/csv 路径 | **准确** |
| `src/integrations/run_ledger.py` 增量写快照 | 确认：`append_result()` 写 results.jsonl，`write_summary_snapshot()` 写 summary.json | **准确** |
| `src/integrations/openclaw_contract.py` 仅是 payload shim | 确认：只做 dict 构造，无运行时逻辑 | **准确** |

### 14.2 计划遗漏的关键问题

#### 问题 1：`run_single` 没有 `job_id` / 报告体系

当前 `process_single_order()` 直接返回 `ReceiptResult`，不创建 `run_id`，不写 `reports/` 目录。

**影响**：计划中 `get_artifact(job_id, order_id)` 和 `get_status(job_id)` 对单票场景不适用。

**建议**：service 层为 `run_single` 也生成 `run_id`，将结果写入 `reports/<run_id>/`，统一两种模式的结果查询路径。

#### 问题 2：浏览器会话生命周期未定义

CLI 模式下 `SessionManager` 作为 context manager 使用（`with SessionManager(...) as session:`），每次调用 open/close。

MCP Server 是长驻进程，需要明确：

- **方案 A**：每次 tool 调用都 open/close 浏览器（简单但慢）
- **方案 B**：MCP Server 启动时 open，关闭时 close（快但需管理状态）
- **方案 C**：懒加载 + idle timeout 自动关闭（平衡方案）

**建议**：一期用方案 A（与 CLI 一致），二期优化为方案 C。

#### 问题 3：retry 逻辑重复

- `main.py:process_single_order` — 硬编码 3 次重试 + `time.sleep(1)`
- `batch_runner.py:_run_single_order` — 按 `max_attempts` 重试，基于 `metadata.retryable` 判断

service 层应统一为一套 retry 策略，消除重复。

#### 问题 4：`BatchSessionProcessor` 未在计划中出现

`main.py` 中 batch 模式实际使用的是 `BatchSessionProcessor`（从 `session_manager.py` 导入），而非直接使用 `SessionManager`。service 层需要明确复用哪个。

#### 问题 5：workflow 子模块未在映射中列出

除 `batch_runner.py` 外，还有 `entry_flow.py`、`login_flow.py`、`receipt_flow.py`、`pdf_flow.py` 四个 workflow 模块。它们不需要修改，但属于执行核心的一部分，应在"应保留复用的核心"表中补充。

### 14.3 审查结论与实施结果

上述 5 个遗漏问题已在实施中**全部解决**：

| 问题 | 解决方式 |
|------|---------|
| `run_single` 无 job_id | `receipt_service.py:run_single()` 生成 `run_id` + 写 `reports/` |
| 浏览器会话生命周期 | 一期选方案 A（每次 open/close），与 CLI 一致 |
| retry 逻辑重复 | 统一为 `settings.max_retries` + `settings.retry_delay` |
| `BatchSessionProcessor` 未提及 | 在 `run_batch()` 中显式使用 |
| workflow 子模块未列出 | 已补充到 Section 9.1 核心复用表 |

实施产出：

```text
✅ Phase 0.1 — src/application/receipt_service.py (ReceiptApplicationService, 6 methods)
✅ Phase 0.2 — 统一 retry，run_single 补 run_id + 报告写入
✅ Phase 0.3 — main.py 改为 CLI adapter，71/71 既有测试通过
✅ Phase 1.1 — src/mcp/server.py (FastMCP, stdio, browser lock)
✅ Phase 1.2 — 6 tools: run_single, run_batch, retry_failed, get_status, get_artifact, health_check
✅ Phase 1.5 — 17 new tests (test_receipt_service.py + test_mcp_tools.py), mcp-config.example.json
```

---

## 参考资料

- MCP Python SDK（稳定 README）：https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md
- MCP Python SDK API：https://py.sdk.modelcontextprotocol.io/api/
- MCP Tasks 草案规范：https://modelcontextprotocol.io/specification/draft/basic/utilities/tasks
- FastMCP 从 MCP SDK 升级说明：https://gofastmcp.com/getting-started/upgrading/from-mcp-sdk
- FastMCP Background Tasks：https://gofastmcp.com/servers/tasks
