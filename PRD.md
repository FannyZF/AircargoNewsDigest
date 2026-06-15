# 空运新闻收集工具 PRD

## 1. 产品概述

### 1.1 产品名称
**AirCargoNews Digest** — 空运新闻日报聚合工具

### 1.2 产品定位
面向空运/航空货运行业从业者的一站式新闻聚合工具，每日自动从指定网站抓取空运相关新闻，通过 Deepseek LLM 完成翻译、摘要、关键词提取，最终生成 HTML 格式的可阅读新闻日报简报。

### 1.3 目标用户
- 空运/航空货运从业者（运营、销售、管理层）
- 供应链/物流行业分析师
- 国际贸易相关人员

---

## 2. 功能需求

### 2.1 新闻采集模块（Web Scraping）

| 功能点 | 优先级 | 描述 |
|--------|--------|------|
| 网页抓取 | P0 | 通过 CSS Selector 抓取新闻列表页，提取标题、链接、发布日期、摘要 |
| 文章正文抓取 | P0 | 进入新闻详情页，抓取完整正文内容 |
| 去重过滤 | P0 | 基于 URL 精确匹配 + 标题相似度去重 |
| 日期筛选 | P0 | 仅保留当日发布的新闻（可配置天数窗口） |
| 站点配置化 | P0 | 通过配置文件管理目标网站及其 CSS 选择器规则，新增源只需加一段配置 |
| 反爬应对 | P1 | 支持 User-Agent 轮换、请求间隔控制、失败重试 |

**默认配置站点：**
1. Air Cargo News — `https://www.aircargonews.net/`
2. Airfreight News — `https://www.airfreight.news/`

### 2.2 LLM 处理模块（Deepseek）

| 功能点 | 优先级 | 描述 |
|--------|--------|------|
| 内容翻译 | P0 | 英文新闻自动翻译为中文标题 + 中文正文 |
| 摘要生成 | P0 | 每条新闻生成 3-5 句话精炼中文摘要 |
| 关键词提取 | P0 | 每条新闻提取 5-10 个中文关键词/标签，用于后续知识库检索 |
| 分类标注 | P1 | LLM 自动将新闻归类（运价/运力/航线/政策/企业动态等） |
| 关键数据提取 | P1 | 提取运价变化、运力变化、航线变动等结构化数值 |
| 批处理与重试 | P0 | 批量处理多条新闻，单条失败不影响其他，自动重试 |

### 2.3 简报生成模块（HTML）

| 功能点 | 优先级 | 描述 |
|--------|--------|------|
| HTML 日报 | P0 | 生成排版精美、响应式的 HTML 日报，浏览器直接打开即可阅读 |
| 头条置顶 | P1 | LLM 自动选出 3-5 条最重要的新闻作为今日头条 |
| 分类展示 | P1 | 按新闻类别分区展示 |
| 关键词标签云 | P2 | 日报底部展示当日所有新闻的关键词标签云 |
| 暗色模式 | P2 | HTML 页面支持亮色/暗色模式切换 |

### 2.4 调度与管理

| 功能点 | 优先级 | 描述 |
|--------|--------|------|
| 定时执行 | P0 | 每日定时自动运行（默认 08:00 UTC+8） |
| 手动触发 | P0 | 支持 CLI 命令手动触发单次运行 |
| 增量运行 | P1 | 记录已抓取 URL，避免重复处理 |
| 日志记录 | P0 | 完整运行日志，含成功/失败/跳过数量统计 |

---

## 3. 技术架构

### 3.1 技术选型

```
语言：     Python 3.10+
爬虫：     httpx + BeautifulSoup4 + lxml
调度：     APScheduler（程序内定时）/ Windows Task Scheduler（系统级）
LLM：      Deepseek API（兼容 OpenAI SDK）
存储：     SQLite
输出：     Jinja2 → HTML 模板
配置：     YAML 配置文件
日志：     Python logging + 文件输出
```

### 3.2 项目结构

```
aircargo-news/
├── config.yaml                # 主配置文件
├── src/
│   ├── __init__.py
│   ├── main.py                # 入口，CLI 命令处理
│   ├── collector/
│   │   ├── __init__.py
│   │   ├── scraper.py         # 通用网页抓取器（CSS Selector）
│   │   └── dedup.py           # 去重逻辑
│   ├── processor/
│   │   ├── __init__.py
│   │   ├── llm_client.py      # Deepseek API 调用封装
│   │   └── pipeline.py        # 处理管线（翻译→摘要→关键词→分类）
│   ├── reporter/
│   │   ├── __init__.py
│   │   ├── digest.py          # 日报数据组装
│   │   └── templates/
│   │       └── daily.html.j2  # HTML 日报模板
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── cron.py            # 定时调度器
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── db.py              # SQLite 操作
│   │   └── models.py          # 数据模型定义
│   └── utils/
│       ├── __init__.py
│       └── logger.py          # 日志工具
├── output/                    # 日报输出目录
├── data/
│   └── news.db                # SQLite 数据库文件
└── logs/                      # 日志文件
```

