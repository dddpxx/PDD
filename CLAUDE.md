# CLAUDE.md

面向后续接手本仓库的 AI 智能体的上手文档。**动手前请先读根目录的 `DM.md`**——那是本项目唯一的设计基准文档，记录了每个决策点（`【D-序号】`）和大量踩坑经验，本文件只是它的快速索引与工程化补充。

## 项目简介

拼多多 AI 选品 / 改款 / 自动履约系统：粘贴一个拼多多商品链接，系统自动抓取源商品、用 AI 重写文案、生成"改款后"的场景图与详情页，发布到自己的店铺；客户下单后再用买家账号去源店代下单，形成"无库存代发"闭环（完整愿景见 `DM.md §0/§1`）。

**当前实现进度**（重要，别按愿景假设功能都在）：

- **已跑通**：Module 01~06 的"商品加工链路"（导入 → 分析 → 关键词 → 文案 → AI 场景图 → 详情页预览），已用真实链接（男士内裤，`goods_id=981833693052`）端到端验证。
- **半成品**：Module 07 发布（改走 Playwright 操作商家后台网页，见 `DM.md §16`）、Module 09 采购履约（只做了利润守卫核价 + 账号池调度，真正的自动下单**故意没写**，见 `DM.md §15`）。
- **未开始**：Module 08 订单中心、Module 10 AI 客服。

## 技术栈

纯 Python 后端脚本，**没有前端 / 数据库 / 消息队列**——这是有意的轻量决策（`DM.md §7 D4`：加工链路先用脚本跑起来，不上 FastAPI+Celery+Postgres+Redis）。

- 语言：Python 3.10+（代码用了 `str | None` 语法）
- 依赖（`backend/requirements.txt`）：`requests` + `beautifulsoup4`（抓商品页）、`python-dotenv`、`openai`（文本模型，走 OpenAI 兼容中转）、`pillow`（用代码把文案画成卖点图，不用 AI 画字）、`playwright`（登录取 cookie + 操作商家后台）
- AI 图像生成：**本地 ComfyUI**（2026-08-17 起，Module 05 从 gpt-image 切到本地 Qwen-Image-Edit-2509），默认监听 `http://127.0.0.1:8189`，靠图像参考图锁商品/人物一致性，见 `comfy_client.py` / `creative.py`
- AI 文本：OpenAI 兼容中转（当前用 sublyx），`llm_client.py` 封装

## 目录结构

所有代码在 `backend/` 下：

```
backend/
├── requirements.txt
├── .env.example              # 环境变量样板（注意：已过时，见下方「环境变量」）
├── login_pdd.py              # 入口①：弹浏览器人工登录一次，存登录态到 pdd_login_state.json
├── run_pipeline.py           # 入口②：python run_pipeline.py <拼多多链接>，跑 Module 01~06
├── pdd_agent/                # 核心包，每个文件对应 DM.md 里一个 Module
│   ├── config.py             # 环境变量 → Settings，文本/图像凭证分开配
│   ├── models.py             # 所有数据模型（dataclass）
│   ├── auth.py               # 登录态管理 + Playwright 反指纹上下文 new_stealth_context()
│   ├── importer.py           # Module 01 商品导入（抓公开详情页，无官方API）
│   ├── analyzer.py           # Module 02 商品分析 + 图片分类打标(KEEP/DROP)
│   ├── keywords.py           # Module 03 关键词（V0，LLM主观打分，非真实热度统计）
│   ├── copywriter.py         # Module 04 文案生成（受"事实锁"约束）
│   ├── creative.py           # Module 05 AI场景图（调本地 ComfyUI）
│   ├── comfy_client.py       # ComfyUI 客户端（Z-Image-Turbo / Qwen-Image-Edit-2509）
│   ├── personas.py           # 模特人设一致性（代号系统：壮壮/土土/憨憨/帅帅）
│   ├── detail_builder.py     # Module 06 详情页组装（preview.html + detail_page.html）
│   ├── detail_graphics.py    # Module 06 附属：用 Pillow 把文案画成卖点/介绍图
│   ├── typo_fix.py           # 已知错别字的纯文本兜底替换（图片级涂改已废弃）
│   ├── store_publisher.py    # Module 07 build_publish_plan()：把SKU/属性算成发布方案（只算数据）
│   ├── merchant_publisher.py # Module 07 用 Playwright 操作 mms.pinduoduo.com 真实填表
│   ├── pdd_client.py         # 开放平台API签名机制（路线已放弃，留着备用，见 DM.md §16）
│   ├── procurement.py        # Module 09 利润守卫核价 + 买家账号池调度（无真实下单）
│   ├── pipeline.py           # 串起 Module 01~06 的编排逻辑
│   └── utils.py              # 下载文件等杂项
├── assets/model_personas/    # 模特人设标准照 + 提示词素材（personas.py 用）
└── _explore_*.py / _test_*.py / _run_log.txt / *.png  # 临时探索脚本与产物，标注"用完即删"，非正式代码
```

