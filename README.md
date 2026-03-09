# 泰国海关 E-tracking PDF 下载工具

## 当前边界

这个仓库现在把仓库根目录当作项目根目录使用，不再假设外层还有 `etracking/` 子项目。

- 运行期文件放到 `runtime/`
- 浏览器与旧流程代码仍在 `src/session_manager.py`，但新的配置、路径、结果和批处理边界已经拆到 `src/core/`、`src/workflow/`、`src/support/`
- 默认离线测试只跑 `tests/unit/`
- 现场浏览器冒烟测试位于 `tests/integration/`，需要显式 opt-in

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org -r requirements.txt
playwright install chromium
```

## 配置

受版本控制的安全模板在 [config/settings.example.yaml](/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/config/settings.example.yaml)。

本地实际配置可以放在以下任一位置，都会覆盖模板：

- `config/settings.yaml`
- `config/settings.local.yaml`
- 环境变量：`ETRACKING_TAX_ID`、`ETRACKING_BRANCH_ID`、`ETRACKING_PRINTER_CARD_NUMBER`、`ETRACKING_PRINTER_PHONE_NUMBER`、`ETRACKING_BROWSER_CDP_URL`、`ETRACKING_EXCEL_PATH`、`ETRACKING_OUTPUT_DIR`

本地配置文件已被 [`.gitignore`](/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/.gitignore) 忽略，不应提交。

## Runtime 目录

默认运行期输出位于 `runtime/`：

- `runtime/logs/`：结构化日志与截图
- `runtime/session/state.json`：浏览器会话状态
- `runtime/receipts/`：下载得到并通过校验的 PDF
- `runtime/reports/<job_id>/`：批处理报告
- `runtime/inbox/`：可选的外部投递目录

旧的 `logs/`、`downloads/`、`session/`、`data/receipts/` 已被视为历史运行产物，不再作为源码目录。

## Secrets 处理

- 不要把真实税号、打印卡号、手机号写进 `settings.example.yaml`
- 优先用 `config/settings.local.yaml` 或环境变量保存凭据
- 真实浏览器状态文件只放在 `runtime/session/state.json`

## 命令行

单个订单：

```bash
./.venv/bin/python -m src.main --order-id A017X680406286
```

批量处理：

```bash
./.venv/bin/python -m src.main --batch --excel data/orders.xlsx --sheet Sheet1
```

关闭已保存会话状态：

```bash
./.venv/bin/python -m src.main --batch --no-saved-state
```

指定运行期输出目录：

```bash
./.venv/bin/python -m src.main --batch --output-dir runtime/receipts
```

连接到已启动的 Chrome DevTools 会话：

```bash
./.venv/bin/python -m src.main --cdp-url http://127.0.0.1:9222 --order-id A017X680406286
```

只重跑之前失败的订单：

```bash
./.venv/bin/python -m src.main --retry-failed-from runtime/reports/<job_id>/results.jsonl
```

## Job 输出

每次批量运行都会写出：

- `summary.json`
- `results.jsonl`
- `results.csv`

这些文件默认位于 `runtime/reports/<job_id>/`，其中包含成功数、失败数、人工复核数、失败原因以及产物路径。

## PDF 成功标准

订单只会在以下条件全部满足时记为成功：

- 文件存在
- 文件头是真实 PDF
- 文件大小超过最小阈值
- 产物能和请求的订单号关联起来

截图后备或 marker PDF 不再算成功，只会记为失败或人工复核。

## 测试

默认离线单元测试：

```bash
./.venv/bin/python -m pytest tests/unit -q
```

当前单元测试覆盖：

- 配置与 runtime 路径
- PDF 校验规则
- 语义化 receipt flow 选择器
- 批处理参数传播
- DevTools 诊断载荷
- CDP attach 到现有 Chrome 会话
- OpenClaw 合同面

相关文档：

- [DevTools 调试流程](/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/docs/devtools-debugging.md)
- [OpenClaw 集成约定](/Users/apple/Documents/2.1 AI Journey/Cursor_projects/Etracking/docs/openclaw-integration.md)
