# 三位一体空投系统

融合 AI 情报 + Hunter 验证 + 专用机器人的自动化空投系统。

## Render 环境变量

| 变量 | 说明 | 是否必须 |
|------|------|----------|
| `BOT_TOKEN` | Telegram Bot Token | ✅ 必须 |
| `CHAT_ID` | Telegram 用户 ID | ✅ 必须 |
| `WALLET_ADDRESSES` | 钱包地址（多个用逗号分隔） | ❌ 可选 |

## 运行方式
- 自动：每 6 小时运行一次
- 手动：Actions → Run workflow