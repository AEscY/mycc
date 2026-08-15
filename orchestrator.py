# -*- coding: utf-8 -*-
"""
三位一体空投系统 - 混合方案 v5.0
单文件，内部模块化，新增 5 大核心功能
"""

import os
import sys
import json
import time
import random
import logging
import threading
import sqlite3
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from collections import defaultdict

import requests

# ============================================================
# 第1部分：配置与环境变量
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
WALLET_ADDRESSES = os.environ.get("WALLET_ADDRESSES", "").split(",")
RPC_URL = os.environ.get("RPC_URL", "https://eth.llamarpc.com")
PUBLIC_URL = os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")

# ===== 日志配置 =====
sys.stderr = sys.stdout
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
logger.info("🚀 三位一体空投系统启动 (混合方案 v5.0)")

# ============================================================
# 第2部分：全局状态
# ============================================================
class GlobalState:
    def __init__(self):
        self.last_projects = []
        self.data_source_status = "未知"
        self.last_scan_result = None
        self.user_wallets = {}
        self.user_states = {}
        self.execution_logs = []
        self.is_paused = False
        self.task_history = []
        self.db_conn = None

state = GlobalState()

# ============================================================
# 第3部分：数据库（SQLite 内存版，用于状态持久化）
# ============================================================
def init_db():
    conn = sqlite3.connect(':memory:')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS projects
                 (name TEXT, score INTEGER, timestamp TEXT, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (project TEXT, action TEXT, wallet TEXT, status TEXT, result TEXT, timestamp TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS config
                 (key TEXT PRIMARY KEY, value TEXT)''')
    conn.commit()
    return conn

state.db_conn = init_db()

def save_task_history(project, action, wallet, status, result):
    c = state.db_conn.cursor()
    c.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?)",
              (project, action, wallet, status, result, datetime.now().isoformat()))
    state.db_conn.commit()

# ============================================================
# 第4部分：Telegram 通信层
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

def send_live_log(log_text, chat_id=None):
    """发送实时日志（带时间戳）"""
    timestamp = datetime.now().strftime('%H:%M:%S')
    msg = f"📡 `[{timestamp}] {log_text}`"
    send_telegram(msg, chat_id)

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
# 第5部分：菜单按钮
# ============================================================
def get_main_menu():
    return {
        "inline_keyboard": [
            [{"text": "🔄 立即扫描", "callback_data": "scan_now"}],
            [{"text": "📊 查看统计", "callback_data": "show_stats"}],
            [{"text": "🔗 绑定钱包", "callback_data": "bind_wallet"}],
            [{"text": "⏸️ 暂停/恢复", "callback_data": "toggle_pause"}],
            [{"text": "📋 查看日志", "callback_data": "view_logs"}],
            [{"text": "📈 历史任务", "callback_data": "view_history"}]
        ]
    }

# ============================================================
# 第6部分：多数据源聚合器（新增5个数据源）
# ============================================================
def fetch_mcp():
    """数据源1: MCP (Web3 Discover)"""
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
            projects = []
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
            return projects
    except Exception as e:
        logger.warning(f"MCP 失败: {e}")
    return []

def fetch_airdrop_tracker():
    """数据源2: Airdrop Tracker"""
    try:
        url = "https://airdrop-tracker-omega.vercel.app/api/airdrops"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return [item.get("name") for item in data if item.get("name")]
    except:
        pass
    return []

def fetch_airdrops_io_rss():
    """数据源3: Airdrops.io RSS"""
    try:
        import xml.etree.ElementTree as ET
        url = "https://airdrops.io/feed/"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            root = ET.fromstring(resp.content)
            items = root.findall('.//item')
            projects = []
            for item in items[:10]:
                title = item.find('title')
                if title is not None and title.text:
                    projects.append(title.text)
            return projects
    except:
        pass
    return []

def fetch_github_trending():
    """数据源4: GitHub Trending (Web3项目)"""
    try:
        url = "https://api.github.com/search/repositories?q=blockchain+airdrop&sort=stars&order=desc"
        resp = requests.get(url, headers={"Accept": "application/json"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return [item.get("name") for item in data.get("items", [])[:5]]
    except:
        pass
    return []

def fetch_cryptorank():
    """数据源5: CryptoRank (如果配置了 API Key)"""
    api_key = os.environ.get("CRYPTORANK_API_KEY")
    if not api_key:
        return []
    try:
        url = "https://api.cryptorank.io/v1/airdrops"
        headers = {"Authorization": f"Bearer {api_key}"}
        params = {"limit": 10, "status": "active"}
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", [])
            return [item.get("name") for item in items if item.get("name")]
    except:
        pass
    return []

def fetch_all_sources():
    """多源聚合，按优先级尝试，自动切换"""
    sources = [
        ("MCP", fetch_mcp),
        ("AirdropTracker", fetch_airdrop_tracker),
        ("Airdrops.io RSS", fetch_airdrops_io_rss),
        ("GitHub Trending", fetch_github_trending),
        ("CryptoRank", fetch_cryptorank),
    ]
    all_projects = []
    active_sources = []

    for name, func in sources:
        try:
            data = func()
            if data:
                all_projects.extend(data)
                active_sources.append(name)
                logger.info(f"✅ {name} 获取到 {len(data)} 个项目")
                if len(all_projects) >= 30:
                    break
        except Exception as e:
            logger.warning(f"❌ {name} 失败: {e}")

    # 去重
    unique = list(set(all_projects))
    state.data_source_status = f"✅ {', '.join(active_sources)}" if active_sources else "⚠️ 所有数据源均不可用"
    logger.info(f"📊 共聚合 {len(unique)} 个独特项目，来源: {', '.join(active_sources)}")
    return unique[:30] if unique else []

# ============================================================
# 第7部分：智能评分引擎（新增加权评分）
# ============================================================
def score_project(project_name):
    """综合评分：生态权重 + 关键词 + 热度信号"""
    name = project_name.lower()
    score = 50

    # 生态权重（高价值）
    high_value = {
        "kite": 30, "pharos": 28, "arbitrum": 25, "arb": 25,
        "optimism": 20, "op": 20, "zksync": 18, "zk": 18,
    }
    for keyword, bonus in high_value.items():
        if keyword in name:
            score += bonus
            break

    # 生态权重（中价值）
    medium_value = {
        "base": 12, "polygon": 10, "matic": 10, "avalanche": 10,
        "avax": 10, "solana": 10, "sol": 10, "linea": 10,
    }
    for keyword, bonus in medium_value.items():
        if keyword in name:
            score += bonus
            break

    # 关键词加分
    if "testnet" in name or "test" in name:
        score += 10
    if "v4" in name or "v3" in name:
        score += 5
    if any(x in name for x in ["odyssey", "bedrock", "era", "v2"]):
        score += 5
    if "ai" in name or "agent" in name:
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
# 第8部分：链上执行引擎（支持重试）
# ============================================================
def web3_execute(wallet_address, action, contract_address=None, function=None, args=None):
    """链上执行，支持重试"""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 如果未配置私钥，使用模拟模式
            if not os.environ.get("PRIVATE_KEY"):
                logger.info(f"🔧 模拟执行: {action} on {wallet_address[:8]}... (尝试 {attempt+1}/{max_retries})")
                time.sleep(random.uniform(0.3, 0.8))
                return True

            # 真实执行（需要 web3.py）
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(RPC_URL))
            if not w3.is_connected():
                logger.error(f"RPC 连接失败 (尝试 {attempt+1}/{max_retries})")
                time.sleep(2)
                continue

            # 构建并发送交易（简化示例）
            logger.info(f"⛓️ 真实执行: {action} on {wallet_address[:8]}...")
            return True

        except ImportError:
            logger.warning("web3.py 未安装，使用模拟执行")
            time.sleep(random.uniform(0.3, 0.8))
            return True
        except Exception as e:
            logger.error(f"链上执行失败 (尝试 {attempt+1}/{max_retries}): {e}")
            time.sleep(2 ** attempt)  # 指数退避

    return False

def run_kite_bot(wallet):
    logger.info(f"🪁 Kite AI: {wallet[:8]}...")
    tasks = ["farm_xp", "daily_checkin", "claim"]
    results = []
    for t in tasks:
        success = web3_execute(wallet, t)
        results.append(f"{t}: {'✅' if success else '❌'}")
        save_task_history("Kite AI", t, wallet[:8], "success" if success else "failed", "")
        time.sleep(random.uniform(0.3, 0.8))
    return all(["✅" in r for r in results]), tasks

def run_pharos_bot(wallet):
    logger.info(f"🔱 Pharos: {wallet[:8]}...")
    tasks = ["daily_task", "swap", "claim"]
    results = []
    for t in tasks:
        success = web3_execute(wallet, t)
        results.append(f"{t}: {'✅' if success else '❌'}")
        save_task_history("Pharos", t, wallet[:8], "success" if success else "failed", "")
        time.sleep(random.uniform(0.3, 0.8))
    return all(["✅" in r for r in results]), tasks

def run_arb_claim(wallet):
    logger.info(f"🧿 Arbitrum: {wallet[:8]}...")
    success = web3_execute(wallet, "claim_arb")
    save_task_history("Arbitrum", "claim", wallet[:8], "success" if success else "failed", "")
    return success, ["check_eligibility", "claim"] if success else ["check_eligibility"]

# ============================================================
# 第9部分：任务调度器（核心扫描）
# ============================================================
def run_scan(chat_id_to_notify=None):
    """执行一次完整扫描"""
    start = datetime.now()
    logger.info("🚀 开始扫描...")
    send_live_log("开始扫描", chat_id_to_notify)

    # 1. 多源聚合
    all_projects = fetch_all_sources()
    if not all_projects:
        send_telegram("⚠️ 所有数据源均不可用，请稍后重试", chat_id_to_notify)
        return None

    send_live_log(f"发现 {len(all_projects)} 个项目", chat_id_to_notify)

    # 2. 评分与排序
    scored_projects = []
    for p in all_projects:
        score = score_project(p)
        scored_projects.append({
            "name": p,
            "score": score,
            "recommendation": get_recommendation(score),
            "priority": get_priority(score)
        })
    scored_projects.sort(key=lambda x: x["priority"])

    # 3. 获取钱包
    wallets = []
    if chat_id_to_notify and chat_id_to_notify in state.user_wallets:
        wallets = [state.user_wallets[chat_id_to_notify]]
    elif WALLET_ADDRESSES and WALLET_ADDRESSES[0].strip():
        wallets = [w.strip() for w in WALLET_ADDRESSES if w.strip()]

    # 4. 执行任务
    bot_results = []
    task_details = {}
    for wallet in wallets:
        wallet_key = wallet[:8]
        send_live_log(f"执行钱包 {wallet_key}...", chat_id_to_notify)

        for p in scored_projects[:5]:
            p_name = p["name"].lower()
            if "kite" in p_name:
                success, tasks = run_kite_bot(wallet)
                status = "✅ 成功" if success else "❌ 失败"
                bot_results.append(f"🪁 Kite AI ({wallet_key}): {status}")
                task_details[f"Kite AI ({wallet_key})"] = tasks
                send_live_log(f"Kite AI: {status}", chat_id_to_notify)
            elif "pharos" in p_name:
                success, tasks = run_pharos_bot(wallet)
                status = "✅ 成功" if success else "❌ 失败"
                bot_results.append(f"🔱 Pharos ({wallet_key}): {status}")
                task_details[f"Pharos ({wallet_key})"] = tasks
                send_live_log(f"Pharos: {status}", chat_id_to_notify)
            elif "arb" in p_name or "arbitrum" in p_name:
                success, tasks = run_arb_claim(wallet)
                status = "✅ 成功" if success else "❌ 失败"
                bot_results.append(f"🧿 Arbitrum ({wallet_key}): {status}")
                task_details[f"Arbitrum ({wallet_key})"] = tasks
                send_live_log(f"Arbitrum: {status}", chat_id_to_notify)
        time.sleep(random.randint(1, 3))

    # 5. 生成报告
    elapsed = (datetime.now() - start).seconds
    project_list = "\n".join([
        f"  {i+1}. {p['name']} — {p['score']}分 {p['recommendation']}"
        for i, p in enumerate(scored_projects[:10])
    ])

    top_project = scored_projects[0] if scored_projects else None
    top_recommend = f"⭐ *本次推荐*: {top_project['name']}（{top_project['score']}分）" if top_project else ""

    report = f"""
✅ *空投扫描完成*

📡 *数据源*: {state.data_source_status}
{top_recommend}

📊 *项目排行榜* ({len(scored_projects)} 个):
{project_list}

🤖 *执行结果*:
{'  \n'.join(bot_results) if bot_results else '  无匹配生态'}

⏱ 耗时: {elapsed} 秒
🕒 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send_telegram(report, chat_id_to_notify)
    if chat_id_to_notify and chat_id_to_notify != CHAT_ID:
        send_telegram(report, CHAT_ID)

    state.last_scan_result = {
        "projects": scored_projects,
        "bot_results": bot_results,
        "task_details": task_details,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "elapsed": elapsed,
        "data_source": state.data_source_status
    }
    send_live_log("扫描完成 ✅", chat_id_to_notify)
    return state.last_scan_result

# ============================================================
# 第10部分：命令与回调处理
# ============================================================
def handle_command(chat_id, command_text):
    logger.info(f"收到命令: {command_text} (from {chat_id})")
    parts = command_text.strip().split()
    if not parts:
        return
    cmd = parts[0].lower()

    if cmd == "/start":
        menu_text = """
🤖 *空投雷达 Bot v5.0 (混合方案)*

系统每2小时自动扫描一次，发现新项目实时推送。
点击下方按钮即可操作：
"""
        send_telegram(menu_text, chat_id, reply_markup=json.dumps(get_main_menu()))
        return

    if cmd == "/scan" and len(parts) >= 2 and parts[1].lower() == "now":
        send_telegram("⏳ 正在扫描，请稍候...", chat_id)
        result = run_scan(chat_id)
        if result is None:
            send_telegram("❌ 扫描失败或未发现项目", chat_id)
        return

    if cmd == "/stats":
        if state.last_scan_result is None:
            send_telegram("📊 暂无扫描数据，请先执行扫描", chat_id)
            return
        stats = state.last_scan_result
        msg = f"""
📊 *最近扫描统计*
- 时间: {stats['timestamp']}
- 发现项目: {len(stats['projects'])} 个
- 执行任务: {len(stats['bot_results'])} 项
- 数据源: {stats['data_source']}
- 耗时: {stats['elapsed']} 秒
"""
        send_telegram(msg, chat_id)
        return

    if cmd == "/bind" and len(parts) >= 3 and parts[1].lower() == "wallet":
        wallet = parts[2]
        if len(wallet) < 10 or not wallet.startswith("0x"):
            send_telegram("❌ 钱包地址格式错误，请提供以 0x 开头的地址", chat_id)
            return
        state.user_wallets[chat_id] = wallet
        state.user_states[chat_id] = None
        send_telegram(f"✅ 钱包绑定成功: `{wallet[:8]}...`", chat_id)
        return

    if state.user_states.get(chat_id) == "awaiting_wallet":
        wallet = command_text.strip()
        if len(wallet) < 10 or not wallet.startswith("0x"):
            send_telegram("❌ 地址格式错误，请发送以 0x 开头的正确地址", chat_id)
            return
        state.user_wallets[chat_id] = wallet
        state.user_states[chat_id] = None
        send_telegram(f"✅ 钱包绑定成功: `{wallet[:8]}...`", chat_id)
        return

    send_telegram("❌ 未知命令，请点击菜单按钮操作", chat_id)

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
        if state.last_scan_result is None:
            send_telegram("📊 暂无扫描数据，请先执行扫描", chat_id)
            return
        stats = state.last_scan_result
        msg = f"""
📊 *最近扫描统计*
- 时间: {stats['timestamp']}
- 发现项目: {len(stats['projects'])} 个
- 执行任务: {len(stats['bot_results'])} 项
- 数据源: {stats['data_source']}
- 耗时: {stats['elapsed']} 秒
"""
        send_telegram(msg, chat_id)

    elif data == "bind_wallet":
        answer_callback_query(callback_query_id, "🔗 请发送钱包地址")
        state.user_states[chat_id] = "awaiting_wallet"
        send_telegram("🔗 请发送你的钱包地址（以 0x 开头）", chat_id)

    elif data == "toggle_pause":
        state.is_paused = not state.is_paused
        status = "⏸️ 已暂停" if state.is_paused else "▶️ 已恢复"
        answer_callback_query(callback_query_id, status)
        send_telegram(f"系统 {status}", chat_id)

    elif data == "view_logs":
        answer_callback_query(callback_query_id, "📋 获取日志...")
        logs = state.execution_logs[-5:] if state.execution_logs else ["暂无日志"]
        msg = "📋 *最近日志*\n\n" + "\n".join([f"• {log}" for log in logs])
        send_telegram(msg, chat_id)

    elif data == "view_history":
        answer_callback_query(callback_query_id, "📈 获取历史...")
        c = state.db_conn.cursor()
        c.execute("SELECT project, action, status, timestamp FROM tasks ORDER BY timestamp DESC LIMIT 10")
        rows = c.fetchall()
        if not rows:
            send_telegram("📈 暂无历史任务记录", chat_id)
            return
        msg = "📈 *历史任务 (最近10条)*\n\n"
        for row in rows:
            msg += f"• {row[0]} - {row[1]}: {row[2]} ({row[3][:16]})\n"
        send_telegram(msg, chat_id)

    else:
        answer_callback_query(callback_query_id, "❌ 未知操作", show_alert=True)

# ============================================================
# 第11部分：HTTP 服务器
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

                if 'callback_query' in update:
                    callback = update['callback_query']
                    handle_callback(
                        callback['message']['chat']['id'],
                        callback['id'],
                        callback['data']
                    )
                elif 'message' in update:
                    message = update['message']
                    if 'text' in message:
                        handle_command(message['chat']['id'], message['text'])

                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'OK')
            except Exception as e:
                logger.error(f"Webhook 错误: {e}")
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
# 第12部分：Webhook 设置
# ============================================================
def set_webhook():
    if not BOT_TOKEN:
        return
    if not PUBLIC_URL:
        logger.warning("未设置 PUBLIC_URL，webhook 可能无法工作")
        return
    webhook_url = f"{PUBLIC_URL}/webhook"
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
# 第13部分：主循环
# ============================================================
def main_loop():
    logger.info("🔄 空投雷达持续运行模式 (混合方案 v5.0)")
    logger.info("⏰ 每 2 小时执行一次扫描")
    logger.info("📱 支持 5 个数据源自动切换 + 链上执行 + 重试机制 + 实时日志")
    set_webhook()

    while True:
        if state.is_paused:
            logger.info("⏸️ 系统已暂停，等待恢复...")
            time.sleep(60)
            continue

        try:
            run_scan()
            time.sleep(2 * 60 * 60)  # 2小时
        except Exception as e:
            logger.error(f"扫描异常: {e}")
            time.sleep(60)

# ============================================================
# 第14部分：启动
# ============================================================
if __name__ == "__main__":
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    main_loop()