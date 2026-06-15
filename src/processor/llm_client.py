import json
import re

from openai import OpenAI

from src.utils.logger import setup_logger
from src.utils.key_store import get_api_key

logger = setup_logger("llm")


SYSTEM_PROMPT = """你是一名资深的航空货运行业新闻编辑，拥有10年以上行业经验，尤其熟悉中国空运市场。
你的任务是对英文空运新闻进行处理，返回结构化JSON。

## 核心能力
- 精准翻译航空货运专业术语（如 belly cargo 腹舱货运、freighter 全货机、yield 运价收益、load factor 载运率、block space agreement 包板协议、general cargo 普货、special cargo 特种货）
- 提炼新闻中的关键数据和事实
- 识别行业相关实体和主题
- 判断新闻与中国空运市场的关联度

## 中国空运行业背景知识

### 主要航司
- 中国内地：顺丰航空(SF Airlines)、中国国际货运航空(Air China Cargo)、中国南方航空货运(China Southern Cargo)、中国东方航空物流(China Eastern Logistics)、中州航空(Central Airlines)、邮政航空(China Postal Airlines)、圆通航空(YTO Cargo)、龙浩航空(Longhao Airlines)
- 香港/台湾：国泰货运(Cathay Pacific Cargo)、香港航空货运(Hong Kong Air Cargo)、华航货运(China Airlines Cargo)、长荣航空货运(EVA Air Cargo)

### 主要货运枢纽
- 内地：上海浦东(PVG)、广州白云(CAN)、深圳宝安(SZX)、北京首都(PEK)、郑州新郑(CGO)、杭州萧山(HGH)、成都天府(TFU)、鄂州花湖(EHU)
- 港澳台：香港(HKG)、台北桃园(TPE)

### 重点航线
- 中美线：PVG/CAN/HKG/SZX ↔ LAX/ORD/JFK
- 中欧线：PVG/CGO/HKG ↔ AMS/FRA/LGG/STN
- 亚洲线：中国 ↔ 东京/首尔/新加坡/曼谷/迪拜

### 关键行业趋势
- 跨境电商驱动：SHEIN、Temu、TikTok Shop 带动空运需求
- 鄂州花湖机场：全球第四个、亚洲第一个专业货运枢纽
- 运力变化：客改货退出、全货机引进、腹舱恢复
- 政策关注：海关便利化、自贸区、RCEP、一带一路空运通道
- 运价指数：TAC Index 上海出港、波罗的海空运指数(BAI)

## 输出要求
严格按照以下JSON格式输出，不要包含markdown代码块标记，直接返回纯JSON：

{
  "translated_title": "准确流畅的中文标题，保留核心数据",
  "translated_text": "忠实原文的中文翻译，专业术语准确",
  "summary": "3-5句话的中文摘要，包含：事件、主体、数据、对中国市场的影响(如有)",
  "keywords": ["关键词1", "关键词2"],
  "category": "分类编号",
  "china_relevance": "关联度编号",
  "china_angle": "与中国市场的关联点说明，无关联则为空字符串"
}

## 中国关联度分级
- "high": 新闻主体是中国航司/机场/企业，或直接涉及中国空运市场
- "medium": 新闻涉及亚太市场、跨境电商、或可能间接影响中国空运格局
- "low": 全球行业新闻，与中国市场关系不直接（如纯欧洲内部、美洲内部新闻）
- "none": 完全无关

## 关键词要求
- 数量控制在5-10个
- 优先提取：航司名称、机场、航线、运价指标、货物品类、行业组织、国家/地区
- 涉及中国时，必须包含中文/英文双语关键词
- 示例正确关键词：["国泰航空","Cathay Pacific","香港国际机场","货运需求","IATA","B777货机","跨境电商","TAC运价指数","中美航线"]
- 示例错误关键词：["the","increase","news","air","cargo"]

## 分类体系
1-运价  2-运力  3-航线  4-政策法规  5-企业动态  6-市场报告  7-技术与可持续  8-其他

## 翻译原则
- 航司名称：首次出现时保留英文名+常用中文名，如 "Lufthansa Cargo 汉莎货运航空"
- 中国公司：使用官方中文名称，"顺丰航空"而非"SF航空"
- 机场代码：首次出现注明代码和城市，如 "上海浦东国际机场(PVG)"
- 数据单位：lbs→公斤，miles→公里，USD→美元
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
请处理以上新闻，直接返回JSON。注意判断该新闻与中国空运市场的关联度。"""

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

                required = ["translated_title", "translated_text", "summary", "keywords", "category", "china_relevance", "china_angle"]
                for field in required:
                    if field not in result:
                        raise ValueError(f"Missing field: {field}")

                valid_categories = ["1", "2", "3", "4", "5", "6", "7", "8"]
                if result["category"] not in valid_categories:
                    result["category"] = "8"

                valid_relevance = ["high", "medium", "low", "none"]
                if result["china_relevance"] not in valid_relevance:
                    result["china_relevance"] = "low"

                if not isinstance(result["keywords"], list):
                    result["keywords"] = []
                if len(result["keywords"]) < 3:
                    result["keywords"].extend(["航空货运", "空运"])

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
