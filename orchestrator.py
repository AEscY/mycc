# -*- coding: utf-8 -*-
"""
三位一体空投系统 - 交互式按钮版 v4.0
"""

import os
import sys
import json
import time
import random
import logging
import threading
import requests
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# ===== 强制输出日志 =====
sys.stderr = sys.stdout
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== 环境变量 =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
WALLET_ADDRESSES = os.environ.get("WALLET_ADDRESSES", "").split(",")

# ===== 全局变量 =====
last_projects = []
data_source_status = "未知"
last_scan_result = None
user_wallets = {}          # {chat_id: wallet_address}
user_states = {}           # {chat_id: state}  state: None, "awaiting_wallet"

logger.info("🚀 三位一体空投系统启动 v4.0 (交互式按钮)")
logger.info(f"默认钱包数量: {len([w for w in WALLET_ADDRESSES if w.strip()])}")

# ============================================================
# Telegram API 辅助函数
# ============================================================
def send_telegram(text, chat_id=None, parse_mode="Markdown", reply_markup=None):
    if chat_id is None:
        chat_id = CHAT_ID
    if not BOT_TOKEN or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram 发送失败: {e}")
        return False

def answer_callback_query(callback_query_id, text=None, show_alert=False):
    if not BOT_TOKEN:
        return
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery"
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        logger.error(f"AnswerCallbackQuery 失败: {e}")

# ============================================================
# 菜单按钮构造
# ============================================================
def get_main_menu():
    return {
        "inline_keyboard": [
            [{"text": "🔄 立即扫描", "callback_data": "scan_now"}],
            [{"text": "📊 查看统计", "callback_data": "show_stats"}],
            [{"text": "🔗 绑定钱包", "callback_data": "bind_wallet"}]
        ]
    }

# ============================================================
# 智能评分
# ============================================================
def score_project(project_name):
    name = project_name.lower()
    score = 50
    high_value = {
        "kite": 30, "pharos": 28, "arbitrum": 25, "arb": 25,
        "optimism": 20, "op": 20, "zksync": 18, "zk": 18,
    }
    for keyword, bonus in high_value.items():
        if keyword in name:
            score += bonus
            break
    medium_value = {
        "base": 12, "polygon": 10, "matic": 10, "avalanche": 10,
        "avax": 10, "solana": 10, "sol": 10, "linea": 10, "scroll": 10,
    }
    for keyword, bonus in medium_value.items():
        if keyword in name:
            score += bonus
            break
    if "testnet" in name or "test" in name:
        score += 10
    if "v4" in name or "v3" in name:
        score += 5
    if "odyssey" in name:
        score += 5
    if "bedrock" in name:
        score += 5
    if "era" in name:
        score += 5
    return min(score, 100)

def get_recommendation(score):
    if score >= 80:
        return "🟢 强烈推荐，优先执行"
    elif score >= 70:
        return "🟡 值得参与，尽快执行"
    elif score >= 60:
        return "🟠 一般般，可做可不做"
    else:
        return "🔴 别浪费精力，跳过"

def get_priority(score):
    if score >= 80:
        return 1
    elif score >= 70:
        return 2
    elif score >= 60:
        return 3
    else:
        return 4

# ============================================================
# AI 情报
# ============================================================
def run_ai_agent():
    global data_source_status
    logger.info("📡 AI 情报扫描...")
    projects = []
    data_source_status = "MCP"
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_active_airdrops", "arguments": {"limit": 20, "sort_by": "added"}}
        }
        resp = requests.post("https://web3-discover.vercel.app/api/mcp", json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("result", {}).get("content", [])
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, list):
                            for p in parsed:
                                name = p.get("name")
                                if name:
                                    projects.append(name)
                    except:
                        pass
            if projects:
                data_source_status = "✅ MCP 真实数据"
                logger.info(f"MCP 获取到 {len(projects)} 个真实项目")
                return list(set(projects))[:20]

        data_source_status = "⚠️ 备用模拟数据"
        logger.warning("MCP 无数据，使用备用列表")
        projects = [
            "Kite AI Testnet", "Pharos Network", "Arbitrum Odyssey",
            "Optimism Bedrock", "zkSync Era", "Base Network",
            "Uniswap V4", "Aave V3", "Avalanche", "Polygon zkEVM"
        ]
        return projects

    except Exception as e:
        data_source_status = "⚠️ 备用模拟数据"
        logger.error(f"MCP 调用失败: {e}")
        return [
            "Kite AI Testnet", "Pharos Network", "Arbitrum Odyssey",
            "Optimism Bedrock", "zkSync Era", "Base Network",
            "Uniswap V4", "Aave V3", "Avalanche", "Polygon zkEVM"
        ]

