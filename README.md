# AA Copilot for Solana

<div align="center">

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Solana](https://img.shields.io/badge/Solana-USDC-purple.svg)](https://solana.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**一个面向 Solana Agent Economy Hackathon 的 Agent Skill：让群聊里的 AA 收款，从混乱变优雅。**

[English](#english) | [中文](#中文)

</div>

---

## 中文

### 项目简介

AA Copilot for Solana 是一套可调用、可复用、可验证的 **Agent Skill**。它不是前端产品，而是一套围绕 `Solana + Agent Skills + 群体分账` 设计的技能包。

它可以被 `OpenCode`、`OpenClaw`、`Claude Code` 等支持技能目录或提示包的运行时接入，用于识别账单、生成分摊方案、创建链上付款请求、追踪付款状态。

### 现实痛点

AA 的痛点从不是数学：

- "刚才那笔到底是不是这顿饭？"
- "到底 4 个人还是 5 个人？"
- "谁多喝了饮料？"
- "谁还没转？"
- "我转了，你看到了吗？"

**结果**：一位尴尬催款的朋友 + 一个越来越安静的群 + 一张根本没人想再打开第二次的聊天记录截图

### 核心能力

| 能力             | 说明                                                                   |
| ---------------- | ---------------------------------------------------------------------- |
| 🔍 链上查询      | 查询 Solana mainnet 钱包活动，支持 `urllib` / `curl` 两种 RPC 传输方式 |
| 🎯 交易识别      | 识别近期候选支出，做排序与理解                                         |
| 📝 手工 fallback | 交易识别失败后，支持从「账单金额 + 币种 + 分摊规则」直接进入           |
| 🧮 规则解析      | 解析自然语言分摊规则                                                   |
| 📊 草案生成      | 生成分摊草案并要求确认                                                 |
| 💳 支付请求      | 允许参与人钱包地址缺失，不阻塞请求生成                                 |
| 🔗 Solana Pay    | 为每个参与人生成独立的 Solana Pay 请求（含唯一 reference）             |
| 📱 状态追踪      | 用唯一 `reference` 追踪付款状态                                        |
| 🖼️ 可视化        | 把支付请求渲染成更好分享的 HTML / Markdown 视图                        |

### 适用场景

- 朋友聚餐 AA
- 旅行共同开销结算
- 室友采购或房租分摊
- 社群活动费用回收
- 小团队内部报销 / 代垫回款

简单说：**只要有「一个人先付了，后面几个人要补给TA」的场景，这个 skill 就有意义。**

### 技术栈

**链上层**

- Solana Mainnet RPC
- Solana Pay
- USDC on Solana

**技能实现层**

- Python 3
- JSON artifact pipeline
- curl / urllib dual transport

**运行时兼容层**

- OpenCode
- OpenClaw
- Claude Code
- 其他支持技能目录或脚本调用的 Agent Runtime

**展示层**

- HTML payment request renderer
- Markdown payment request renderer

### 快速开始

#### 1. 结构验证

```bash
python skills/solana-aa-settlement/scripts/quick_validate.py
```

#### 2. 回归测试

```bash
python tests/test_solana_aa_settlement.py
```

#### 3. 主网钱包活动查询

```bash
# 推荐方式（使用 curl）
python skills/solana-aa-settlement/scripts/fetch_solana_wallet_activity.py \
  --transport curl \
  --wallet-address "<wallet>" \
  --rpc-url "https://api.mainnet.solana.com" \
  --include-native \
  --max-normalized-transfers 5 \
  --limit 10

# 自动选择传输方式
python skills/solana-aa-settlement/scripts/fetch_solana_wallet_activity.py \
  --transport auto \
  --wallet-address "<wallet>" \
  --rpc-url "https://api.mainnet.solana.com"

# 使用自定义 RPC 提供商
python skills/solana-aa-settlement/scripts/fetch_solana_wallet_activity.py \
  --transport auto \
  --wallet-address "<wallet>" \
  --rpc-url "<provider-rpc>" \
  --http-header "x-api-key=<key>"
```

#### 4. 渲染支付请求

```bash
# 默认：仅返回 JSON（推荐用于聊天机器人；默认用户文本不会暴露 raw pay_url/reference）
python skills/solana-aa-settlement/scripts/render_payment_requests.py \
  --input-file payment_requests.json \
  --output-file result.json

# 生成 HTML/Markdown 文件（默认隐藏 raw link/reference）
python skills/solana-aa-settlement/scripts/render_payment_requests.py \
  --input-file payment_requests.json \
  --output-dir rendered

# 生成本地 QR 图片（需要安装 qrcode 库）
python skills/solana-aa-settlement/scripts/render_payment_requests.py \
  --input-file payment_requests.json \
  --output-dir rendered \
  --prefer-local-qr

# 调试视图：仅供操作员排查时查看 raw pay_url/reference
python skills/solana-aa-settlement/scripts/render_payment_requests.py \
  --input-file payment_requests.json \
  --debug-view \
  --output-file debug_result.json
```

### 完整工作流示例

假设 Alice 先支付了 `100 USDC`，一共 4 个人吃饭：

```bash
# 1. 创建账单上下文
python scripts/create_manual_bill_context.py \
  --bill-amount "100" \
  --token-symbol "USDC" \
  --payer-id "alice" \
  --output-file bill_context.json

# 2. 解析分摊规则
python scripts/parse_split_rules.py \
  --rule-text "4 people" \
  --payer-id "alice" \
  --output-file split_rules.json

# 3. 生成分摊草案
python scripts/build_split_plan.py \
  --bill-amount "100" \
  --parsed-rules-file split_rules.json \
  --participants-file participants.json \
  --payer-id "alice" \
  --output-file split_plan.json

# 4. 生成 Solana Pay 请求
python scripts/generate_solana_pay_requests.py \
  --wallet-resolution-file wallet_resolution.json \
  --recipient-wallet "<alice_wallet>" \
  --bill-id "dinner-001" \
  --output-file payment_requests.json

# 5. 渲染（可选）
python scripts/render_payment_requests.py \
  --input-file payment_requests.json \
  --output-file rendered.json
```

**分摊结果**：每人 `25 USDC`，系统为另外 3 人生成独立的 Solana Pay 请求。聊天模式默认优先输出结构化 QR 媒体，不再把本地二维码路径、raw `solana:` URI 或 `reference` 明文发给终端用户。

### 项目结构

```
.
├── README.md
├── DEMAND.md
├── PROJECT_PLAN.md
├── SKILLS_PLAN.md
├── skills/
│   └── solana-aa-settlement/
│       ├── SKILL.md              # 技能文档（主入口）
│       ├── agents/
│       │   └── openai.yaml       # Agent 配置
│       ├── references/           # 参考文档
│       │   ├── workflow.md       # 工作流说明
│       │   ├── contracts.md      # 数据契约
│       │   ├── transaction-discovery.md
│       │   ├── solana-pay.md
│       │   └── state-machine.md
│       └── scripts/              # 可执行脚本
│           ├── common.py
│           ├── fetch_solana_wallet_activity.py
│           ├── fetch_recent_transfers.py
│           ├── rank_expense_candidates.py
│           ├── create_manual_bill_context.py
│           ├── parse_split_rules.py
│           ├── build_split_plan.py
│           ├── resolve_participant_wallets.py
│           ├── generate_solana_pay_requests.py
│           ├── render_payment_requests.py
│           └── watch_bill_status.py
└── tests/
    ├── fixtures/
    └── test_solana_aa_settlement.py
```

---

## English

### Overview

AA Copilot for Solana is an **Agent Skill** designed for the Solana Agent Economy Hackathon. It transforms the chaotic process of group expense splitting into an elegant, automated workflow.

This is not a frontend product, but a reusable skill package around `Solana + Agent Skills + Group Settlement`. It can be integrated into runtimes like `OpenCode`, `OpenClaw`, `Claude Code` to handle bill recognition, split generation, payment request creation, and payment tracking.

### The Problem

Group expenses are never about math. The real pain points are:

- "Which transaction was for this dinner?"
- "Was it 4 or 5 people?"
- "Who drank extra?"
- "Who hasn't paid yet?"
- "I sent it, did you see?"

**Result**: One awkward friend playing temporary CFO + a progressively quieter group chat + a screenshot nobody wants to open again.

### Core Capabilities

| Capability                 | Description                                                                  |
| -------------------------- | ---------------------------------------------------------------------------- |
| 🔍 On-chain Query          | Query Solana mainnet wallet activity with dual transport (`urllib` / `curl`) |
| 🎯 Transaction Recognition | Identify and rank recent expense candidates                                  |
| 📝 Manual Fallback         | Continue with manual bill entry when on-chain discovery fails                |
| 🧮 Rule Parsing            | Parse natural language split rules                                           |
| 📊 Draft Generation        | Generate split drafts with confirmation gates                                |
| 💳 Payment Requests        | Generate Solana Pay requests without requiring participant wallet addresses  |
| 🔗 Solana Pay              | Create unique payment requests per participant with trackable references     |
| 📱 Status Tracking         | Track who paid using unique `reference`                                      |
| 🖼️ Rendering               | Output shareable HTML / Markdown views                                       |

### Tech Stack

- **Chain Layer**: Solana Mainnet RPC, Solana Pay, USDC
- **Implementation**: Python 3, JSON artifact pipeline
- **Runtime**: OpenCode, OpenClaw, Claude Code compatible
- **Presentation**: HTML/Markdown renderers

### Quick Start

```bash
# Query wallet activity
python scripts/fetch_solana_wallet_activity.py \
  --transport curl \
  --wallet-address "<wallet>" \
  --rpc-url "https://api.mainnet.solana.com"

# Generate payment requests
python scripts/generate_solana_pay_requests.py \
  --wallet-resolution-file wallets.json \
  --recipient-wallet "<your_wallet>" \
  --bill-id "dinner-001"

# Render (JSON output only, no files)
python scripts/render_payment_requests.py \
  --input-file payment_requests.json \
  --output-file result.json
```

### Example: 100 USDC Dinner

Alice paid `100 USDC` for a 4-person dinner. The workflow:

1. **Recognize** the transaction on-chain (or use manual fallback)
2. **Generate** split draft: 4 people × `25 USDC`
3. **Confirm** the draft with payer
4. **Create** 3 independent Solana Pay requests
5. **Track** payments by unique reference
6. **Complete** when all requests are paid

### Design Highlights

- **Security First**: Input validation, payload size limits, header sanitization
- **Resilient**: curl fallback for unreliable Python networking
- **Privacy**: Local QR generation preferred over remote services
- **User-Friendly**: Wallet addresses optional, identity-based requests
- **Runtime Agnostic**: Works across different Agent platforms

### Why Solana

- Fast settlement
- Clear on-chain records
- Low friction for payment requests
- Native Solana Pay support

### Status

✅ Core skill implementation complete  
✅ Security hardened  
✅ Python 3.9+ compatible  
📝 X Article: [X_ARTICLE.md](X_ARTICLE.md)  
📸 Demo screenshots: Coming soon

### License

[MIT](LICENSE)

---

<div align="center">

**Built with ❤️ for the Solana Agent Economy Hackathon**

[GitHub](https://github.com/yourusername/solana-aa-settlement) · [Issues](https://github.com/yourusername/solana-aa-settlement/issues) · [Discussions](https://github.com/yourusername/solana-aa-settlement/discussions)

</div>
