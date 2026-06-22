# 空运新闻速递 — 产品需求文档 (PRD)

> 版本: v2.2 | 更新: 2026-06-16

---

## 1. 产品概述

### 1.1 产品名称
**空运新闻速递** (AirCargoNews Digest)

### 1.2 一句话描述
面向空运行业的全自动新闻聚合工具 — 每日从指定网站抓取英文新闻，通过 Deepseek LLM 翻译为中文并生成摘要/关键词/区域标注，最终以邮件和 HTML 日报形式分发给订阅者。

### 1.3 核心价值
| 痛点 | 解决方案 |
|------|---------|
| 英文新闻阅读门槛高 | LLM 全量翻译为专业中文 |
| 信息过载，难以筛选 | 5 个关键词 + 多级分类 + 区域标注 |
| 每天手动查阅多个网站 | 全自动定时抓取 + 邮件推送 |
| 缺乏中国视角 | 内嵌中国空运行业知识库 Prompt |

---

## 2. 系统架构

### 2.1 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| 爬虫 | httpx + BeautifulSoup4 + lxml |
| Web 框架 | FastAPI + Jinja2 |
| LLM | Deepseek v4-flash (兼容 OpenAI SDK) |
| 调度 | APScheduler |
| 存储 | SQLite |
| 邮件 | smtplib (SMTP_SSL) |
| 部署 | Docker + docker-compose |

### 2.2 项目结构

```
AircargoNewsDigest/
├── config.yaml                 # 新闻源 + LLM + 抓取配置
├── Dockerfile                  # Docker 镜像
├── docker-compose.yml          # 双端口 + volume 挂载
├── requirements.txt
├── src/
│   ├── main.py                 # CLI 入口 + 双端口启动 + 定时器
│   ├── collector/
│   │   ├── scraper.py          # 通用 CSS Selector 抓取器 + 分页回溯
│   │   └── dedup.py            # URL 去重 + 标题相似度 + 日期过滤
│   ├── processor/
│   │   ├── llm_client.py       # Deepseek API + System Prompt (含中国知识库)
│   │   └── pipeline.py         # 批量处理管线 (翻译/摘要/关键词/分类/区域/核心句)
│   ├── reporter/
│   │   ├── digest.py           # 按来源分组 → HTML 日报生成
│   │   └── templates/daily.html.j2  # Apple 风格 HTML 模板
│   ├── scheduler/
│   │   └── cron.py             # 每日定时调度 (可配置时间)
│   ├── storage/
│   │   ├── models.py           # NewsItem 数据模型
│   │   └── db.py               # SQLite CRUD + 自动迁移
│   ├── web/
│   │   ├── app.py              # FastAPI 全功能 App + 公开订阅 App
│   │   └── templates/          # base / index / history / search / admin / settings / sources / subscribe / standalone_sub
│   └── utils/
│       ├── logger.py           # 日志工具
│       ├── key_store.py        # API Key 持久化 (data/api_key.json)
│       ├── schedule_store.py   # 定时时间持久化 (data/schedule.json)
│       ├── subscription_store.py  # 订阅者管理 (data/subscribers.json)
│       └── mailer.py           # SMTP 邮件发送
├── output/                     # 历史日报 HTML 文件
├── data/                       # SQLite + JSON 数据
└── logs/                       # 运行日志
```

### 2.3 双端口架构

| 端口 | 用途 | 公开性 |
|------|------|--------|
| **18903** | 订阅页面 `/s` + 公开 API | 公网开放 |
| **18913** | 日报/历史/搜索/管理/设置/来源 | 管理员专用 (建议防火墙限制) |

18903 只加载一个轻量 FastAPI App，仅含订阅相关路由，不暴露任何内部功能。

### 2.4 数据流

```
[aircargonews.net] ──┐
                      ├─→ 网页抓取 ─→ 去重+日期过滤 ─→ SQLite (status=pending)
[airfreight.news]  ──┘                                        │
                                                               ▼
                                              Deepseek LLM 单次调用:
                                              ├─ 英文→中文翻译
                                              ├─ 3-5句摘要
                                              ├─ 2-3句核心原文句 (core_extract)
                                              ├─ 5个关键词
                                              ├─ 多分类标注 (运价/运力/航线/...)
                                              └─ 区域标注 (中国/亚洲/欧洲/...)
                                                               │
                                                               ▼
                                                      SQLite (status=processed)
                                                               │
                                               ┌───────────────┴───────────────┐
                                               ▼                               ▼
                                    生成 HTML 日报 (output/)          邮件群发给订阅者
                                    (按来源分组, 日期偏移-1天)        (SMTP, 每天定时)
```

