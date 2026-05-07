"""
小红书爆款标题生成引擎
模式1：文案取标题 — 从完整文案中提炼标题
模式2：视频配标题 — 根据视频方向生成标题
知识库：从 ./knowledge 目录读取产品知识文件，支持 KB_DIR 环境变量覆盖
"""

import re
import os
import json
from pathlib import Path
from openai import OpenAI

# ============================================================
# 路径 & 产品配置（动态加载，不再硬编码）
# ============================================================

_PROJECT_DIR = Path(__file__).parent


def get_kb_dir():
    """知识库目录：优先 KB_DIR 环境变量，否则项目内 ./knowledge"""
    return os.getenv("KB_DIR", str(_PROJECT_DIR / "knowledge"))


def _load_products_config():
    """从 knowledge/products.json 加载产品配置，失败时硬编码兜底"""
    config_path = Path(get_kb_dir()) / "products.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "bzu": {"name": "研生之力超能B族", "file": "product-info.md"},
        "ctj": {"name": "研生之力巢天娇", "file": "product-info-ctj.md"},
    }


def get_product_list():
    """返回产品列表 [{id, name, file}]"""
    config = _load_products_config()
    return [{"id": pid, "name": cfg["name"], "file": cfg["file"]} for pid, cfg in config.items()]


def _get_product_names():
    return {pid: cfg["name"] for pid, cfg in _load_products_config().items()}


def _get_product_files():
    return {pid: cfg["file"] for pid, cfg in _load_products_config().items()}


# ============================================================
# 知识库加载
# ============================================================


def _load_product_context(product_id):
    """加载单个产品的知识库内容"""
    product_files = _get_product_files()
    filename = product_files.get(product_id)
    if not filename:
        return _fallback_context(product_id)
    filepath = Path(get_kb_dir()) / filename
    if not filepath.exists():
        return _fallback_context(product_id)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()[:2500]
    except Exception:
        return _fallback_context(product_id)


def _fallback_context(product_id):
    product_names = _get_product_names()
    name = product_names.get(product_id, "未知产品")
    if product_id == "bzu":
        return f"""
产品：{name}（B族维生素保健食品）
核心卖点：8种B族全配齐 + 胆碱护肝 + 肌醇助代谢 + 专利PQQ抗氧化（维C的5000倍）
五维养护：头发、皮肤、身材、精力、免疫
食用方式：每天早饭后随餐1粒
目标人群：打工人、熬夜党、外卖党、身材管理者、油痘肌、30+女性
"""
    elif product_id == "ctj":
        return f"""
产品：{name}（肌醇保健食品，卵巢养护）
核心卖点：40:1黄金肌醇比例（Myo-肌醇:D-手性肌醇），与健康成年女性血浆天然比例一致 + 高纯度专利PQQ抗氧化（维C的5000倍）
定位：非激素，身体天然存在的成分，给卵巢做日常养护
食用方式：每天2次，每次2粒（共4粒），温水吞服
目标人群：更年期女性、经期紊乱女性、大龄备孕女性、关注气色女性、长期高压熬夜久坐人群
"""
    return f"产品：{name}，信息暂不可用"


# ============================================================
# 合规检查
# ============================================================

FORBIDDEN_WORDS = [
    "最", "第一", "唯一", "绝对", "100%", "百分之百", "保证",
    "顶级", "极品", "万能", "零风险", "永不", "最佳", "最好",
    "治疗", "治愈", "根治", "药到病除", "处方", "临床验证",
    "诊断", "疗效", "用药", "患者", "病理",
    "见效", "立竿见影", "一用就好", "无效退款", "瞬间",
    "立刻见效", "当天见效", "一周见效", "包治",
    "医生推荐", "专家认证", "医院推荐", "国家认证",
    "替代药物", "替代药品", "比药还好", "不用吃药",
    "糖尿病", "高血压", "心脏病", "癌症", "肿瘤",
    "限时", "抢购", "赶紧下单", "手慢无", "错过后悔",
]

EFFECT_PATTERNS = [
    r"\d+天.{0,5}(见效|变化|改善|消失|好转)",
    r"(一定|肯定|保证|绝对).{0,5}(好|有效|有用|瘦|白|美)",
    r"(吃了|用了|坚持).{0,3}(就|立刻|马上|瞬间)",
]


