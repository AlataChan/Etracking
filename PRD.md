# 📦 Order PDF Secure Downloader · 产品开发文档

## 🧭 项目背景

本项目旨在实现对 **泰国海关 e-Tracking 系统**的自动化操作流程，包括登录、订单号查询、收据页面弹出、并将其转换为 PDF 格式保存的全过程。目标是替代人工操作，提高效率，降低人为失误，并保障账号与平台的交互安全。

目标网站：[https://e-tracking.customs.go.th/ETS/](https://e-tracking.customs.go.th/ETS/)

---

## 🎯 功能需求概述

| 编号 | 功能描述                           |
| -- | ------------------------------ |
| F1 | 自动读取并校验Excel中多个Sheet的提单号（F列）   |
| F2 | 自动登录或复用已登录会话，自动检测session状态     |
| F3 | 输入订单号并触发收据打印操作                 |
| F4 | 监听弹出的打印页面并导出为PDF（支持blob:弹窗自动抓取） |
| F5 | PDF文件自动规范化命名（提单号_下载日期）并分文件夹存储（receipts目录） |
| F6 | 支持异常指数退避重试机制、失败记录、成功日志汇总       |
| F7 | 模拟随机人类行为以规避封禁风险                |
| F8 | 完善结构化日志与异常实时报警机制               |

---

## 🧱 技术架构

* **语言**：Python 3.9+
* **核心库**：

  * [`playwright`](https://playwright.dev/python/)（浏览器自动化）
  * `pandas`（Excel处理）
  * `loguru`（日志）
  * `pyyaml`（配置读取）
* **设计模式**：模块化 + 任务管道式执行
* **安全机制**：行为模拟、会话复用、频率限制、UA伪装

---

## 📁 项目结构说明

```
order_pdf_sop/
│
├── config/
│   ├── settings.yaml
│   └── user_agents.txt
│
├── data/
│   └── orders.xlsx
│
├── session/
│   └── state.json
│
├── downloads/
│   └── receipts/
│       └── YYYY-MM-DD/
│           └── 提单号_下载日期.pdf
│
├── src/
│   ├── main.py
│   ├── session_manager.py
│   ├── navigator.py
│   ├── receipt_printer.py
│   ├── humanizer.py
│   ├── excel_reader.py
│   ├── monitor.py
│   └── utils.py
│
├── logs/
│   └── app.log
│
├── requirements.txt
└── README.md
```

---

## 🚦 执行流程

### ▶️ 初始部署

1. 安装依赖

   ```bash
   pip install -r requirements.txt
   playwright install
   ```

2. 手动登录并保存登录会话

   ```bash
   playwright codegen https://e-tracking.customs.go.th/ETS/
   ```

   将 session 保存为 `session/state.json`

---

### ▶️ 自动化执行逻辑

1. 加载并校验 `orders.xlsx` 所有 sheet，提取 F 列提单号

2. 启动 Playwright 浏览器（非 headless）并加载会话

3. 对每个订单号执行：

   * 输入提单号，提交搜索
   * 点击"打印收据"按钮
   * 等待弹窗页面打开
   * 导出当前页面为 PDF：`page.pdf(path=...)`
   * 命名为 `${提单号}_下载日期.pdf`，保存至 receipts 目录

4. 日志记录处理情况、错误原因

5. 导出执行报告（成功/失败数量、处理时间）

---

## 🛡️ 安全机制设计

| 项目        | 防护措施                       |
| --------- | -------------------------- |
| 登录频率限制    | 会话持久化避免重复登录                |
| 被识别为机器人   | Headless 关闭，使用真实浏览器模式      |
| 自动操作模拟    | 模拟键盘输入、鼠标移动、随机延迟           |
| 下载控制      | 每个任务延迟 10\~20 秒，防止接口请求频率过高 |
| 文件命名 & 路径 | 精确控制文件名与提单号绑定，避免重复覆盖       |
| 网络波动应对    | 异常指数退避重试 + 日志记录失败提单        |
| 实时异常报警    | 异常自动触发报警邮件提醒               |

---

## 📌 注意事项 Checklist

* [ ] 确保账号具备打印权限
* [ ] 手动保存一次登录状态
* [ ] 浏览器窗口不可最小化（否则页面截图可能为空）
* [ ] 若网页结构变动需重新调整 selector 选择器
* [ ] 网络抖动时增加延迟或尝试次数

---

## ✅ 项目价值总结

* **自动化替代人工**：提升效率 5-10 倍
* **标准化输出**：命名规范一致、可审计
* **安全性强**：避免账号频繁登录、规避被识别风险
* **企业可用**：适合报关、贸易、财务流程自动化集成

---

> 👨‍💻 维护者：META\_ME · 自适应 AI Agent
> 📅 最后更新：2025-05-08

* 自动等待Loading弹窗消失，确保PDF页面加载完成
* 支持blob:开头PDF弹窗，自动抓取二进制流保存

- step1-10（登录、协议、菜单、表单前置）只做一次
- step11-13（填写订单号、查找、导出PDF）循环处理所有订单