---

## 3. 数据模型

### 3.1 NewsItem

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PK (UUID) | 唯一标识 |
| url | TEXT UNIQUE | 原文链接 |
| title | TEXT | 英文原标题 |
| original_text | TEXT | 原文正文 |
| source | TEXT | 来源网站名称 |
| published_at | TEXT | 原文发布日期 |
| collected_at | TEXT | 抓取时间 |
| translated_title | TEXT | 中文标题 |
| translated_text | TEXT | 中文全文翻译 |
| summary | TEXT | 3-5 句中文摘要 |
| core_extract | TEXT | 2-3 句原文核心句 (翻译) |
| keywords | TEXT (JSON) | 5 个中文关键词 |
| categories | TEXT (JSON) | 分类编号数组 |
| regions | TEXT (JSON) | 区域数组 |
| status | TEXT | pending / processed / failed / skipped |
| processed_at | TEXT | LLM 处理时间 |
| error_message | TEXT | 失败原因 |

### 3.2 分类体系
1-运价  2-运力  3-航线  4-政策法规  5-企业动态  6-市场报告  7-技术与可持续  8-其他

### 3.3 区域体系
China / Asia / Europe / NorthAmerica / SouthAmerica / MiddleEast / Africa / Oceania / Global

---

## 4. LLM Prompt 设计

### 4.1 设计原则
- **单次调用完成全部处理**：一次 API 调用返回翻译+摘要+核心句+关键词+分类+区域，减少 token 消耗
- **结构化 JSON 输出**：强制 JSON 格式，正则提取兜底，避免 LLM 自由发挥
- **中国行业知识内嵌**：System Prompt 包含中国航司/机场/航线白名单 + 跨境电商等行业趋势
- **正反例示例**：关键词和分类同时给出正确和错误示例，引导 LLM 输出质量

### 4.2 输出字段

| 字段 | 要求 |
|------|------|
| translated_title | 保留核心数据的中文标题 |
| translated_text | 专业术语准确的全文翻译 |
| summary | 3-5 句，含事件+主体+数据+影响 |
| core_extract | 从原文摘取 2-3 句最核心原句并翻译 |
| keywords | 严格 5 个，优先行业实体 |
| categories | 可多选分类编号 |
| regions | 可多选区域代码 |

---

## 5. Web 前端

### 5.1 页面清单

| 路径 | 页面 | 功能 |
|------|------|------|
| `/` | 日报首页 | 今日日报, 三维筛选侧边栏 |
| `/history` | 历史日报 | 按日期归档, 查看/删除/重新生成/推送 |
| `/search` | 搜索 | 关键词+分类+区域组合搜索 |
| `/sources` | 来源管理 | 自动探测 CSS 选择器 + 手动添加/删除 |
| `/subscribe` | 订阅管理 | 订阅/退订 + 订阅者列表 |
| `/admin` | 管理后台 | 统计 + 重启 + 高级操作(默认隐藏) |
| `/settings` | 设置 | API Key / 定时时间 / SMTP 配置 |
| `/s` | 独立订阅页 | 无导航栏, 适合微信嵌入 |

### 5.2 日报页交互

**左侧三维筛选 (客户端 DOM 过滤)**:
- **来源** — 按新闻网站过滤 (去重计数)
- **内容分类** — 8 个分类可选
- **区域** — 9 个地理区域可选
- 三者叠加 ⇒ 取交集
- 选中后隐藏分类板块标题, 平铺展示
- 顶部显示激活的筛选标签, 可单独移除

**每张新闻卡片**:
```
┌─ 标题 (链接到原文) ─────────────────────┐
│ 来源  Air Cargo News    2026-06-15     │
│ 分类  [运价] [航线]                     │
│ 区域  [中国] [亚洲]                     │
│                                         │
│ 摘要: IATA最新数据显示...               │
│                                         │
│ ▌ 新闻核心                              │
│ ▌ 国泰货运新增香港-芝加哥全货机航线...    │
│ ▌ 每周三班, 由B747-8F执飞              │
│                                         │
│ [关键词1] [关键词2] [关键词3] ...        │
│ [展开全文 ▼]                            │
└─────────────────────────────────────────┘
```

### 5.3 设计风格 (Apple-inspired)
- 毛玻璃导航栏 (`backdrop-filter: blur(20px)`)
- 18px 大圆角卡片 + 微阴影 + 悬停上浮动效
- SF Pro 字体优先, 自动跟随系统暗色模式
- 胶囊按钮 (20px 圆角)
- 紫色=来源, 绿色=分类, 蓝色=区域, 红色=中国