def check_title(title, max_len=30):
    """检查单个标题合规性"""
    issues = []
    for word in FORBIDDEN_WORDS:
        if word in title:
            issues.append(f"违禁词「{word}」")
    for pattern in EFFECT_PATTERNS:
        if re.search(pattern, title):
            issues.append("疑似功效承诺")
            break
    if len(title) > max_len + 5:
        issues.append(f"超长({len(title)}字)")
    return len(issues) == 0, issues


# ============================================================
# 模板回退（无 API Key 时使用）
# ============================================================

FALLBACK_BZU_SHORT = {  # ≤12字符
    "身材管理": ["代谢提上来，掉秤不再难", "节食不掉秤？缺了B族", "大餐后，做对一件事就行"],
    "低能量": ["下午不犯困的秘密", "低能量人的自救指南", "戒掉咖啡，状态反而好了"],
    "油痘肌": ["脸不出油了，才敢说", "油痘肌，从内调开始吧"],
    "春困": ["春天总犯困？试试这个", "别再靠咖啡续命了"],
    "大餐": ["大餐前吃一粒，不肿", "假期随便吃，节后不后悔"],
    "素人": ["吃了一个月，说点实话", "亲测有用的内调方法"],
    "日常": ["打工人养生，闭眼入", "同事追着问的秘密", "这瓶真的救了我"],
}
FALLBACK_BZU_LONG = {  # 10-20字符
    "身材管理": ["说八百遍了，想掉秤先把代谢提上来", "节食不掉秤？你可能缺了关键一步", "代谢慢真的会胖，还好有救", "小基数卡平台？先把代谢提上来", "每天一粒，代谢提上来，真的好"],
    "低能量": ["下午三点不犯困，终于找到方法了", "低能量老鼠人的自救指南来了", "不是懒，是缺B族，精力差的人必看", "戒掉咖啡之后，我的状态更好了", "从早困到晚？你缺了这个代谢开关"],
    "油痘肌": ["脸不出油了，后悔没早发现这个方法", "油痘肌姐妹看过来，从内调开始", "出油冒痘？试试内调，坚持一个月变了"],
    "春困": ["春天总犯困？试试这个方法，真的有用", "打工人春困自救指南，别再喝咖啡了"],
    "大餐": ["大餐前吃一粒，节后不肿不胖", "假期随便吃？节后不后悔的底气"],
    "素人": ["吃了一个月，说点大实话，坚持就有变化", "不是智商税，亲测有用的内调分享", "两个月了，分享真实的体验和变化"],
    "日常": ["打工人养生好物，从内到外都在变好", "同事追着问的秘密，终于公开了", "自用一年多不说假话，按头安利"],
}
FALLBACK_CTJ_SHORT = {  # ≤12字符
    "更年期": ["更年期自救指南", "情绪终于稳了"],
    "经期": ["被月经折腾的日子，结束了", "姨妈终于规律了"],
    "备孕": ["大龄备孕这一年，值了", "备孕先养巢"],
    "气色": ["养巢一年，像换了一个人", "素颜也透亮的方法"],
    "日常": ["女生养巢，闭眼入", "吃了三瓶，才敢来分享", "卵巢养护，不是备孕才需要"],
}
FALLBACK_CTJ_LONG = {  # 10-20字符
    "更年期": ["更年期不是病，但真的很需要认真养护", "40+女性的底气，来自内在的养护", "更年期自救指南：情绪终于稳下来了"],
    "经期": ["被月经折腾的日子，终于找到解法了", "姨妈终于规律了，分享我的调理方法", "PMS太折磨人了，分享五个自救方法"],
    "备孕": ["大龄备孕这一年，还好结果没辜负自己", "备孕先养巢，过来人的真心话", "35+备孕成功，分享我的内调经验"],
    "气色": ["养巢一年，朋友说我像换了一个人", "脸终于有光泽了，不是粉底撑出来的", "皮肤变好，不是靠护肤品，是从内调开始"],
    "日常": ["吃了三瓶才敢来分享，养巢真的有用", "卵巢养护不是备孕才需要，女生都该重视"],
}


def _fallback_titles(product_id, input_text, count, copy_type="long"):
    """模板匹配回退，按产品+角度匹配，加输入内容哈希偏移避免不同文案输出雷同"""
    if product_id == "bzu":
        source = FALLBACK_BZU_SHORT if copy_type == "short" else FALLBACK_BZU_LONG
    else:
        source = FALLBACK_CTJ_SHORT if copy_type == "short" else FALLBACK_CTJ_LONG

    text_lower = input_text.lower().strip()
    matched = None
    for key, titles in source.items():
        if key in text_lower or any(word in text_lower for word in key):
            matched = titles
            break

    if not matched:
        matched = source.get("日常", source[next(iter(source))])

    offset = hash(input_text) % max(len(matched) - count + 1, 1)
    rotated = matched[offset:] + matched[:offset]
    result = rotated[:count]
    while len(result) < count:
        result.append(matched[len(result) % len(matched)])
    return result