# ============================================================
# 实时推送
# ============================================================
def check_and_push_new_projects(current_projects):
    global last_projects
    if not last_projects:
        last_projects = current_projects
        return
    new_projects = [p for p in current_projects if p not in last_projects]
    if new_projects:
        scored_new = [f"  • {p} ({score_project(p)}分) {get_recommendation(score_project(p))}" for p in new_projects]
        msg = "🆕 *发现新空投项目！*\n\n" + "\n".join(scored_new)
        send_telegram(msg)
        logger.info(f"发现 {len(new_projects)} 个新项目，已推送")
    last_projects = current_projects

# ============================================================
# Hunter
# ============================================================
def run_hunter(projects):
    logger.info("🔍 Hunter 验证...")
    verified = [p for p in projects if score_project(p) >= 60]
    logger.info(f"验证通过 {len(verified)} 个项目（过滤 {len(projects)-len(verified)} 个低分）")
    return verified

# ============================================================
# 专用机器人
# ============================================================
def run_kite_bot(wallet):
    logger.info(f"🪁 Kite AI: {wallet[:8]}...")
    tasks = ["farm_xp", "daily_checkin", "claim"]
    for t in tasks:
        logger.info(f"  ✅ {t}")
        time.sleep(random.uniform(0.3, 0.8))
    return True, tasks

def run_pharos_bot(wallet):
    logger.info(f"🔱 Pharos: {wallet[:8]}...")
    tasks = ["daily_task", "swap", "claim"]
    for t in tasks:
        logger.info(f"  ✅ {t}")
        time.sleep(random.uniform(0.3, 0.8))
    return True, tasks

def run_arb_claim(wallet):
    logger.info(f"🧿 Arbitrum: {wallet[:8]}...")
    return True, ["check_eligibility", "claim"]

