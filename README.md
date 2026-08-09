# Free Token Hunter · 免费额度猎手

一个**零第三方依赖**（仅用 Python 3 标准库 `argparse` / `json` / `urllib` / `pathlib`）的命令行工具，自动汇总互联网上各类提供**免费 token / 额度**的渠道（大模型 API、云服务、学生福利、免费算力），为每个渠道生成清晰的引导流程（注册 → 订阅 → 领取），并帮助用户**逐步完成领取、记录进度、实测 Key 可用性**。

> 项目目标：把分散在官网 / 社区 / 清单仓库里的「免费额度获取方式」整理成一份可检索、可引导、可验证的结构化知识库，并尽量自动化「逐个领取」的过程。

---

## 特性

- **41 个渠道**，结构化 JSON 数据，按类别分文件维护（国内大模型 / 海外大模型 / 云服务 / 学生算力）。
- **8 个子命令**：`list` / `show` / `plan` / `guide` / `status` / `verify` / `export` / `discover`。
- **个性化路线**：根据「能否海外网络 / 是否绑卡 / 是否学生 / 主要用途」加权排序，给出最适合你的领取顺序。
- **交互式逐步引导**：`guide` 按渠道内置的 `signup` / `claim` 步骤逐条带过，可标记 `done / doing / skip`，进度落盘。
- **API Key 实测**：对 OpenAI 兼容端点发一次真实请求，验证 Key 是否真的能用（不是只看文档）。
- **HTML 单文件看板**：`export --format html` 生成带 `localStorage` 进度的可视化面板，支持筛选 / 搜索 / 排序。
- **联网发现**：`discover` 抓取 `free-for-dev` 等长尾清单仓库，并用 GitHub 搜索 API 动态发现高星清单，自动补全未收录渠道。
- **安全优先**：领取到的密钥写入本地 `out/keys.local.env`（权限 `chmod 600`），**不进 git**；`.gitignore` 已排除密钥与运行产物。

---

## 目录结构

```
free-token-hunter/
├── hunter.py                  # 主程序（约 700 行，零依赖 CLI）
├── data/
│   ├── 01-llm-cn.json         # 国内大模型 API（14 渠道）
│   ├── 02-llm-global.json     # 海外大模型 API（13 渠道）
│   ├── 03-cloud.json          # 云服务 / 部署 / 数据库（8 渠道）
│   ├── 04-student-compute.json# 学生 / 免费算力（7 渠道）
│   └── custom_channels.json   # 你自己追加的渠道（可选，自动合并）
├── templates/
│   └── dashboard.html         # HTML 看板模板（占位符 /*__DATA__*/ 在 export 时被替换）
├── out/                       # 运行产物（已 gitignore）
│   ├── index.html             # export 生成的看板
│   ├── 免费token渠道汇总.md    # export 生成的 Markdown 报告
│   ├── channels.merged.json   # 合并后的全量数据
│   ├── progress.json          # 领取进度
│   ├── plan.json              # 个性化路线
│   ├── discovered.json        # discover 发现结果
│   └── keys.local.env         # 本地密钥库（不入库）
├── .gitignore
└── README.md
```

---

## 快速开始

```bash
# 进入项目目录
cd free-token-hunter

# 1. 先看全量渠道清单（支持筛选）
python hunter.py list

# 2. 生成一条个性化领取路线（会问几个问题）
python hunter.py plan

# 3. 按路线逐个引导领取（q 退出，b 回看，d/s 标记状态）
python hunter.py guide

# 4. 查看进度与到期提醒
python hunter.py status
```

> **Windows / 环境提示**：建议用本机受管 Python（3.11+）。若在受限沙箱里跑，需要联网的命令（`discover`、`verify` 真实请求）要允许出网。`.env` 与 `out/` 已被 `.gitignore` 排除，密钥不会误提交。

---

## 命令详解

### `list` —— 列出渠道
```
python hunter.py list [--region cn|global] [--category llm-api|aggregator|cloud|compute|student]
                      [--no-card] [--no-vpn] [--student] [--exclude-student]
                      [-k 关键词] [--min-score 8.0]
```
按筛选条件打印表格（名称 / 地区 / 分类 / 难度 / 推荐分 / 关键需求）。

### `show <id>` —— 查看单个渠道完整引导
```
python hunter.py show zhipu-bigmodel
```
打印注册步骤、领取步骤、验证方式、提示与风险。

### `plan` —— 生成个性化路线
```
python hunter.py plan [--top 12]
```
交互问答（网络、绑卡、学生、用途）后，按加权分输出最优领取顺序，写入 `out/plan.json`。

### `guide` —— 分步引导并记录进度
```
python hunter.py guide [<id>] [--all]
```
- 不传 `id`：按 `out/plan.json` 路线逐个引导；`--all` 忽略路线引导全部。
- 传 `id`：只引导指定渠道。
- 交互键：`d`=标记已完成 / `s`=进行中 / `k`=跳过 / `b`=回看上一步 / `q`=退出。
- 进度写入 `out/progress.json`。