# ============================================================
# 辅助知识库（提升标题质量）
# ============================================================

def _load_aux_knowledge():
    """加载 templates / slang / keywords / forbidden-words 辅助知识，拼接为 prompt 片段"""
    kb = Path(get_kb_dir())
    parts = []

    # 1. 爆款标题公式（templates.md）
    tpl = kb / "templates.md"
    if tpl.exists():
        raw = tpl.read_text(encoding="utf-8")
        # 只提取标题公式部分
        formulas = []
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("- \""):
                formulas.append(line.strip("- "))
        if formulas:
            parts.append("爆款标题公式参考：\n" + "\n".join(formulas[:12]))

    # 2. 流行表达 & 开头钩子（trending-slang.md）
    slang = kb / "trending-slang.md"
    if slang.exists():
        raw = slang.read_text(encoding="utf-8")
        # 提取开头钩子和热门表达
        hooks = []
        for line in raw.split("\n"):
            line = line.strip()
            if "谁懂啊" in line or "后悔" in line or "真香" in line or "宝藏" in line or "听我" in line or "说真的" in line:
                hooks.append(line.strip("| "))
        if hooks:
            parts.append("流行表达参考（让标题更有网感）：" + "；".join(hooks[:15]))

    # 3. 合规替换表（forbidden-words.md 中的第五章）
    fw = kb / "forbidden-words.md"
    if fw.exists():
        raw = fw.read_text(encoding="utf-8")
        in_table = False
        repl_lines = []
        for line in raw.split("\n"):
            if "合规表达替换速查表" in line:
                in_table = True
                continue
            if in_table and line.startswith("|") and "禁用" not in line and "---" not in line:
                repl_lines.append(line.strip("|"))
            elif in_table and not line.startswith("|"):
                break
        if repl_lines:
            parts.append("合规改写参考（禁止治疗/功效/绝对化用语）：\n" + "\n".join(repl_lines[:20]))

    return "\n\n".join(parts) if parts else ""


_AUX_KNOWLEDGE = _load_aux_knowledge()

# ============================================================
# 提示词
# ============================================================

_MODE1_BASE = """你是小红书标题创作者。你的工作很简单：读一段文案，凭直觉写出让人想点进去的标题。

**创作方法：**
读完文案，问自己：这段文案里最打动人的那个瞬间是什么？把这个感觉直接变成标题。
- 从文案里抓一个具体细节或对比（比如"同事皮肤好我蜡黄""以为只有备孕才需要"），用它做标题素材
- 用第一人称"我"写，像跟闺蜜聊天——带情绪、有态度、不端着
- 标题要有情感变化：意外、醒悟、后悔没早试、庆幸发现了
- 多用数字和对比制造冲击力，少用形容词堆砌
- 逗号断句，有节奏，不一大段连在一起

**硬性规则：**
- 不使用 emoji
- 禁止极限词（最、第一、100%）、医疗术语（治疗、疗效）、功效承诺（保证有效）

**标题风格参考 — 看真人怎么写：**
情感共鸣：半年内调心得 → "听完播客发现，我这半年的内调思路没走弯路"
痛点方案：30+抗衰食物科普 → "女人过30，要想老得慢！这些食物要多吃！"
反转认知：骨皮同养食补清单 → "想比同龄人显年轻？记住这22种食物"
真实体验：两个月产品体验 → "连续吃了两个月研生之力巢天娇的真实感受"
干货合集：结构化内调方案 → "建议先存后看！全网很全的养雌内调方案"

{aux}

**输出格式**
每行一个标题，直接输出标题文字，不要编号、不要引号、不要任何前缀："""

MODE1_SYSTEM = _MODE1_BASE.replace("{aux}", _AUX_KNOWLEDGE)

MODE1_USER = """## 产品背景
{product}

## 文案内容
{content}

## 要求
基于以上文案，生成 {count} 个{type_desc}。"""