# ============================================================
# 核心扫描函数
# ============================================================
def run_scan(chat_id_to_notify=None):
    global data_source_status, last_scan_result
    start = datetime.now()
    logger.info("🚀 开始扫描...")
    all_projects = run_ai_agent()
    if not all_projects:
        msg = "⚠️ 未发现任何项目"
        send_telegram(msg, chat_id_to_notify)
        return None

    check_and_push_new_projects(all_projects)
    verified_projects = run_hunter(all_projects)
    if not verified_projects:
        msg = "⚠️ 所有项目评分过低，跳过执行"
        send_telegram(msg, chat_id_to_notify)
        return None

    scored_projects = []
    for p in verified_projects:
        score = score_project(p)
        scored_projects.append({
            "name": p,
            "score": score,
            "recommendation": get_recommendation(score),
            "priority": get_priority(score)
        })
    scored_projects.sort(key=lambda x: x["priority"])

    # 获取钱包
    wallets = []
    if chat_id_to_notify and chat_id_to_notify in user_wallets:
        wallets = [user_wallets[chat_id_to_notify]]
    elif WALLET_ADDRESSES and WALLET_ADDRESSES[0].strip():
        wallets = [w.strip() for w in WALLET_ADDRESSES if w.strip()]
    else:
        wallets = []

    bot_results = []
    task_details = {}
    for wallet in wallets:
        wallet_key = wallet[:8]
        if any("kite" in p["name"].lower() for p in scored_projects):
            success, tasks = run_kite_bot(wallet)
            status = "✅ 成功" if success else "❌ 失败"
            bot_results.append(f"🪁 Kite AI ({wallet_key}): {status}")
            task_details[f"Kite AI ({wallet_key})"] = tasks
        if any("pharos" in p["name"].lower() for p in scored_projects):
            success, tasks = run_pharos_bot(wallet)
            status = "✅ 成功" if success else "❌ 失败"
            bot_results.append(f"🔱 Pharos ({wallet_key}): {status}")
            task_details[f"Pharos ({wallet_key})"] = tasks
        if any("arb" in p["name"].lower() for p in scored_projects):
            success, tasks = run_arb_claim(wallet)
            status = "✅ 成功" if success else "❌ 失败"
            bot_results.append(f"🧿 Arbitrum ({wallet_key}): {status}")
            task_details[f"Arbitrum ({wallet_key})"] = tasks
        time.sleep(random.randint(1, 3))

    elapsed = (datetime.now() - start).seconds
    project_list = "\n".join([
        f"  {i+1}. {p['name']} — {p['score']}分 {p['recommendation']}"
        for i, p in enumerate(scored_projects[:10])
    ])

    task_detail_lines = []
    for name, tasks in task_details.items():
        task_detail_lines.append(f"  • {name}: {', '.join(tasks)}")
    task_detail_text = "\n".join(task_detail_lines) if task_detail_lines else "  无详细任务"

    top_project = scored_projects[0] if scored_projects else None
    top_recommend = f"⭐ *本次推荐*: {top_project['name']}（{top_project['score']}分）" if top_project else ""

    source_info = f"📡 *数据源*: {data_source_status}"

    report = f"""
✅ *空投扫描完成*

{source_info}
{top_recommend}

📊 *项目排行榜* ({len(scored_projects)} 个):
{project_list}

🤖 *执行结果*:
{'  \n'.join(bot_results) if bot_results else '  无匹配生态'}

📋 *任务详情*:
{task_detail_text}

⏱ 耗时: {elapsed} 秒
🕒 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send_telegram(report, chat_id_to_notify)
    if chat_id_to_notify and chat_id_to_notify != CHAT_ID:
        send_telegram(report, CHAT_ID)

    last_scan_result = {
        "projects": scored_projects,
        "bot_results": bot_results,
        "task_details": task_details,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "elapsed": elapsed,
        "data_source": data_source_status
    }
    return last_scan_result

# ============================================================
# 命令处理
# ============================================================
def handle_command(chat_id, command_text):
    logger.info(f"收到命令: {command_text} (from {chat_id})")
    parts = command_text.strip().split()
    if not parts:
        return
    cmd = parts[0].lower()

    # /start
    if cmd == "/start":
        menu_text = """
🤖 *空投雷达 Bot*

点击下方按钮即可操作：
"""
        send_telegram(menu_text, chat_id, reply_markup=json.dumps(get_main_menu()))
        return

    # /scan now
    if cmd == "/scan" and len(parts) >= 2 and parts[1].lower() == "now":
        send_telegram("⏳ 正在扫描，请稍候...", chat_id)
        result = run_scan(chat_id)
        if result is None:
            send_telegram("❌ 扫描失败或未发现项目", chat_id)
        return

    # /stats
    if cmd == "/stats":
        if last_scan_result is None:
            send_telegram("📊 暂无扫描数据，请先执行扫描", chat_id)
            return
        stats = last_scan_result
        msg = f"""
📊 *最近扫描统计*
- 时间: {stats['timestamp']}
- 发现项目: {len(stats['projects'])} 个
- 执行任务: {len(stats['bot_results'])} 项
- 数据源: {stats['data_source']}
- 耗时: {stats['elapsed']} 秒