### `status` —— 领取进度与到期提醒
```
python hunter.py status [-v]
```
统计「已领取 / 进行中 / 未开始」，并列出临近到期的渠道（`-v` 显示每个渠道详情）。

### `verify` —— 实测 API Key
```
python hunter.py verify [<id>] [--no-record]
```
读取 `out/keys.local.env` 中对应 `env` 的 Key，对 `verify.base_url` 发一次 `/chat/completions` 真实请求，返回可用 / 不可用。**仅支持 `type: openai_compatible` 的渠道。**

### `export` —— 导出报告
```
python hunter.py export [--format md|html|json|all]   # 默认 all
```
- `md` → `out/免费token渠道汇总.md`
- `html` → `out/index.html`（数据注入模板，可双击打开）
- `json` → `out/channels.merged.json`
- `all` → 三个都生成。

### `discover` —— 联网发现未收录渠道
```
python hunter.py discover [--top 30] [--no-search]
```
- 内置已验证静态源（`free-for-dev`、`awesome-free-chatgpt`，含 `master`/`main` 回退）。
- 默认调用 GitHub 搜索 API，按中英文查询词发现高星（≥200★）清单仓库，解析其中提到的资源。
- 结果写入 `out/discovered.json`，供你人工审阅后转成 `custom_channels.json`。

---

## 渠道数据格式

每个 `data/*.json` 是一个「数据包」，结构：

```json
{
  "pack": "国内大模型 API 免费额度",
  "pack_id": "llm-cn",
  "note": "国内直连，无需海外网络；绝大多数需手机号注册。",
  "channels": [
    {
      "id": "zhipu-bigmodel",
      "name": "智谱 AI 开放平台 BigModel",
      "aka": ["GLM", "ChatGLM"],
      "category": "llm-api",          // llm-api | aggregator | cloud | compute | student
      "region": "cn",                 // cn | global
      "url": "https://open.bigmodel.cn",
      "claim_url": "https://open.bigmodel.cn/usercenter/resourcepack",
      "docs_url": "https://open.bigmodel.cn/dev/api",
      "quota": "新用户赠送约 2000 万 tokens；GLM-4-Flash 长期免费",
      "validity": "赠送包官方口径长期有效",
      "reset": "一次性发放，Flash 免费模型不消耗额度",
      "needs": { "card": false, "phone": true, "realname": true, "vpn": false, "student": false },
      "difficulty": 1,                // 1~5，越低越容易
      "score": 9.5,                   // 推荐分，越高越值得先领
      "tags": ["中文强", "OpenAI兼容", "长期有效"],
      "signup": ["步骤1", "步骤2", "..."],
      "claim":   ["领取1", "领取2", "..."],
      "verify":  { "type": "openai_compatible", "base_url": "https://.../v4", "model": "glm-4-flash", "env": "ZHIPU_API_KEY" },
      "tips":    ["提示1", "..."],
      "risks":   ["风险1", "..."]
    }
  ]
}
```

### 如何新增渠道

1. **快速追加**：在 `data/custom_channels.json` 里按上面的结构加 `channels` 数组（文件不存在可自建，加载时自动与 `data/0*.json` 合并）。
2. **正式收录**：直接编辑对应分类的 `data/0N-*.json`。
3. 字段尽量填全；`verify` 仅 `openai_compatible` 类型可被 `verify` 命令自动实测，其余类型请手填 `tips` 说明验证办法。

---

## 安全与合规提醒

- **密钥不出本机**：`verify` / `guide` 读取的 Key 只存在本地 `out/keys.local.env`，文件权限 `chmod 600`，且 `.gitignore` 已排除。请勿把该文件提交、上传或发给他人。
- **遵守各平台条款**：免费额度通常仅限个人学习 / 非商用；不要用于刷量、滥用或转售。部分海外渠道需要真实海外网络与支付方式，请按平台要求合规使用。
- **额度会变动**：厂商政策、赠送额度、有效期随时调整，本仓库数据为抓取时快照，领取前请以官网实时页面为准。
- **`discover` 仅供参考**：联网发现的清单来自第三方仓库，链接与可用性需你自行甄别；工具不会自动注册或代填任何表单。

---

## 已知限制

- `verify` 仅对 `openai_compatible` 端点做真实调用；其余渠道（如纯云资源、学生包）需你手动在控制台确认。
- 引导是「带步骤 + 记录进度」，**不会**自动代你点网页 / 填表单 / 过短信验证码——这些必须人来完成（验证码、实名、绑卡无法自动化，也不应自动化）。
- 数据覆盖面以主流、长期有效、低门槛的渠道为主；长尾一次性活动靠 `discover` 补充，不保证全量。

---

## 维护建议

- 每季度跑一次 `python hunter.py discover` 找新渠道，审阅后合入 `custom_channels.json`。
- 领取后及时 `status` 查看到期日，临近过期的额度优先用掉。
- 想扩展更多国家 / 更多类别，直接在 `data/` 增加 `0N-*.json` 并补 `CATEGORY_LABEL`（在 `hunter.py` 内）即可。