MODE2_SYSTEM = """你是小红书标题创作专家。

**创作规则**
1. 不使用 emoji
2. 使用逗号、问号等标点做自然断句，有呼吸感和节奏感
3. 口语化、原生感强，像真实用户分享而非广告——多用"我"开头、带情绪、有悬念
4. 有强烈的点击欲望，戳痛点、造悬念、给共鸣
5. 标题必须与产品相关，自然植入产品关联
6. 禁止极限词、医疗术语、功效承诺、专家背书

**标题创作要诀 — 写出"人味"：**
1. 用具体数字制造真实感：两个月、22种、30岁、5个习惯
2. 用情感钩子替代空洞形容词：感谢、后悔、误解、没白花、再舒服也别做
3. 口语节奏：短的像聊天，长的有呼吸感，善用逗号断句
4. 五种爆款风格及真人范例：
   情感共鸣：第一人称分享半年内调心得 → "听完播客发现，我这半年的内调思路没走弯路"
   痛点方案：女生30+抗衰食物科普 → "女人过30，要想老得慢！这些食物要多吃！"
   反转认知：骨皮同养概念+食补清单 → "想比同龄人显年轻？记住这22种食物"
   真实体验：两个月巢天娇素人体验 → "连续吃了两个月研生之力巢天娇的真实感受"
   干货合集：结构化养雌内调方案 → "建议先存后看！全网很全的养雌内调方案"

{aux}

**输出格式**
每行一个标题，直接输出标题文字，不要编号、不要引号、不要任何前缀：""".replace("{aux}", _AUX_KNOWLEDGE)

MODE2_USER = """## 产品背景
{product}

## 视频传播方向
{angle}

## 要求
请生成 {count} 个{type_desc}。"""


# ============================================================
# 主函数
# ============================================================

def generate_titles(mode, content, product_id="bzu", copy_type="long", count=5,
                    api_key=None, base_url=None, model=None):
    """
    生成标题

    Args:
        mode: "copy"（文案取标题）或 "video"（视频配标题）
        content: 文案全文 或 视频方向描述
        product_id: 产品 ID（来自 products.json）
        copy_type: "short"（≤10字）或 "long"（10-20字）
        count: 生成数量
        api_key / base_url / model: LLM 配置（可选，不传则读环境变量）

    Returns:
        [(title, is_valid, issues), ...], source
    """
    # 动态校验 product_id
    valid_ids = list(_get_product_names().keys())
    if product_id not in valid_ids:
        product_id = valid_ids[0] if valid_ids else "bzu"

    api_key = api_key or os.getenv("LLM_API_KEY", "")
    base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com")
    model = model or os.getenv("LLM_MODEL", "deepseek-chat")

    type_desc = "短标题，每个标题不超过12字符（含标点），使用逗号、问号等标点做自然断句" if copy_type == "short" else "长标题，每个标题10到20字符（含标点），使用标点断句，让标题有节奏感"
    max_len = 12 if copy_type == "short" else 20

    product_context = _load_product_context(product_id)

    if not api_key:
        raw_titles = _fallback_titles(product_id, content, count, copy_type)
    else:
        try:
            client = OpenAI(api_key=api_key, base_url=base_url)

            if mode == "copy":
                system_prompt = MODE1_SYSTEM
                user_prompt = MODE1_USER.format(
                    product=product_context,
                    content=content[:3000],
                    count=count,
                    type_desc=type_desc,
                )
            else:
                system_prompt = MODE2_SYSTEM
                user_prompt = MODE2_USER.format(
                    product=product_context,
                    angle=content,
                    count=count,
                    type_desc=type_desc,
                )

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.85,
                max_tokens=count * 80,
            )

            raw = response.choices[0].message.content.strip()
            lines = raw.split("\n")
            raw_titles = []
            for line in lines:
                line = line.strip()
                line = re.sub(r'^[\d]+[\.\、\s]+', '', line)
                line = re.sub(r'^标题[\d]*[：:]', '', line)
                line = line.strip().strip('"')
                if line and len(line) >= 2:
                    raw_titles.append(line)

            if len(raw_titles) < count:
                fallback = _fallback_titles(product_id, content, count, copy_type)
                for t in fallback:
                    if len(raw_titles) >= count:
                        break
                    if t not in raw_titles:
                        raw_titles.append(t)

            raw_titles = raw_titles[:count]

        except Exception as e:
            err_msg = str(e)[:200]
            raise RuntimeError(f"API调用失败：{err_msg}") from e

    source = "api" if api_key else "template"
    results = []
    for t in raw_titles:
        valid, issues = check_title(t.strip(), max_len + 5)
        results.append((t.strip(), valid, issues))

    return results, source