---

## 6. 邮件订阅

### 6.1 订阅方式
- **独立页面**: `http://IP:18903/s` (移动端友好)
- **API**: `GET /api/public/subscribe?email=xxx` (跨域支持)
- **公众号**: 菜单跳转链接

### 6.2 发送机制
- 每天定时任务完成后, 查找昨日日期的 HTML 文件
- 通过 SMTP_SSL 群发给所有活跃订阅者
- 支持手动推送: 历史页面 → 推送按钮
- SMTP 配置在设置页面 (存入 data/smtp_config.json)

### 6.3 数据存储
- `data/subscribers.json`: `[{"email": "...", "active": true}]`
- `data/smtp_config.json`: SMTP 服务器配置

---

## 7. 来源管理

### 7.1 配置结构
```yaml
sources:
  - name: "Air Cargo News"
    base_url: "https://www.aircargonews.net"
    list_url: "https://www.aircargonews.net/"
    enabled: true
    selectors:
      list_container: "article.summary"
      title: "span.post-title"
      link: "a"
      date: "time.pubdate"
      date_attr: "datetime"
      summary: "p.excerpt"
    article_selector:
      content: "div.entry-content"
    pagination:
      pattern: "/page/{page}/"
      start: 1
```

### 7.2 自动探测
用户只需输入网站首页 URL，系统自动分析 HTML 结构：
1. 搜索含常见类名 (post/article/news/card/media) 的容器元素
2. 选择包含最多链接和日期元素的容器
3. 自动识别标题/日期/摘要的 CSS 选择器
4. 自动发现分页规律
5. 将识别结果自动填入配置表单

---

## 8. 定时调度

### 8.1 执行流程
```
用户设定时间 (如 08:00)
  → 抓取各源新闻列表 (lookback_days 内)
  → 进入详情页抓取正文
  → 去重入库 (status=pending)
  → LLM 批量处理 (status=processed)
  → 生成 HTML 日报 (output/daily_YYYY-MM-DD.html)
  → 邮件发送给订阅者
```

### 8.2 日期偏移
由于新闻源多为欧美网站，北京时间早上抓取到的是前一天的新闻。每日日报的文件名和显示日期自动使用 **昨日** 日期 (即新闻实际发生日)。

### 8.3 手工操作 (管理页面)
- **抓取新闻**: 仅抓取不入库
- **LLM 处理**: 处理待处理队列
- **生成日报**: 生成今日日报
- **一键全流程**: 以上三步依次执行
- **历史回溯**: 从 2026-05-01 起翻页抓取

---

## 9. 部署

### 9.1 Docker 部署
```bash
git clone https://github.com/FannyZF/AircargoNewsDigest.git
cd AircargoNewsDigest
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY
docker compose up -d --build
```

### 9.2 Docker Compose 配置要点
```yaml
ports:
  - "18903:18903"     # 公开订阅端口
  - "18913:18913"     # 管理端口
volumes:
  - ./data:/app/data       # SQLite + JSON 持久化
  - ./output:/app/output   # 日报文件持久化
  - ./logs:/app/logs
  - ./config.yaml:/app/config.yaml  # 可写 (来源管理需修改)
restart: unless-stopped      # 崩溃自动重启 + 开机自启
environment:
  - TZ=Asia/Shanghai
```

---

## 10. 配置持久化

所有运行时配置均存储在 `data/` 目录下，不依赖 config.yaml：

| 文件 | 内容 | 设置入口 |
|------|------|---------|
| data/api_key.json | Deepseek API Key | 设置页面 |
| data/schedule.json | 每日定时时间 | 设置页面 |
| data/subscribers.json | 邮件订阅者列表 | 订阅页面 |
| data/smtp_config.json | SMTP 服务器配置 | 设置页面 |
| data/news.db | SQLite 新闻数据库 | 自动 |

这样 config.yaml 变更不会覆盖运行时配置，Docker volume 挂载保证重启不丢失。

---

## 11. CLI 命令

| 命令 | 功能 |
|------|------|
| `python -m src.main web` | 启动 Web 服务 (双端口 + 定时器) |
| `python -m src.main run` | 单次全流程 (抓取→处理→生成) |
| `python -m src.main collect` | 仅抓取 |
| `python -m src.main process` | 仅 LLM 处理 |
| `python -m src.main report` | 仅生成日报 |
| `python -m src.main backfill` | 历史回溯 (翻页至 5/1) |
| `python -m src.main schedule` | 独立定时器 (不启动 Web) |
| `python -m src.main init` | 生成默认 config.yaml |
