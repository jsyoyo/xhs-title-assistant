"""
小红书爆款标题助手 - Flask Web 应用
模式1：粘贴文案 → 提炼标题
模式2：输入视频方向 → 生成标题
附加：知识库编辑器（/editor）
"""

import os
import logging
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, jsonify, session, redirect

import json
import re
import time
import threading
import requests

from title_generator import generate_titles, get_product_list, get_kb_dir

app = Flask(__name__)
BASE_DIR = Path(__file__).parent

# Flask session 密钥（用于编辑器登录态）
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24).hex())

# 编辑器访问密码
EDITOR_PASSWORD = os.getenv("EDITOR_PASSWORD", "")

# 日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ============================================================
# 标题生成
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "无效请求"}), 400

    mode = data.get("mode", "copy")
    content = data.get("content", "").strip()
    product = data.get("product", "bzu")
    copy_type = data.get("copy_type", "long")
    count = int(data.get("count", 5))

    if not content:
        return jsonify({"success": False, "error": "请输入内容"}), 400

    if mode not in ("copy", "video"):
        return jsonify({"success": False, "error": "无效模式"}), 400

    # 动态校验 product
    valid_ids = [p["id"] for p in get_product_list()]
    if product not in valid_ids:
        product = valid_ids[0] if valid_ids else "bzu"

    if copy_type not in ("short", "long"):
        copy_type = "long"

    if count not in (3, 5, 8, 10):
        count = 5

    # LLM 配置（服务端 .env 为主，前端可选覆盖）
    api_key = data.get("api_key", "").strip()
    base_url = data.get("base_url", "").strip()
    model = data.get("model", "").strip()

    try:
        results, source = generate_titles(
            mode=mode,
            content=content,
            product_id=product,
            copy_type=copy_type,
            count=count,
            api_key=api_key or None,
            base_url=base_url or None,
            model=model or None,
        )

        titles = []
        for title, valid, issues in results:
            titles.append({
                "title": title,
                "valid": valid,
                "issues": issues,
            })

        logger.info(f"生成成功 mode={mode} product={product} count={len(titles)} source={source}")
        return jsonify({
            "success": True,
            "titles": titles,
            "total": len(titles),
            "mode": mode,
            "product": product,
            "source": source,
        })

    except RuntimeError as e:
        logger.error(f"生成失败: {e}")
        return jsonify({"success": False, "error": str(e), "hint": "请检查API Key、Base URL和模型名是否正确"}), 500
    except Exception as e:
        logger.error(f"系统错误: {e}")
        return jsonify({"success": False, "error": f"系统错误：{str(e)}"}), 500


# ============================================================
# 诊断接口
# ============================================================

@app.route("/debug")
def debug():
    kb_dir = get_kb_dir()
    kb_path = Path(kb_dir)

    kb_status = {}
    for p in get_product_list():
        fp = kb_path / p["file"]
        kb_status[p["id"]] = {
            "name": p["name"],
            "file": p["file"],
            "exists": fp.exists(),
            "size_kb": fp.stat().st_size // 1024 if fp.exists() else 0,
        }

    return jsonify({
        "knowledge_base_path": kb_dir,
        "knowledge_base_exists": kb_path.exists(),
        "products": kb_status,
        "api_key_configured": bool(os.getenv("LLM_API_KEY")),
        "api_base_url": os.getenv("LLM_BASE_URL", "https://api.deepseek.com"),
        "api_model": os.getenv("LLM_MODEL", "deepseek-chat"),
        "editor_configured": bool(EDITOR_PASSWORD),
    })


# ============================================================
# 知识库编辑器
# ============================================================

def _editor_check_auth():
    """检查编辑器访问权限，返回 True/False"""
    if not EDITOR_PASSWORD:
        return False
    return session.get("editor_authenticated") == True


@app.route("/editor")
def editor():
    return render_template("editor.html")


@app.route("/editor/login", methods=["POST"])
def editor_login():
    if not EDITOR_PASSWORD:
        return jsonify({"success": False, "error": "编辑器未配置，请在 .env 中设置 EDITOR_PASSWORD"}), 403

    data = request.get_json()
    pwd = data.get("password", "") if data else ""
    if pwd == EDITOR_PASSWORD:
        session["editor_authenticated"] = True
        logger.info("编辑器登录成功")
        return jsonify({"success": True})
    logger.warning("编辑器登录失败：密码错误")
    return jsonify({"success": False, "error": "密码错误"}), 401


@app.route("/editor/logout", methods=["POST"])
def editor_logout():
    session.pop("editor_authenticated", None)
    return jsonify({"success": True})


@app.route("/editor/api/products")
def editor_api_products():
    if not _editor_check_auth():
        return jsonify({"success": False, "error": "请先登录"}), 401
    products = get_product_list()
    return jsonify({"success": True, "products": products})