运行产物写到 `backend/output/<goods_id>/`（已在 `.gitignore`），如 `preview.html`（人工审核左右对比）、`detail_page.html`（模拟手机端详情页）、`scenes/*.png`。

## 如何运行

命令均从 `backend/` 目录执行（下面是 Windows PowerShell 写法，源自 `DM.md §12/§13`）：

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium          # login_pdd.py / 商家后台自动化需要浏览器内核
copy .env.example .env               # 然后按下方「环境变量」填好，注意 .env.example 已过时
python login_pdd.py                  # 弹浏览器人工登录拼多多，存 pdd_login_state.json
python run_pipeline.py "<拼多多商品链接>"
```

跑完看 `backend/output/<goods_id>/preview.html` 与 `detail_page.html`。

- Module 05 场景图这一步需要本地 ComfyUI 已启动并加载了 `creative.py` 用到的 Qwen 模型（默认端口 8189），否则该步会失败。若只想验证 01~04，可参考临时脚本 `_test_new_product.py` 借用已生成的旧场景图。
- Module 07 商家后台自动化另需一份商家登录态 `merchant_cookies.txt`（见 `merchant_publisher.py` / `_explore_merchant.py`），且必须用**有头浏览器 + `new_stealth_context()`**，无头模式会触发滑块验证（`DM.md §16`）。

## 如何测试

**当前没有自动化测试套件**（没有 `tests/` 目录，没有 pytest 配置）。验证方式一直是"拿一条真实商品链接跑 `run_pipeline.py`，肉眼审核 `preview.html`"，以及 `_test_*.py` / `_explore_*.py` 这类**一次性临时脚本**（文件头明确写了"用完即删"，不是长期测试资产，不要依赖它们）。

> 待作者补充：是否要引入正式的自动化测试（pytest 等）、以及 CI 流程。

## 关键约定

- **模块编号即文档编号**：`pdd_agent/` 每个文件顶部 docstring 都标了对应的 `Module NN` 和 `DM.md` 章节，改代码前先读对应章节和该文件 docstring 里记录的坑。
- **注释/文档用中文**，且信息密度很高——很多"为什么这么写"的关键约束都写在 docstring 和行内注释里（例如为什么参考图筛选放宽到 `product|model`、为什么图片分类 `type!="product"` 就强制 DROP），改动前务必读完再动。
- **文本凭证与图像凭证分开**：同一个中转 key 不保证文本和图像权限都有，`config.py` 拆成 `text_*` / `image_*` 两套，别合并。
- **抓取逻辑是易碎的**：`importer.py` 靠抓公开页面，页面改版/反爬升级随时会失效（`DM.md §10.2`），别把它当稳定基础设施。
- **临时脚本命名**：探索/一次性脚本用 `_` 前缀（`_explore_*.py`、`_test_*.py`），产物 `_run_log.txt`、`_explore_*.png` 等同理。
- 分支/提交规范：仓库目前只有一个初始提交，尚无成文的分支或 commit message 约定。
  > 待作者补充：分支命名、commit 规范、PR 流程。

## 环境变量

**⚠️ `backend/.env.example` 已过时**：它只列了 `OPENAI_IMAGE_*` / `OPENAI_TEXT_*` / `PDD_AGENT_OUTPUT_DIR`，但代码（`config.py`）实际读取的变量更多（ComfyUI、人设、采购参数等都缺失）。建议作者补齐 `.env.example`。以下是 `config.py` 真实读取的全部变量（**不要在文档或提交里写入任何真实 key / token**）：

| 变量 | 用途 | 是否必填 |
|---|---|---|
| `OPENAI_TEXT_API_KEY` | 文本模型（Module 02/03/04）凭证，需 chat/completions 权限 | **必填**（缺失直接报错） |
| `OPENAI_TEXT_BASE_URL` | 文本模型中转地址 | 选填 |
| `OPENAI_TEXT_MODEL` | 文本模型名（默认 `gpt-5`） | 选填 |
| `OPENAI_IMAGE_API_KEY` | 图像凭证（Module 05 已改走本地 ComfyUI，仅 `personas.py` 老路径可能用到） | 选填 |
| `OPENAI_IMAGE_BASE_URL` | 图像中转地址（默认 `https://api.sublyx.org/v1`） | 选填 |
| `OPENAI_IMAGE_MODEL` | 图像模型名（默认 `gpt-image-1`） | 选填 |
| `PDD_AGENT_OUTPUT_DIR` | 产物输出目录（默认 `output`） | 选填 |
| `COMFY_BASE_URL` | 本地 ComfyUI 地址（默认 `http://127.0.0.1:8189`） | 选填 |
| `COMFY_UNET_NAME` / `COMFY_CLIP_NAME` / `COMFY_VAE_NAME` | Z-Image-Turbo 模型文件名 | 选填 |
| `COMFY_QWEN_UNET_NAME` / `COMFY_QWEN_CLIP_NAME` / `COMFY_QWEN_VAE_NAME` | Qwen-Image-Edit-2509 模型文件名（Module 05 实际用的这套） | 选填 |
| `PDD_PERSONA_CODENAME` | 用哪个模特人设跑（默认 `帅帅`，可选 壮壮/土土/憨憨） | 选填 |
| `PDD_PROCUREMENT_MIN_MARGIN_RATE` | 采购最低毛利率（默认 `0.25`） | 选填 |
| `PDD_PROCUREMENT_MIN_MARGIN_ABS` | 采购最低毛利绝对值/元（默认 `8`） | 选填 |
| `PDD_PROCUREMENT_DAILY_SPEND_CAP` | 每日采购总额上限/元（默认 `500`） | 选填 |
| `PDD_PROCUREMENT_CUTOFF_HOUR` | 采购批次 cutoff 小时（默认 `18`，见 `DM.md D1.1`） | 选填 |
| `PDD_LOGIN_STATE_PATH` | 登录态文件路径（`pipeline.py` 读取，默认 `pdd_login_state.json`） | 选填 |

