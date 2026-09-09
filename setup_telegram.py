#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 通知配置指引

运行后按步骤操作：
  python setup_telegram.py          # 显示配置指南
  python setup_telegram.py --token BOT_TOKEN   # 验证 Bot Token
  python setup_telegram.py --chat CHAT_ID      # 填入 Chat ID 并测试
"""
import sys
import io
import os
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    os.system('')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

import httpx


def get_config():
    import yaml
    with open("config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(cfg):
    import yaml
    with open("config.yaml", "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def test_bot(token):
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        r = httpx.get(url, timeout=10)
        j = r.json()
        if j.get("ok"):
            b = j["result"]
            print(f"✅ Bot 验证成功！")
            print(f"   名称: @{b.get('username', '未知')}")
            print(f"   显示: {b.get('first_name', '')} {b.get('last_name', '')}")
            return True
        else:
            print(f"❌ Token 无效: {j.get('description', '')}")
            return False
    except Exception as e:
        print(f"❌ 连接失败: {e}")
        return False


def get_chat_id(token):
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        r = httpx.get(url, timeout=10)
        j = r.json()
        if j.get("ok"):
            results = j.get("result", [])
            if not results:
                print("❌ 未找到任何消息记录")
                print("   请先向你的 Bot 发送一条消息（随便发什么），然后重新运行本命令")
                return None
            # 取最后一条消息的 chat_id
            for update in reversed(results):
                msg = update.get("message") or update.get("edited_message")
                if msg:
                    chat = msg.get("chat", {})
                    chat_id = chat.get("id")
                    user = msg.get("from", {})
                    name = f"{user.get('first_name', '')} {user.get('last_name', '')}".strip()
                    username = user.get("username", "")
                    print(f"✅ 找到 Chat ID！")
                    print(f"   用户: {name} (@{username})")
                    print(f"   Chat ID: {chat_id}")
                    return str(chat_id)
            print("❌ 未找到有效消息，请先向 Bot 发送一条消息")
        return None
    except Exception as e:
        print(f"❌ 获取失败: {e}")
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Telegram 配置工具")
    parser.add_argument("--token", help="验证 Bot Token")
    parser.add_argument("--chat", help="获取 Chat ID（需要已向 Bot 发过消息）")
    parser.add_argument("--save", action="store_true", help="保存配置")
    args = parser.parse_args()

    if args.token:
        ok = test_bot(args.token)
        if ok:
            cfg = get_config()
            cfg.setdefault("notification", {}).setdefault("telegram", {})["bot_token"] = args.token
            save_config(cfg)
            print("✅ Bot Token 已保存")
        return

    if args.chat:
        print("⚠️ 请确保你已向 Bot 发送过任意消息")
        input("按 Enter 继续...")
        cfg = get_config()
        token = cfg.get("notification", {}).get("telegram", {}).get("bot_token", "")
        if not token:
            print("❌ 请先验证 Bot Token")
            return
        chat_id = get_chat_id(token)
        if chat_id:
            cfg["notification"]["telegram"]["chat_id"] = chat_id
            save_config(cfg)
            print(f"✅ Chat ID {chat_id} 已保存")
            # 发送测试消息
            print("发送测试消息...")
            ok = httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": chat_id, "text": "✅ 抖音监控通知测试成功！", "parse_mode": "HTML"},
                timeout=30
            ).json().get("ok", False)
            print("✅ 测试消息已发送" if ok else "❌ 测试消息发送失败")
        return

    # 显示指南
    print("=" * 55)
    print("   📱 Telegram 通知配置指南")
    print("=" * 55)
    print("""
第1步：创建 Telegram Bot
  1. 打开 Telegram，搜索 @BotFather 并打开对话
  2. 发送命令: /newbot
  3. 按提示输入 Bot 名称（如: 抖音监控助手）
  4. 按提示输入 Bot 用户名（如: douyin_monitor_bot）
  5. BotFather 会回复给你一个 Bot Token（一串数字:字母）
  6. 复制这个 Token

第2步：验证 Token 并保存
  运行: python setup_telegram.py --token 你的TOKEN

第3步：获取你的 Chat ID
  1. 在 Telegram 搜索你刚创建的 Bot
  2. 点击 "Start" 或发送任意消息
  3. 运行: python setup_telegram.py --chat
  4. 程序会自动检测并保存你的 Chat ID

第4步：完成！
  现在运行 python monitor.py 即可开始监控

如需修改配置，编辑 config.yaml:
  - douyin.cookie: 抖音 Cookie
  - douyin.users: 监控的用户列表
  - notification.telegram: Telegram 通知配置
""")


if __name__ == "__main__":
    main()