@app.route("/editor/api/load")
def editor_api_load():
    if not _editor_check_auth():
        return jsonify({"success": False, "error": "请先登录"}), 401

    product_id = request.args.get("product", "")
    products = {p["id"]: p for p in get_product_list()}
    if product_id not in products:
        return jsonify({"success": False, "error": "无效产品ID"}), 400

    kb_dir = Path(get_kb_dir())
    filepath = kb_dir / products[product_id]["file"]
    if filepath.exists():
        content = filepath.read_text(encoding="utf-8")
    else:
        content = ""
    return jsonify({"success": True, "content": content, "product": products[product_id]})


@app.route("/editor/api/save", methods=["POST"])
def editor_api_save():
    if not _editor_check_auth():
        return jsonify({"success": False, "error": "请先登录"}), 401

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "无效请求"}), 400

    product_id = data.get("product", "")
    content = data.get("content", "")

    products = {p["id"]: p for p in get_product_list()}
    if product_id not in products:
        return jsonify({"success": False, "error": "无效产品ID"}), 400

    kb_dir = Path(get_kb_dir())
    filepath = kb_dir / products[product_id]["file"]

    try:
        filepath.write_text(content, encoding="utf-8")
        logger.info(f"知识库已更新: {products[product_id]['name']} ({filepath})")
        return jsonify({"success": True, "message": f"「{products[product_id]['name']}」知识库已保存"})
    except Exception as e:
        logger.error(f"知识库保存失败: {e}")
        return jsonify({"success": False, "error": f"保存失败：{str(e)}"}), 500


# ============================================================
# 飞书机器人
# ============================================================

FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
FEISHU_TOKEN = {"value": "", "expires_at": 0}
_PROCESSED_EVENTS = {}  # event_id -> timestamp，防止重复推送（dict 保证插入顺序）
_BOT_OPEN_ID = None  # 机器人在飞书的 open_id，首次收到@消息时自动学习


def _get_tenant_token():
    """获取飞书 tenant_access_token（缓存 1.5 小时）"""
    now = time.time()
    if FEISHU_TOKEN["value"] and now < FEISHU_TOKEN["expires_at"]:
        return FEISHU_TOKEN["value"]

    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        logger.error(f"飞书 token 获取失败: {data}")
        raise RuntimeError(f"飞书认证失败：{data.get('msg', '')}")

    FEISHU_TOKEN["value"] = data["tenant_access_token"]
    FEISHU_TOKEN["expires_at"] = now + data.get("expire", 7200) - 300
    return FEISHU_TOKEN["value"]


def _reply_feishu(message_id, text):
    """回复飞书消息"""
    token = _get_tenant_token()
    resp = requests.post(
        f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}/reply",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": json.dumps({"text": text}), "msg_type": "text"},
        timeout=10,
    )
    data = resp.json()
    if data.get("code") != 0:
        logger.error(f"飞书回复失败: {data}")


def _parse_command(text):
    """
    解析用户消息，提取产品、格式、数量和文案内容。
    支持格式：
      @机器人 bzu long 5 文案内容...
      @机器人 超能B族 短 3 文案内容...
      @机器人 文案内容...（使用默认值）
    """
    text = text.strip()

    product = "bzu"
    copy_type = "long"
    count = 5
    mode = "copy"

    # 去掉 @机器人 部分（飞书消息中通常是 @用户名 开头）
    text = re.sub(r'@\S+\s*', '', text).strip()

    product_names = {p["name"]: p["id"] for p in get_product_list()}
    product_names.update({
        "bzu": "bzu", "B族": "bzu", "超能B族": "bzu", "b族": "bzu",
        "ctj": "ctj", "巢天娇": "ctj", "巢天嬌": "ctj",
    })

    # 尝试匹配产品
    for name, pid in product_names.items():
        if text.startswith(name):
            product = pid
            text = text[len(name):].strip()
            break

    # 去掉前导标点（用户可能在产品名后输入逗号、句号等）
    text = re.sub(r'^[\s，,。、]+', '', text)

    # 尝试匹配格式
    for fmt, val in [("short", "short"), ("短标题", "short"), ("短", "short"), ("long", "long"), ("长标题", "long"), ("长", "long")]:
        if text.startswith(fmt):
            copy_type = val
            text = text[len(fmt):].strip()
            break

    # 去掉前导标点
    text = re.sub(r'^[\s，,。、]+', '', text)

    # 尝试匹配数量
    m = re.match(r'(\d+)\s*', text)
    if m:
        n = int(m.group(1))
        if n in (3, 5, 8, 10):
            count = n
        text = text[len(m.group(0)):].strip()

    # 剩余部分为内容，去掉前导标点
    content = re.sub(r'^[\s，,。、]+', '', text).strip()

    return product, copy_type, count, content


