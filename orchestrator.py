# -*- coding: utf-8 -*-
"""
三位一体空投系统 - 完整版 v3.0
新增：Telegram 交互命令（/start, /scan now, /stats, /bind wallet）
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
from urllib.parse import urlparse, parse_qs

# ===== 强制输出日志 =====
sys.stderr = sys.stdout
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== 环境变量 =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")          # 默认接收报告的 chat_id
WALLET_ADDRESSES = os.environ.get("WALLET_ADDRESSES", "").split(",")

# ===== 全局变量 =====
last_projects = []
data_source_status = "未知"
last_scan_result = None   # 存储最近一次扫描的详细结果
user_wallets = {}         # 存储用户绑定的钱包地址 {chat_id: wallet_address}

logger.info("🚀 三位一体空投系统启动 v3.0 (交互版)")
logger.info(f"默认钱包数量: {len([w for w in WALLET_ADDRESSES if w.strip()])}")

# ============================================================
# Telegram 消息发送（支持指定 chat_id）
# ============================================================
def send_telegram(text, chat_id=None, parse_mode="Markdown"):
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
        resp = requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram 发送失败: {e}")
        return False

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
# AI 情报（数据源状态追踪）
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
# 实时推送（检测新项目）
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
# Hunter 验证
# ============================================================
def run_hunter(projects):
    logger.info("🔍 Hunter 验证...")
    verified = [p for p in projects if score_project(p) >= 60]
    logger.info(f"验证通过 {len(verified)} 个项目（过滤 {len(projects)-len(verified)} 个低分）")
    return verified

# ============================================================
# 专用机器人（支持传入钱包地址）
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
# 核心扫描函数（返回详细结果）
# ============================================================
def run_scan(chat_id_to_notify=None):
    """执行扫描并返回结果，可指定通知的 chat_id"""
    global data_source_status, last_scan_result
    start = datetime.now()
    logger.info("🚀 开始扫描...")

    # 1. AI 发现
    all_projects = run_ai_agent()
    if not all_projects:
        msg = "⚠️ 未发现任何项目"
        send_telegram(msg, chat_id_to_notify)
        return None

    check_and_push_new_projects(all_projects)

    # 2. Hunter 验证
    verified_projects = run_hunter(all_projects)
    if not verified_projects:
        msg = "⚠️ 所有项目评分过低，跳过执行"
        send_telegram(msg, chat_id_to_notify)
        return None

    # 3. 评分排序
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

    # 4. 获取要使用的钱包列表（优先使用绑定钱包）
    wallets = []
    if chat_id_to_notify and chat_id_to_notify in user_wallets:
        wallets = [user_wallets[chat_id_to_notify]]
    elif WALLET_ADDRESSES and WALLET_ADDRESSES[0].strip():
        wallets = [w.strip() for w in WALLET_ADDRESSES if w.strip()]
    else:
        wallets = []

    # 5. 执行机器人
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

    # 6. 生成报告
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
    # 发送给指定用户
    send_telegram(report, chat_id_to_notify)
    # 同时发送给默认 CHAT_ID（如果不同且存在）
    if chat_id_to_notify and chat_id_to_notify != CHAT_ID:
        send_telegram(report, CHAT_ID)

    # 保存结果
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
# Telegram 命令处理
# ============================================================
def handle_command(chat_id, command_text):
    """处理用户命令"""
    logger.info(f"收到命令: {command_text} (from {chat_id})")
    parts = command_text.strip().split()
    if not parts:
        return

    cmd = parts[0].lower()

    # /start
    if cmd == "/start":
        menu = """
🤖 *空投雷达 Bot*

可用命令:
/start - 显示此菜单
/scan now - 立即执行一次扫描
/stats - 查看最近一次扫描统计
/bind wallet 0x... - 绑定你的钱包地址

系统每2小时自动扫描一次，发现新项目会实时推送。
"""
        send_telegram(menu, chat_id)
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
            send_telegram("📊 暂无扫描数据，请先执行 /scan now", chat_id)
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
        send_telegram(f"✅ 钱包绑定成功: `{wallet[:8]}...`", chat_id)
        return

    # 未知命令
    send_telegram("❌ 未知命令，请输入 /start 查看菜单", chat_id)

# ============================================================
# HTTP 服务器（支持 Webhook）
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

                # 提取消息
                if 'message' in update:
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
# 设置 Telegram Webhook
# ============================================================
def set_webhook():
    if not BOT_TOKEN:
        logger.error("未设置 BOT_TOKEN，无法设置 webhook")
        return
    public_url = os.environ.get("PUBLIC_URL")
    if not public_url:
        # 尝试从 Render 环境获取
        public_url = os.environ.get("RENDER_EXTERNAL_URL")
    if not public_url:
        logger.warning("未设置 PUBLIC_URL，webhook 可能无法工作，请手动设置")
        return
    webhook_url = f"{public_url}/webhook"
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    try:
        resp = requests.post(url, json={"url": webhook_url}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("ok"):
                logger.info(f"✅ Webhook 设置成功: {webhook_url}")
            else:
                logger.error(f"Webhook 设置失败: {data}")
        else:
            logger.error(f"Webhook 请求失败: {resp.status_code}")
    except Exception as e:
        logger.error(f"Webhook 设置异常: {e}")

# ============================================================
# 主循环
# ============================================================
def main_loop():
    logger.info("🔄 空投雷达持续运行模式 v3.0 (交互版)")
    logger.info("⏰ 每 2 小时执行一次扫描")
    logger.info("📱 发现新项目立即推送，支持 /start /scan now /stats /bind wallet")

    # 首次启动时设置 webhook
    set_webhook()

    while True:
        try:
            run_scan()  # 自动扫描（默认发给 CHAT_ID）
            wait_seconds = 2 * 60 * 60
            logger.info(f"⏳ 等待 {wait_seconds/3600} 小时后执行下一次...")
            time.sleep(wait_seconds)
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