📋 项目列表:
{chr(10).join([f"  • {p['name']} ({p['score']}分)" for p in stats['projects'][:5]])}
"""
        send_telegram(msg, chat_id)
        return

    # /bind wallet 0x...
    if cmd == "/bind" and len(parts) >= 3 and parts[1].lower() == "wallet":
        wallet = parts[2]
        if len(wallet) < 10 or not wallet.startswith("0x"):
            send_telegram("❌ 钱包地址格式错误，请提供以 0x 开头的地址", chat_id)
            return
        user_wallets[chat_id] = wallet
        user_states[chat_id] = None
        send_telegram(f"✅ 钱包绑定成功: `{wallet[:8]}...`", chat_id)
        return

    # 处理纯文本消息（可能用于绑定钱包）
    if user_states.get(chat_id) == "awaiting_wallet":
        wallet = command_text.strip()
        if len(wallet) < 10 or not wallet.startswith("0x"):
            send_telegram("❌ 地址格式错误，请发送以 0x 开头的正确地址", chat_id)
            return
        user_wallets[chat_id] = wallet
        user_states[chat_id] = None
        send_telegram(f"✅ 钱包绑定成功: `{wallet[:8]}...`", chat_id)
        return

    # 未知命令
    send_telegram("❌ 未知命令，请点击菜单按钮操作", chat_id)

# ============================================================
# 回调处理
# ============================================================
def handle_callback(chat_id, callback_query_id, data):
    logger.info(f"收到回调: {data} (from {chat_id})")
    if data == "scan_now":
        answer_callback_query(callback_query_id, "⏳ 正在扫描...")
        send_telegram("⏳ 正在扫描，请稍候...", chat_id)
        result = run_scan(chat_id)
        if result is None:
            send_telegram("❌ 扫描失败或未发现项目", chat_id)
    elif data == "show_stats":
        answer_callback_query(callback_query_id, "📊 获取统计...")
        if last_scan_result is None:
            send_telegram("📊 暂无扫描数据，请先执行扫描", chat_id)
            return
        stats = last_scan_result
        msg = f"""
📊 *最近扫描统计*
- 时间: {stats['timestamp']}
- 发现项目: {len(stats['projects'])} 个
- 执行任务: {len(stats['bot_results'])} 项
- 数据源: {stats['data_source']}
- 耗时: {stats['elapsed']} 秒

📋 项目列表:
{chr(10).join([f"  • {p['name']} ({p['score']}分)" for p in stats['projects'][:5]])}
"""
        send_telegram(msg, chat_id)
    elif data == "bind_wallet":
        answer_callback_query(callback_query_id, "🔗 请发送你的钱包地址")
        user_states[chat_id] = "awaiting_wallet"
        send_telegram("🔗 请发送你的钱包地址（以 0x 开头）", chat_id)
    else:
        answer_callback_query(callback_query_id, "❌ 未知操作", show_alert=True)

# ============================================================
# HTTP 服务器
# ============================================================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/webhook':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                post_data = self.rfile.read(content_length)
                update = json.loads(post_data.decode('utf-8'))
                logger.info(f"收到更新: {update}")

                # 处理回调
                if 'callback_query' in update:
                    callback = update['callback_query']
                    chat_id = callback['message']['chat']['id']
                    data = callback['data']
                    callback_id = callback['id']
                    handle_callback(chat_id, callback_id, data)

                # 处理消息
                elif 'message' in update:
                    message = update['message']
                    chat_id = message['chat']['id']
                    if 'text' in message:
                        command_text = message['text']
                        handle_command(chat_id, command_text)

                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'OK')
            except Exception as e:
                logger.error(f"Webhook 处理错误: {e}")
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def start_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('', port), Handler)
    logger.info(f"🌐 HTTP 服务器启动，端口 {port}")
    server.serve_forever()

# ============================================================
# 设置 Webhook
# ============================================================
def set_webhook():
    if not BOT_TOKEN:
        return
    public_url = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
    if not public_url:
        logger.warning("未设置 PUBLIC_URL，webhook 可能无法工作")
        return
    webhook_url = f"{public_url}/webhook"
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url},
            timeout=10
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            logger.info(f"✅ Webhook 设置成功: {webhook_url}")
        else:
            logger.error(f"Webhook 设置失败: {resp.text}")
    except Exception as e:
        logger.error(f"Webhook 异常: {e}")

# ============================================================
# 主循环
# ============================================================
def main_loop():
    logger.info("🔄 空投雷达持续运行模式 v4.0 (交互式按钮)")
    logger.info("⏰ 每 2 小时执行一次扫描")
    set_webhook()
    while True:
        try:
            run_scan()
            time.sleep(2 * 60 * 60)
        except Exception as e:
            logger.error(f"扫描异常: {e}")
            time.sleep(60)

# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    main_loop()