登录态 / cookie 文件（`.env`、`pdd_login_state.json`、`cookies.txt`、`merchant_cookies.txt`）均已在 `.gitignore`，**不要提交**。

## 设计要点 / 坑（从代码与 DM.md 提炼）

- **不做一键全自动发布**：AI 结果必须过人工审核（`preview.html` 左右对比原商品），`DM.md §3.1`。
- **文案"事实锁"**：Module 04 只能引用 Module 02 从原商品提取的 FACTS，禁止编造未验证卖点（`analyzer.py` / `copywriter.py`）。
- **图片分类规则**：`type in (product, text_info)` → KEEP，`type in (model, scene)` → DROP；边界是"有没有真人模特出镜"，不是"有没有文字"（`DM.md §13`，`analyzer.classify_images`）。代码层强制过滤，不完全信 LLM 打标。
- **登录不能全自动**：Playwright 自动化登录会被验证码拦，正规做法是人工在真实浏览器登录一次、复用 cookie（`auth.py`，`DM.md §12 / D1.2`）。
- **商家后台写操作有 `anti-content` 反爬指纹**，裸 HTTP 重放走不通；只能用有头浏览器 + 抹掉 `navigator.webdriver` 的 `new_stealth_context()` 操作真实页面（`DM.md §16`）。**项目明确不研究验证码绕过 / 风控规避**（`DM.md §3.8`），遇验证码一律转人工。
- **模特人设一致性**：图像模型没有 seed，纯文字描述每次生成都是不同的人；靠先生成一张"标准照"当参考图锁一致性，改人设走候选流程（`generate_candidates`→`promote_candidate`），旧版自动备份到 `history/`，避免删了找不回（`personas.py`）。
- **错别字只做文案层文本替换**（`typo_fix.KNOWN_TYPO_FIXES`），图片级自动涂改机制已按用户要求废弃，图片错字人工处理（`DM.md §13`）。
- **利润守卫是资金安全网**：采购下单前用 `procurement.check_profit_guard()` 重新核价，毛利率/绝对值/每日总额三道闸门任一不过就拦截转人工（`DM.md §3.5 / §15`）。
- **采购下单执行故意留空**：`procurement.py` 的真实 `place_order` 是 TODO，涉及真实资金，需用户在场从"只走到支付前一步"的保守版本开始，别自作主张补全（`DM.md §15`）。

> 待作者补充：Module 07 商品属性表单剩余必填项/SKU 表格/运费模板的自动化填写、Module 08 订单中心、Module 10 AI 客服的实现，以及生产部署方案（目前只有本地脚本，无部署配置）。
