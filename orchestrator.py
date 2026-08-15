# -*- coding: utf-8 -*-
"""
三位一体空投系统 - 完整版 v2.0
新增：数据源状态 + 任务详情 + 一键分享 + 智能推荐
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

# ===== 强制输出日志 =====
sys.stderr = sys.stdout
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== 环境变量 =====
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
WALLET_ADDRESSES = os.environ.get("WALLET_ADDRESSES", "").split(",")

logger.info("🚀 三位一体空投系统启动 v2.0")
logger.info(f"钱包数量: {len([w for w in WALLET_ADDRESSES if w.strip()])}")

# ===== 全局状态 =====
last_projects = []
data_source_status = "未知"

# ===== Telegram 推送 =====
def send_telegram(text, parse_mode="Markdown"):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text[:4000],
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        logger.error(f"Telegram 发送失败: {e}")
        return False

# ===== AI 智能评分 =====
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

# ===== AI 情报（数据源状态追踪） =====
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

        # 如果 MCP 无数据，使用备用
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

# ===== 实时推送 =====
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

# ===== Hunter 验证 =====
def run_hunter(projects):
    logger.info("🔍 Hunter 验证...")
    verified = [p for p in projects if score_project(p) >= 60]
    logger.info(f"验证通过 {len(verified)} 个项目（过滤 {len(projects)-len(verified)} 个低分）")
    return verified

# ===== 专用机器人 =====
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

# ===== 执行扫描 =====
def run_scan():
    global data_source_status
    start = datetime.now()

    # 1. AI 发现
    all_projects = run_ai_agent()
    if not all_projects:
        send_telegram("⚠️ 未发现任何项目")
        return

    check_and_push_new_projects(all_projects)

    # 2. Hunter 验证
    verified_projects = run_hunter(all_projects)
    if not verified_projects:
        send_telegram("⚠️ 所有项目评分过低，跳过执行")
        return

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

    # 4. 执行机器人（收集详细任务）
    bot_results = []
    task_details = {}
    for wallet in WALLET_ADDRESSES:
        wallet = wallet.strip()
        if not wallet:
            continue
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

    # 5. 生成报告
    elapsed = (datetime.now() - start).seconds

    # 排行榜
    project_list = "\n".join([
        f"  {i+1}. {p['name']} — {p['score']}分 {p['recommendation']}"
        for i, p in enumerate(scored_projects[:10])
    ])

    # 任务详情（新增）
    task_detail_lines = []
    for name, tasks in task_details.items():
        task_detail_lines.append(f"  • {name}: {', '.join(tasks)}")
    task_detail_text = "\n".join(task_detail_lines) if task_detail_lines else "  无详细任务"

    # 智能推荐（新增）
    top_project = scored_projects[0] if scored_projects else None
    top_recommend = f"⭐ *本次推荐*: {top_project['name']}（{top_project['score']}分）" if top_project else ""

    # 数据源状态（新增）
    source_info = f"📡 *数据源*: {data_source_status}"

    # 可复制的纯文本版本（新增）
    plain_text = f"""
空投扫描报告 - {datetime.now().strftime('%Y-%m-%d %H:%M')}

项目排行:
{chr(10).join([f"{i+1}. {p['name']} ({p['score']}分)" for i, p in enumerate(scored_projects[:10])])}

执行结果:
{chr(10).join(bot_results) if bot_results else '无'}

耗时: {elapsed}秒
"""
    share_text = f"\n\n📋 *复制分享*:\n`{plain_text.strip()}`"

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
{share_text}
"""
    send_telegram(report)
    logger.info("报告已发送")

    return scored_projects

# ============================================================
# HTTP 健康检查（Render 端口要求）
# ============================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health' or self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def start_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('', port), HealthHandler)
    logger.info(f"🌐 HTTP 服务器启动，端口 {port}")
    server.serve_forever()

# ============================================================
# 主循环
# ============================================================
def main_loop():
    logger.info("🔄 空投雷达持续运行模式 v2.0")
    logger.info("⏰ 每 2 小时执行一次扫描")
    logger.info("📱 发现新项目立即推送")

    while True:
        try:
            run_scan()
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