def _process_feishu_message(message_id, user_text):
    """异步处理飞书消息，生成标题并回复"""
    try:
        if not user_text.strip():
            _reply_feishu(message_id, "请发送文案内容，例如：\n超能B族 长 5 我吃了三个月B族，皮肤出油改善了...")
            return

        product, copy_type, count, content = _parse_command(user_text)

        if not content:
            help_text = (
                "请按格式发送：\n"
                "【产品】 【短/长】 【数量】 文案内容\n\n"
                "产品可选：超能B族 / 巢天娇\n"
                "格式可选：短 / 长\n"
                "数量可选：3 / 5 / 8 / 10\n\n"
                "示例：超能B族 长 5 我吃了三个月B族，皮肤出油真的改善了"
            )
            _reply_feishu(message_id, help_text)
            return

        results, source = generate_titles(
            mode="copy",
            content=content,
            product_id=product,
            copy_type=copy_type,
            count=count,
        )

        product_names = {p["id"]: p["name"] for p in get_product_list()}
        type_label = "短标题" if copy_type == "short" else "长标题"
        source_label = "AI生成" if source == "api" else "模板生成"

        lines = [
            f"【{product_names[product]} · {type_label} · {source_label}】",
            "",
        ]
        for i, (title, valid, _issues) in enumerate(results, 1):
            flag = "" if valid else " ⚠"
            lines.append(f"{i}. {title}{flag}")

        _reply_feishu(message_id, "\n".join(lines))
        logger.info(f"飞书回复成功 product={product} count={len(results)}")

    except RuntimeError as e:
        try:
            _reply_feishu(message_id, f"生成失败：{e}")
        except Exception:
            logger.error(f"回复失败: {e}")
    except Exception as e:
        logger.error(f"飞书处理异常: {e}")
        try:
            _reply_feishu(message_id, "系统错误，请稍后重试")
        except Exception:
            pass


@app.route("/feishu/event", methods=["POST"])
def feishu_event():
    body = request.get_json()
    if not body:
        return jsonify({}), 400

    # URL 验证 — 同步返回
    if body.get("type") == "url_verification":
        challenge = body.get("challenge", "")
        logger.info(f"飞书 URL 验证，challenge={challenge[:20]}...")
        return jsonify({"challenge": challenge})

    # 消息事件 — 先返回 200，再异步处理
    event_id = body.get("header", {}).get("event_id", "")
    event_type = body.get("header", {}).get("event_type", "")
    event = body.get("event", {})
    message = event.get("message", {})

    # 去重：同一个 event_id 只处理一次
    if event_id and event_id in _PROCESSED_EVENTS:
        logger.info(f"飞书重复事件，跳过: {event_id}")
        return jsonify({})
    if event_id:
        _PROCESSED_EVENTS[event_id] = time.time()
        # 超过 200 条时淘汰最旧的一条，而不是全清空
        while len(_PROCESSED_EVENTS) > 200:
            oldest = next(iter(_PROCESSED_EVENTS))
            del _PROCESSED_EVENTS[oldest]

    if event_type == "im.message.receive_v1" and message.get("message_type") == "text":
        message_id = message.get("message_id", "")
        chat_type = message.get("chat_type", "group")
        sender = event.get("sender", {})
        sender_open_id = sender.get("sender_id", {}).get("open_id", "")

        # P2：忽略机器人自己的消息，防止自循环
        global _BOT_OPEN_ID
        if _BOT_OPEN_ID and sender_open_id == _BOT_OPEN_ID:
            logger.info(f"飞书消息（自己发的），跳过")
            return jsonify({})

        # P0：群聊中只处理 @机器人 的消息；私聊（p2p）全部处理
        if chat_type != "p2p":
            mentions = message.get("mentions", [])
            if not mentions:
                logger.info(f"群聊消息未@任何人，跳过")
                return jsonify({})
            # 检查被@的人里有没有本机器人
            bot_mentioned = False
            for m in mentions:
                mid = m.get("id", {}).get("open_id", "")
                name = m.get("name", "")
                # 已知 open_id 时精确匹配，否则靠名字识别
                if _BOT_OPEN_ID and mid == _BOT_OPEN_ID:
                    bot_mentioned = True
                    break
                if not _BOT_OPEN_ID and ("标题助手" in name or "xhs" in name.lower()):
                    bot_mentioned = True
                    _BOT_OPEN_ID = mid
                    logger.info(f"已学习机器人 open_id: {_BOT_OPEN_ID}")
                    break
            if not bot_mentioned:
                logger.info(f"群聊消息@了别人而非机器人，跳过")
                return jsonify({})

        content_str = message.get("content", "{}")
        try:
            content_json = json.loads(content_str)
            user_text = content_json.get("text", "")
        except json.JSONDecodeError:
            user_text = content_str

        logger.info(f"飞书消息（异步处理）: {user_text[:100]}")
        threading.Thread(target=_process_feishu_message, args=(message_id, user_text), daemon=True).start()

    return jsonify({})


# ============================================================
# 启动
# ============================================================

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5088))
    app.run(host="0.0.0.0", port=port, debug=True)
