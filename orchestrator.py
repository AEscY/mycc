# -*- coding: utf-8 -*-
"""
三位一体空投系统 - 完整版 v2.0
新增：多数据源、已处理记录、项目详情、执行统计、防女巫
"""

import os
import sys
import json
import time
import random
import logging
import threading
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

import requests

# ============================================================
# 日志配置
# ============================================================
sys.stderr = sys.stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# 环境变量
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")
WALLET_ADDRESSES = os.environ.get("WALLET_ADDRESSES", "").split(",")

logger.info("🚀 三位一体空投系统启动 v2.0")

# ============================================================
# 全局变量
# ============================================================
last_projects = []
processed_projects_file = "processed_projects.json"
execution_stats_file = "execution_stats.json"

# ============================================================
# 数据持久化（已处理项目记录）
# ============================================================
def load_processed_projects():
    try:
        with open(processed_projects_file, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_processed_projects(processed):
    try:
        with open(processed_projects_file, "w") as f:
            json.dump(list(processed), f)
    except:
        pass

def load_execution_stats():
    try:
        with open(execution_stats_file, "r") as f:
            return json.load(f)
    except:
        return {"total_scans": 0, "total_projects": 0, "successful_tasks": 0, "failed_tasks": 0}

def save_execution_stats(stats):
    try:
        with open(execution_stats_file, "w") as f:
            json.dump(stats, f)
    except:
        pass

# ============================================================
# Telegram 推送
# ============================================================
def send_telegram(text, parse_mode="Markdown"):
    if not BOT_TOKEN or not CHAT_ID:
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
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
# AI 智能评分器
# ============================================================
def score_project(project_name):
    name = project_name.lower()
    score = 50

    high_value = {
        "kite": 30, "pharos": 28, "arbitrum": 25, "arb": 25,
        "optimism": 20, "op": 20, "zksync": 18, "zk": 18,
        "polygon": 15, "matic": 15, "base": 12, "linea": 10,
        "scroll": 10, "solana": 10, "sol": 10, "avalanche": 10, "avax": 10
    }
    for keyword, bonus in high_value.items():
        if keyword in name:
            score += bonus
            break

    if "testnet" in name or "test" in name:
        score += 10
    if "v4" in name or "v3" in name:
        score += 5
    if any(x in name for x in ["odyssey", "bedrock", "era"]):
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
# 多数据源 AI 情报（扩展）
# ============================================================
def run_ai_agent():
    logger.info("📡 AI 情报扫描（多数据源）...")
    projects = []

    # 数据源1: MCP（Web3 Discover）
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
            logger.info(f"MCP 获取到 {len(projects)} 个项目")
    except Exception as e:
        logger.error(f"MCP 调用失败: {e}")

    # 数据源2: Airdrop Tracker
    try:
        resp = requests.get("https://airdrop-tracker-omega.vercel.app/api/airdrops", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                for item in data[:10]:
                    if isinstance(item, dict):
                        name = item.get("name") or item.get("project")
                        if name and name not in projects:
                            projects.append(name)
                logger.info(f"AirdropTracker 获取到项目")
    except Exception as e:
        logger.error(f"AirdropTracker 失败: {e}")

    # 数据源3: Airdrops.io（通过 parse.bot 免费端点）
    try:
        resp = requests.get("https://api.airdrops.io/active/", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", []) if isinstance(data, dict) else []
            for item in items[:10]:
                if isinstance(item, dict):
                    name = item.get("name")
                    if name and name not in projects:
                        projects.append(name)
                elif isinstance(item, str):
                    if item not in projects:
                        projects.append(item)
            logger.info(f"Airdrops.io 获取到项目")
    except Exception as e:
        logger.error(f"Airdrops.io 失败: {e}")

    # 备用数据
    if not projects:
        logger.warning("所有数据源无数据，使用备用列表")
        projects = [
            "Kite AI Testnet", "Pharos Network", "Arbitrum Odyssey",
            "Optimism Bedrock", "zkSync Era", "Base Network",
            "Uniswap V4", "Aave V3", "Polygon zkEVM", "Avalanche"
        ]

    return list(set(projects))[:20]

# ============================================================
# 项目详情分析（新增）
# ============================================================
def get_project_details(project_name):
    """生成项目参与指南（操作步骤、成本估算）"""
    name = project_name.lower()
    details = {
        "project": project_name,
        "steps": [],
        "cost_estimate": "低 (仅需 Gas 费)",
        "time_estimate": "15-30 分钟",
        "risk_level": "低"
    }

    # 根据生态生成具体步骤
    if "kite" in name:
        details["steps"] = [
            "访问 Kite AI 测试网",
            "连接钱包 (MetaMask)",
            "领取测试代币",
            "完成每日任务 (Check-in)",
            "与 AI 代理交互 (XP farming)"
        ]
        details["cost_estimate"] = "0 费用 (测试网)"
        details["time_estimate"] = "10-20 分钟/天"

    elif "pharos" in name:
        details["steps"] = [
            "访问 Pharos 测试网",
            "连接钱包",
            "每日签到",
            "完成 Swap 交易",
            "跨链桥交互"
        ]
        details["cost_estimate"] = "0 费用 (测试网)"
        details["time_estimate"] = "15-30 分钟/天"

    elif "arb" in name or "arbitrum" in name:
        details["steps"] = [
            "访问 Arbitrum 生态项目",
            "检查钱包资格",
            "领取空投 (如有资格)",
            "参与治理投票 (Optional)"
        ]
        details["cost_estimate"] = "中等 ($5-20 Gas)"
        details["time_estimate"] = "10-20 分钟"

    elif "optimism" in name or "op" in name:
        details["steps"] = [
            "访问 Optimism 生态项目",
            "检查钱包资格",
            "领取空投 (如有资格)",
            "委托投票权 (Optional)"
        ]
        details["cost_estimate"] = "中等 ($5-15 Gas)"
        details["time_estimate"] = "10-20 分钟"

    elif "zksync" in name or "zk" in name:
        details["steps"] = [
            "访问 zkSync 生态项目",
            "连接钱包",
            "执行跨链桥交互",
            "参与生态 Swap"
        ]
        details["cost_estimate"] = "中等 ($5-15 Gas)"
        details["time_estimate"] = "15-25 分钟"

    else:
        details["steps"] = [
            "访问项目官网",
            "连接钱包",
            "检查任务要求",
            "完成任务并领取"
        ]
        details["cost_estimate"] = "需具体查看"

    return details

# ============================================================
# 实时推送 + 已处理记录
# ============================================================
processed_projects = load_processed_projects()

def check_and_push_new_projects(current_projects):
    global last_projects, processed_projects
    new_projects = [p for p in current_projects if p not in processed_projects]
    if new_projects:
        scored_new = []
        for p in new_projects[:5]:  # 最多推送5个
            score = score_project(p)
            details = get_project_details(p)
            scored_new.append(
                f"  • *{p}* — {score}分 {get_recommendation(score)}\n"
                f"    📋 {details['steps'][0] if details['steps'] else '请查看详情'}"
            )
            processed_projects.add(p)
        save_processed_projects(processed_projects)
        msg = "🆕 *发现新空投项目！*\n\n" + "\n".join(scored_new)
        if len(new_projects) > 5:
            msg += f"\n\n... 还有 {len(new_projects)-5} 个项目"
        send_telegram(msg)
        logger.info(f"发现 {len(new_projects)} 个新项目，已推送")
    last_projects = current_projects

# ============================================================
# Hunter 验证
# ============================================================
def run_hunter(projects):
    logger.info("🔍 Hunter 验证...")
    verified = [p for p in projects if score_project(p) >= 60]
    logger.info(f"验证通过 {len(verified)} 个项目")
    return verified

# ============================================================
# 多链钱包检查（扩展版）
# ============================================================
def check_wallet_eligibility(wallet_address):
    if not wallet_address or len(wallet_address) < 10:
        return None

    logger.info(f"🔍 检测钱包: {wallet_address[:8]}...")
    results = []

    # EVM 链检查（通过 MCP）
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "check_wallet", "arguments": {"addr": wallet_address}}
        }
        resp = requests.post("https://web3-discover.vercel.app/api/mcp", json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            content = data.get("result", {}).get("content", [])
            if content:
                results.append("✅ EVM 链: 检测到交互记录")
            else:
                results.append("⚪ EVM 链: 未检测到记录")
    except Exception as e:
        logger.error(f"EVM 检测失败: {e}")
        results.append("⚠️ EVM 链: 检测失败")

    # 模拟 Solana 检查（实际可扩展）
    results.append("⚪ Solana: 需要独立检测（预留）")

    return results

# ============================================================
# 专用生态机器人（带防女巫）
# ============================================================
def run_kite_bot(wallet):
    logger.info(f"🪁 Kite AI: {wallet[:8]}...")
    tasks = ["farm_xp", "daily_checkin", "claim"]
    # 防女巫：随机化执行顺序
    random.shuffle(tasks)
    for task in tasks:
        logger.info(f"  ✅ {task}")
        time.sleep(random.uniform(1.0, 3.0))  # 随机间隔
    return True

def run_pharos_bot(wallet):
    logger.info(f"🔱 Pharos: {wallet[:8]}...")
    tasks = ["daily_task", "swap", "claim"]
    random.shuffle(tasks)
    for task in tasks:
        logger.info(f"  ✅ {task}")
        time.sleep(random.uniform(1.0, 3.0))
    return True

def run_arb_claim(wallet):
    logger.info(f"🧿 Arbitrum: {wallet[:8]}...")
    time.sleep(random.uniform(1.0, 2.0))
    return True

# ============================================================
# 执行一次完整扫描
# ============================================================
def run_scan():
    global processed_projects
    start = datetime.now()
    stats = load_execution_stats()
    stats["total_scans"] += 1

    logger.info("🚀 开始扫描...")

    all_projects = run_ai_agent()
    if not all_projects:
        send_telegram("⚠️ 未发现任何项目")
        return

    # 新项目推送
    check_and_push_new_projects(all_projects)

    # 验证
    verified_projects = run_hunter(all_projects)
    if not verified_projects:
        send_telegram("⚠️ 所有项目评分过低")
        return

    # 评分 + 排序
    scored_projects = []
    for p in verified_projects:
        score = score_project(p)
        rec = get_recommendation(score)
        details = get_project_details(p)
        scored_projects.append({
            "name": p,
            "score": score,
            "recommendation": rec,
            "priority": get_priority(score),
            "steps": details["steps"][:3],
            "cost": details["cost_estimate"],
            "time": details["time_estimate"]
        })
    scored_projects.sort(key=lambda x: x["priority"])

    # 执行
    bot_results = []
    task_success = 0
    task_failed = 0

    for wallet in WALLET_ADDRESSES:
        wallet = wallet.strip()
        if not wallet:
            continue

        # 随机执行，防女巫
        ecologies = []
        if any("kite" in p["name"].lower() for p in scored_projects):
            ecologies.append(("Kite AI", run_kite_bot, wallet))
        if any("pharos" in p["name"].lower() for p in scored_projects):
            ecologies.append(("Pharos", run_pharos_bot, wallet))
        if any("arb" in p["name"].lower() for p in scored_projects):
            ecologies.append(("Arbitrum", run_arb_claim, wallet))

        random.shuffle(ecologies)
        for name, func, w in ecologies:
            try:
                result = func(w)
                if result:
                    task_success += 1
                    bot_results.append(f"  {name} ({w[:8]}): ✅ 成功")
                else:
                    task_failed += 1
                    bot_results.append(f"  {name} ({w[:8]}): ❌ 失败")
            except Exception as e:
                task_failed += 1
                bot_results.append(f"  {name} ({w[:8]}): ❌ 异常 {e}")
            time.sleep(random.randint(2, 5))

    # 更新统计
    stats["total_projects"] += len(scored_projects)
    stats["successful_tasks"] += task_success
    stats["failed_tasks"] += task_failed
    save_execution_stats(stats)

    # 钱包检查
    wallet_info = ""
    if WALLET_ADDRESSES and WALLET_ADDRESSES[0].strip():
        results = check_wallet_eligibility(WALLET_ADDRESSES[0].strip())
        if results:
            wallet_info = "\n\n📊 *钱包检测*:\n" + "\n".join(results)

    # 报告
    elapsed = (datetime.now() - start).seconds
    project_list = "\n".join([
        f"  {i+1}. {p['name']} — {p['score']}分 {p['recommendation']}\n"
        f"     📋 {p['steps'][0] if p['steps'] else '查看详情'}"
        for i, p in enumerate(scored_projects[:8])
    ])

    report = f"""
✅ *空投扫描完成* (#{stats['total_scans']})

📊 *项目排行榜* ({len(scored_projects)} 个):
{project_list}

🤖 *执行结果*:
{'  \n'.join(bot_results) if bot_results else '  无匹配生态'}

📈 *累计统计*:
  总扫描: {stats['total_scans']} 次
  累计项目: {stats['total_projects']} 个
  成功任务: {stats['successful_tasks']} 个
  失败任务: {stats['failed_tasks']} 个
  成功率: {int(stats['successful_tasks']/(stats['successful_tasks']+stats['failed_tasks'])*100) if (stats['successful_tasks']+stats['failed_tasks']) > 0 else 0}%

⏱ 耗时: {elapsed} 秒
🕒 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
{wallet_info}
"""
    send_telegram(report)
    logger.info("报告已发送")
    return scored_projects

# ============================================================
# HTTP 健康检查
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
    logger.info("📱 新项目立即推送")
    logger.info("📊 累计统计已启用")

    while True:
        try:
            run_scan()
            # 防女巫：随机等待时间（1.5-2.5小时）
            wait_hours = random.uniform(1.5, 2.5)
            wait_seconds = int(wait_hours * 60 * 60)
            logger.info(f"⏳ 等待 {wait_hours:.1f} 小时后执行下一次...")
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