### 3.3 数据流

```
[aircargonews.net]  ──┐
                       ├──→ [网页抓取] ──→ [去重 + 日期过滤] ──→ [原始新闻入库]
[airfreight.news]   ──┘                                              │
                                                                     ▼
                                                     [Deepseek LLM 管线]
                                                     ├── 翻译（英→中）
                                                     ├── 摘要生成
                                                     ├── 关键词提取
                                                     └── 分类标注
                                                                     │
                                                                     ▼
                                                             [处理后存储]
                                                                     │
                                                                     ▼
                                                     [HTML 模板渲染] ──→ [output/daily_2026-06-15.html]
```

### 3.4 数据模型

```
NewsItem:
    id              TEXT PRIMARY KEY (UUID)
    url             TEXT UNIQUE NOT NULL
    title           TEXT NOT NULL
    original_text   TEXT              -- 原文正文
    source          TEXT NOT NULL     -- 来源网站名称
    published_at    TEXT              -- 原文发布日期
    collected_at    TEXT NOT NULL     -- 抓取时间

    translated_title  TEXT            -- 中文标题
    translated_text   TEXT            -- 中文正文
    summary           TEXT            -- 中文摘要（3-5句）
    keywords          TEXT            -- JSON数组: ["空运运价","中美航线",...]
    category          TEXT            -- 分类编号: 1-运价 2-运力 3-航线 ...
    china_relevance   TEXT            -- 中国关联度: high | medium | low | none
    china_angle       TEXT            -- 与中国市场的关联点说明

    status          TEXT DEFAULT 'pending'   -- pending | processed | failed | skipped
    processed_at    TEXT
    error_message   TEXT
```

---

## 4. 配置文件示例

```yaml
# config.yaml

# ==================== 新闻源配置 ====================
sources:
  - name: "Air Cargo News"
    base_url: "https://www.aircargonews.net/"
    list_url: "https://www.aircargonews.net/"       # 新闻列表页 URL
    enabled: true
    # CSS 选择器配置（根据实际网页结构调整）
    selectors:
      list_container: "article.post"                 # 列表中每条新闻的外层容器
      title: "h2.entry-title a"                      # 标题链接元素
      link: "h2.entry-title a"                       # 链接（取 href）
      date: "time.entry-date"                        # 日期元素（取 datetime 属性或文本）
      summary: "div.entry-content p"                 # 列表页摘要（可选）
    # 详情页选择器
    article_selector:
      content: "div.entry-content"                   # 正文内容容器

  - name: "Airfreight News"
    base_url: "https://www.airfreight.news/"
    list_url: "https://www.airfreight.news/"
    enabled: true
    selectors:
      list_container: "article"
      title: "h2.entry-title a"
      link: "h2.entry-title a"
      date: "time.entry-date"
      summary: "div.entry-summary"
    article_selector:
      content: "div.entry-content"

  # ==== 新增来源只需在此追加即可 ====
  # - name: "新的来源"
  #   base_url: "https://..."
  #   list_url: "https://..."
  #   enabled: true
  #   selectors:
  #     ...

# ==================== LLM 配置 ====================
llm:
  provider: "deepseek"
  model: "deepseek-chat"                  # deepseek-chat | deepseek-reasoner
  api_key: "${DEEPSEEK_API_KEY}"          # 支持环境变量
  base_url: "https://api.deepseek.com"    # Deepseek API 地址
  temperature: 0.3
  max_tokens: 4096
  batch_size: 5                           # 每批处理条数（控制并发）

# ==================== LLM Prompt（内置在 llm_client.py） ====================
# System Prompt 包含：翻译规则、术语字典、中国关联度判断、关键词提取要求
# User Prompt 模板包含：标题、来源、链接、正文
# 输出 JSON：translated_title, translated_text, summary, keywords, category, china_relevance, china_angle

# ==================== 调度配置 ====================
schedule:
  enabled: true
  time: "08:00"                          # 每天执行时间
  timezone: "Asia/Shanghai"

# ==================== 输出配置 ====================
output:
  dir: "./output"                        # 日报输出目录
  filename_pattern: "daily_{date}.html"  # 文件名格式
  keep_days: 30                          # 保留最近 N 天

# ==================== 抓取配置 ====================
scraping:
  request_interval: 2                    # 请求间隔（秒）
  user_agents:                           # UA 池
    - "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ..."
  timeout: 30                            # 请求超时（秒）
  max_retries: 3                         # 失败重试次数
```

