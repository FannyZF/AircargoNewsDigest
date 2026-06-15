import json
import re

from openai import OpenAI

from src.utils.logger import setup_logger
from src.utils.key_store import get_api_key

logger = setup_logger("llm")


SYSTEM_PROMPT = """你是一名资深的航空货运行业新闻编辑，拥有10年以上行业经验，尤其熟悉中国空运市场。
你的任务是对英文空运新闻进行处理，返回结构化JSON。

## 核心能力
- 精准翻译航空货运专业术语（belly cargo 腹舱货运、freighter 全货机、yield 运价收益、load factor 载运率、block space agreement 包板协议、general cargo 普货、special cargo 特种货）
- 提炼新闻中的关键数据和事实
- 识别行业相关实体和主题
- 判断新闻涉及的地理区域

## 中国空运行业背景知识

### 主要航司
- 中国内地：顺丰航空(SF Airlines)、中国国际货运航空(Air China Cargo)、中国南方航空货运(China Southern Cargo)、中国东方航空物流(China Eastern Logistics)、中州航空(Central Airlines)、邮政航空(China Postal Airlines)、圆通航空(YTO Cargo)
- 香港/台湾：国泰货运(Cathay Pacific Cargo)、香港航空货运(Hong Kong Air Cargo)、华航货运(China Airlines Cargo)、长荣航空货运(EVA Air Cargo)

### 主要货运枢纽
- 内地：上海浦东(PVG)、广州白云(CAN)、深圳宝安(SZX)、北京首都(PEK)、郑州新郑(CGO)、杭州萧山(HGH)、成都天府(TFU)、鄂州花湖(EHU)
- 港澳台：香港(HKG)、台北桃园(TPE)

### 关键行业趋势
- 跨境电商：SHEIN、Temu、TikTok Shop 驱动空运需求
- 鄂州花湖机场：全球第四个、亚洲第一个专业货运枢纽
- 运价指数：TAC Index 上海出港、波罗的海空运指数(BAI)

## 输出要求
严格按照以下JSON格式输出，不要包含markdown代码块标记，直接返回纯JSON：

{
  "translated_title": "准确流畅的中文标题，保留核心数据",
  "translated_text": "忠实原文的中文翻译，专业术语准确",
  "summary": "3-5句话的中文摘要，包含：事件、主体、数据、影响",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "categories": ["分类编号1", "分类编号2"],
  "regions": ["区域1", "区域2"]
}

## 区域体系（regions字段，可多选）
选择新闻涉及的地理区域：
- China（涉及中国内地、香港、澳门、台湾的航司/机场/市场）
- Asia（日本、韩国、东南亚、南亚、中亚，不含中国）
- Europe（欧洲各国）
- NorthAmerica（美国、加拿大、墨西哥）
- SouthAmerica（中南美洲）
- MiddleEast（中东地区）
- Africa（非洲各国）
- Oceania（澳大利亚、新西兰、太平洋岛国）
- Global（全球性趋势/报告/组织，不特指某一区域）

示例：
- 新闻讲国泰货运新增航线 → ["China", "Asia"]
- 新闻讲Lufthansa Cargo欧洲内部 → ["Europe"]
- 新闻讲IATA全球货运数据 → ["Global"]
- 新闻讲DHL中美航线运价 → ["China", "NorthAmerica"]

## 关键词要求
- 严格控制在5个
- 优先提取：航司名称、机场、航线、货物品类、行业术语
- 涉及中国时必须包含中文关键词

## 分类体系（categories字段，可多选）
1-运价  2-运力  3-航线  4-政策法规  5-企业动态  6-市场报告  7-技术与可持续  8-其他

## 翻译原则
- 航司名称：首次英文+中文，如 "Lufthansa Cargo 汉莎货运航空"
- 中国公司：使用官方中文名，"顺丰航空"非"SF航空"
- 机场代码：首次注明城市，"上海浦东国际机场(PVG)"
- 数据单位：转公制，必要时附人民币
- 英文人名保留原文"""


class LLMClient:
    def __init__(self, config: dict):
        llm_cfg = config.get("llm", {})
        api_key = get_api_key(config)

        self.client = OpenAI(
            api_key=api_key,
            base_url=llm_cfg.get("base_url", "https://api.deepseek.com"),
        )
        self.model = llm_cfg.get("model", "deepseek-chat")
        self.temperature = llm_cfg.get("temperature", 0.3)
        self.max_tokens = llm_cfg.get("max_tokens", 4096)

    def process_news(self, title: str, content: str, url: str = "", source: str = "") -> dict | None:
        user_prompt = f"""## 待处理新闻

**原文标题：**
{title}

**原文来源：**
{source}

**原文链接：**
{url}

**原文正文：**
{content}

---
请处理以上新闻，直接返回JSON。"""

        for attempt in range(3):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                raw = resp.choices[0].message.content.strip()

                json_match = re.search(r"\{.*\}", raw, re.DOTALL)
                if json_match:
                    raw = json_match.group(0)

                result = json.loads(raw)

                required = ["translated_title", "translated_text", "summary", "keywords", "categories", "regions"]
                for field in required:
                    if field not in result:
                        raise ValueError(f"Missing field: {field}")

                valid_cats = {"1", "2", "3", "4", "5", "6", "7", "8"}
                result["categories"] = [c for c in result.get("categories", []) if c in valid_cats]
                if not result["categories"]:
                    result["categories"] = ["8"]

                valid_regions = {"China", "Asia", "Europe", "NorthAmerica", "SouthAmerica", "MiddleEast", "Africa", "Oceania", "Global"}
                result["regions"] = [r for r in result.get("regions", []) if r in valid_regions]
                if not result["regions"]:
                    result["regions"] = ["Global"]

                if not isinstance(result.get("keywords"), list):
                    result["keywords"] = []
                result["keywords"] = result["keywords"][:5]

                return result

            except json.JSONDecodeError:
                logger.warning("JSON parse failed (attempt %d/3), retrying...", attempt + 1)
                continue
            except Exception as e:
                logger.error("LLM call failed (attempt %d/3): %s", attempt + 1, e)
                if attempt < 2:
                    continue
                return None

        return None