---

## 5. CLI 命令设计

```bash
# 完整流程：抓取 + LLM处理 + 生成HTML日报
python -m src.main run

# 仅抓取新闻列表（不入库处理）
python -m src.main collect

# 仅对已抓取新闻执行 LLM 处理
python -m src.main process

# 仅从已处理新闻生成 HTML 日报
python -m src.main report

# 启动定时调度（后台持续运行，到点自动执行）
python -m src.main schedule

# 生成默认配置文件
python -m src.main init
```

---

## 6. HTML 日报设计

### 6.1 页面结构

```
┌──────────────────────────────────────┐
│  空运新闻日报                        │
│  2026年6月15日 | 共收录 12 条新闻     │
│  [亮色 / 暗色]                       │
├──────────────────────────────────────┤
│  ★ 今日头条 (3-5条)                  │
│  ┌────────────────────────────────┐  │
│  │ 标题 | 来源 | 标签: xxx, xxx   │  │
│  │ 摘要内容...                    │  │
│  │ [原文链接] [展开全文]          │  │
│  └────────────────────────────────┘  │
├──────────────────────────────────────┤
│  ■ 运价与运力                        │
│  ...卡片列表...                      │
├──────────────────────────────────────┤
│  ■ 航线动态                          │
│  ...卡片列表...                      │
├──────────────────────────────────────┤
│  ■ 企业动态                          │
│  ...卡片列表...                      │
├──────────────────────────────────────┤
│  ■ 其他新闻                          │
│  ...卡片列表...                      │
├──────────────────────────────────────┤
│  ☁ 今日关键词标签云                  │
│  [空运运价] [中美航线] [货机]        │
│  [DHL] [IATA] [跨境电商] ...         │
├──────────────────────────────────────┤
│  由 AirCargoNews Digest 自动生成     │
│  数据处理: Deepseek                   │
└──────────────────────────────────────┘
```

### 6.2 设计要点
- **卡片式布局**：每条新闻独立卡片，含标题、标签、摘要、来源、原文链接
- **响应式设计**：桌面/平板/手机均可阅读
- **内联 CSS**：单 HTML 文件，无需外部依赖，离线可读
- **懒加载**：正文内容点击展开，减少初始页面体积
- **标签云**：当日所有关键词汇总，字号按频率变化

---

## 7. 实施路线图

| 阶段 | 内容 | 优先级 |
|------|------|--------|
| **Phase 1** | 两个默认源的网页抓取 + SQLite 存储 + 去重 + 日期过滤 | P0 |
| **Phase 2** | Deepseek LLM 集成：翻译 + 摘要 + 关键词 + 分类（一次性调用） | P0 |
| **Phase 3** | HTML 日报模板 + 生成器 + 标签云 | P0 |
| **Phase 4** | 定时调度 + 手动触发 CLI | P0 |
| **Phase 5** | 反爬增强 + 头条提炼 + 暗色模式 | P1 |
| **Phase 6** | 知识库导出接口（预留） | P2 |

---

## 8. 非功能需求

- **可靠性**：单个源抓取失败不影响其他源
- **成本控制**：每条新闻通过一次 LLM 调用完成翻译+摘要+关键词+分类，减少 token 消耗
- **易扩展**：新增新闻源只需在 config.yaml 的 sources 列表追加一段配置
- **关键词留存**：每条新闻的关键词存入 SQLite，后续可导出到知识库系统

---

## 9. 关键设计决策记录

| 决策项 | 决策 | 原因 |
|--------|------|------|
| 抓取方式 | 纯网页抓取（不用 RSS） | 用户偏好，RSS 内容常不完整 |
| LLM 选型 | Deepseek | 性价比高，中文能力强，兼容 OpenAI SDK |
| LLM 调用策略 | 单次调用完成所有处理 | 减少 token 消耗和延迟，通过结构化 JSON 输出 |
| 输出格式 | HTML（优先） | 排版丰富，浏览器直接打开，无需额外工具 |
| 存储方案 | SQLite | 轻量零配置，单文件，适合本地工具 |
| 关键词用途 | 存入数据库，预留导出 | 为后续知识库/向量检索做准备 |
