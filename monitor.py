#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抖音作品监控 - 核心功能：
  1. 检测指定用户是否有新作品
  2. 有更新时通过 Telegram 通知你
  3. 提供无水印视频的下载链接

支持两种运行方式：
  - 本地运行: python monitor.py --once   (读取 config.yaml)
  - GitHub Actions: python monitor.py --ci (读取环境变量, 状态存 known_videos.json 提交回仓库)

环境变量 (GitHub Actions 用)：
  DOUYIN_COOKIE        抖音 Cookie
  USER_SEC_UID         要监控的用户 sec_uid
  USER_NAME            用户名 (可选)
  TELEGRAM_BOT_TOKEN   Telegram Bot Token
  TELEGRAM_CHAT_ID     Telegram Chat ID
"""

import sys
import os
import io
import json
import time
import hashlib
import struct
import argparse
from datetime import datetime
from urllib.parse import urlencode, urlparse, urlunparse, parse_qs

import httpx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

STATE_FILE = os.path.join(BASE_DIR, "known_videos.json")


# ============================================================
#  a_bogus 签名算法
# ============================================================
_SBOX = [7, 8, 5, 6, 2, 1, 13, 15, 9, 11, 10, 12, 3, 4, 0, 14]
_RKEYS = [0x0521, 0x1143, 0x2387, 0x4713, 0x8E27, 0x3C51,
          0x78A3, 0xF147, 0xE28F, 0xC51D, 0x8A3B, 0x1477]
_CONST = 0x61C88647


def _rotl(v, s):
    return ((v << (s % 32)) | (v >> (32 - s % 32))) & 0xFFFFFFFF


def _proc(arr, key):
    n = len(arr)
    out = []
    for i in range(n):
        v = arr[i]
        t = 0
        for b in range(4):
            byte = (v >> (b * 8)) & 0xFF
            si = (byte >> 4) & 0x0F
            t |= (_SBOX[si] << (b * 8 + 4)) | ((byte & 0x0F) << (b * 8))
        t = (t ^ (key + i * 0x9E3779B9 + arr[0])) & 0xFFFFFFFF
        t = _rotl(t, (i * 3 + 7) % 32)
        out.append(t)
    for i in range(n):
        out[i] = (out[i] ^ _rotl(out[(i + 1) % n], 7)) & 0xFFFFFFFF
        out[i] = (out[i] + _CONST) & 0xFFFFFFFF
    return out


def _token(arr):
    h = 0x811C9DC5
    for v in arr:
        h = (h ^ v) & 0xFFFFFFFF
        h = (h * 0x01000193) & 0xFFFFFFFF
    digest = hashlib.sha256(
        struct.pack('<%dI' % len(arr), *arr) + struct.pack('<I', h)
    ).digest()
    cs = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    bits = buf = 0
    out = []
    for byte in digest:
        buf = (buf << 8) | byte
        bits += 8
        while bits >= 6:
            bits -= 6
            out.append(cs[(buf >> bits) & 0x3F])
    return ''.join(out[:32])


def a_bogus(query, ua, body=""):
    q = query.encode()
    u = ua.encode()
    b = body.encode() if body else b''
    data = q + struct.pack('<H', len(q)) + u + struct.pack('<H', len(u)) + b + struct.pack('<H', len(b))
    seed = hashlib.md5(data).digest()
    while len(data) < 108:
        data += seed[:min(16, 108 - len(data))]
    data = data[:108]
    nwords = len(data) // 4
    arr = list(struct.unpack('<%dI' % nwords, data[:nwords * 4]))
    if not arr:
        arr = [0]
    for i in range(8):
        key = _RKEYS[i % len(_RKEYS)]
        arr = _proc(arr, key)
    return _token(arr)


def sign_url(url, ua, body=""):
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    flat = {k: (v[0] if len(v) == 1 else ','.join(v)) for k, v in params.items()}
    qstr = '&'.join(f"{k}={v}" for k, v in sorted(flat.items()))
    flat['a_bogus'] = a_bogus(qstr, ua, body)
    return urlunparse(parsed._replace(query=urlencode(flat)))


# ============================================================
#  抖音 API
# ============================================================
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

POST_URL = "https://www.douyin.com/aweme/v1/web/aweme/post/"


def clean_cookie(cookie):
    """
    清洗 Cookie 字符串中的非法字符。

    问题背景: GitHub Secrets 粘贴 Cookie 时可能带入换行/制表符等,
    HTTP 头不允许这些字符, 会导致 "Illegal header value" 错误。

    处理: 去掉所有控制字符和空白, 保留 ';' 分隔的 key=value 对。
    """
    if not cookie:
        return ""
    # 去掉换行/回车/制表符等控制字符
    cleaned = ''.join(ch for ch in cookie if ch >= ' ')
    # 若被 Secrets 打码成 *** 等异常值则原样返回 (调用方会校验)
    return cleaned.strip()


def _hdrs(cookie):
    return {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "User-Agent": UA,
        "Referer": "https://www.douyin.com/",
        "Cookie": clean_cookie(cookie),
    }


def fetch_videos(cookie, sec_uid, count=50):
    """获取用户作品列表。返回 (videos, error_message)"""
    params = {
        "device_platform": "webapp", "aid": "6383",
        "sec_user_id": sec_uid, "count": str(count), "max_cursor": "0",
        "version_code": "170400", "version_name": "17.4.0",
    }
    url = POST_URL + "?" + urlencode(params)
    signed = sign_url(url, UA)
    try:
        resp = httpx.get(signed, headers=_hdrs(cookie), timeout=20, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status_code") == 0:
                videos = []
                for item in data.get("aweme_list", []):
                    aid = item.get("aweme_id", "")
                    if not aid:
                        continue
                    vid = item.get("video", {})
                    urls = vid.get("play_addr", {}).get("url_list", [])
                    play = urls[0].replace("playwm", "play").replace("/playwm/", "/play/") if urls else ""
                    dur = vid.get("duration", 0)
                    if dur > 0:
                        dur = dur // 1000
                    covers = vid.get("cover", {}).get("url_list", [])
                    author = item.get("author", {})
                    videos.append({
                        "aweme_id": aid,
                        "title": item.get("desc", ""),
                        "author": author.get("nickname", ""),
                        "author_sec_uid": author.get("sec_uid", ""),
                        "duration": dur,
                        "cover": covers[0] if covers else "",
                        "play_url": play,
                    })
                return videos, ""
            return [], f"status_code={data.get('status_code')}: {data.get('status_msg', '')}"
        elif resp.status_code == 403:
            return [], "被限流(403), 请等几分钟后再试"
        return [], f"HTTP {resp.status_code}"
    except httpx.TimeoutException:
        return [], "请求超时"
    except Exception as e:
        return [], str(e)


# ============================================================
#  用户信息获取 (用户名/粉丝数/作品数)
# ============================================================
def fetch_user_info(cookie, sec_uid, ua=UA):
    """
    获取用户主页信息: 昵称、粉丝数、作品数等。

    返回 (user_info_dict, error_message)
    user_info_dict 包含: nickname, follower_count, following_count,
                          aweme_count, signature, avatar
    """
    params = {
        "device_platform": "webapp",
        "aid": "6383",
        "sec_user_id": sec_uid,
        "version_code": "170400",
        "version_name": "17.4.0",
    }
    url = "https://www.douyin.com/aweme/v1/web/user/profile/other/?" + urlencode(params)
    signed = sign_url(url, ua)
    try:
        resp = httpx.get(signed, headers=_hdrs(cookie), timeout=20, follow_redirects=True)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status_code") == 0:
                u = data.get("user", {}) or {}
                avatars = u.get("avatar_larger", {}).get("url_list", [])
                info = {
                    "nickname": u.get("nickname", ""),
                    "unique_id": u.get("unique_id", ""),      # 抖音号 (不会随改名变化)
                    "sec_uid": u.get("sec_uid", sec_uid),
                    "signature": u.get("signature", ""),
                    "follower_count": u.get("follower_count", 0),
                    "following_count": u.get("following_count", 0),
                    "aweme_count": u.get("aweme_count", 0),
                    "total_favorited": u.get("total_favorited", 0),
                    "avatar": avatars[0] if avatars else "",
                }
                return info, ""
            return {}, f"status_code={data.get('status_code')}: {data.get('status_msg', '')}"
        elif resp.status_code == 403:
            return {}, "被限流(403), 请等几分钟后再试"
        return {}, f"HTTP {resp.status_code}"
    except httpx.TimeoutException:
        return {}, "请求超时"
    except Exception as e:
        return {}, str(e)


# ============================================================
#  状态文件 (known_videos.json)
#  - 记录已知作品 ID, 跨运行持久化
#  - GitHub Actions 中提交回仓库保持状态
# ============================================================
def load_state():
    """加载已知作品 ID 集合 (仅含 aweme_id, 无隐私数据, 便于安全提交仓库)。
    返回 set[str]"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    # 新格式: ["aweme_id1", "aweme_id2", ...]
                    return set(str(x) for x in data)
                if isinstance(data, dict):
                    # 旧格式兼容: {"aweme_id": {...}} -> 取 keys
                    return set(data.keys())
        except Exception as e:
            print(f"[状态] 读取失败(将重建): {e}")
    return set()


def save_state(state):
    """保存已知作品 ID 集合 (仅 aweme_id)"""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(state), f, ensure_ascii=False, indent=2)


# ============================================================
#  Telegram 通知
# ============================================================
def send_telegram(bot_token, chat_id, text):
    if not bot_token or not chat_id:
        print("[Telegram] bot_token 或 chat_id 未配置")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = httpx.post(url, data={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=30)
        return resp.json().get("ok", False)
    except Exception as e:
        print(f"[Telegram] 发送失败: {e}")
        return False


def notify(bot_token, chat_id, video, no_wm_url="", user_info=None):
    """发送新作品通知 (包含用户信息: 抖音号/昵称/粉丝数/作品数)"""
    title = (video.get("title") or "无标题")[:80]
    author = video.get("author", "")
    aid = video.get("aweme_id", "")
    dur = video.get("duration", 0)
    spot = f"https://www.douyin.com/video/{aid}"

    # 用户信息行
    user_lines = []
    if user_info:
        # 优先显示抖音号 (唯一不变), 其次昵称
        nk = user_info.get("unique_id") or user_info.get("nickname") or author
        fans = user_info.get("follower_count")
        awemes = user_info.get("aweme_count")
        user_lines.append(f"👤 抖音号：<b>{nk}</b>")
        if fans is not None:
            user_lines.append(f"👥 粉丝：{fans:,}")
        if awemes is not None:
            user_lines.append(f"🎞 作品数：{awemes}")
    else:
        user_lines.append(f"👤 作者：<b>{author}</b>")

    lines = [
        "🎬 <b>新作品通知</b>",
    ]
    lines += user_lines
    lines += [
        f"📝 标题：{title}",
        f"⏱ 时长：{dur}秒" if dur else "",
        f"🆔 ID：<code>{aid}</code>",
        f"📄 原链接：{spot}",
    ]
    if no_wm_url:
        lines += ["", "⬇️ <b>无水印链接：</b>", f"<code>{no_wm_url}</code>"]
    text = "\n".join(line for line in lines if line)
    ok = send_telegram(bot_token, chat_id, text)
    print(f"  [通知] Telegram {'✅ 推送成功' if ok else '❌ 失败，请检查配置'}")
    return ok


# ============================================================
#  配置加载 (环境变量优先, 其次 config.yaml)
# ============================================================
def load_config():
    """加载配置。GitHub Actions 用环境变量, 本地用 config.yaml"""
    cfg = {
        "douyin": {"cookie": os.environ.get("DOUYIN_COOKIE", ""), "users": []},
        "notification": {"telegram": {
            "bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            "chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        }},
        "scheduler": {"check_interval_minutes": 60},
    }

    # CI 模式: 环境变量提供用户
    if os.environ.get("USER_SEC_UID"):
        cfg["douyin"]["users"].append({
            "name": os.environ.get("USER_NAME", "监控用户"),
            "sec_uid": os.environ["USER_SEC_UID"],
        })

    # 尝试合并 config.yaml (本地运行)
    cfg_path = os.path.join(BASE_DIR, "config.yaml")
    if os.path.exists(cfg_path):
        try:
            import yaml
            with open(cfg_path, encoding="utf-8") as f:
                y = yaml.safe_load(f) or {}
            if not cfg["douyin"]["cookie"]:
                cfg["douyin"]["cookie"] = y.get("douyin", {}).get("cookie", "")
            if not cfg["douyin"]["users"] and y.get("douyin", {}).get("users"):
                cfg["douyin"]["users"] = y["douyin"]["users"]
            if not cfg["notification"]["telegram"]["bot_token"]:
                cfg["notification"]["telegram"]["bot_token"] = \
                    y.get("notification", {}).get("telegram", {}).get("bot_token", "")
            if not cfg["notification"]["telegram"]["chat_id"]:
                cfg["notification"]["telegram"]["chat_id"] = \
                    y.get("notification", {}).get("telegram", {}).get("chat_id", "")
            cfg["scheduler"]["check_interval_minutes"] = \
                y.get("scheduler", {}).get("check_interval_minutes", 60)
        except Exception:
            pass

    return cfg


# ============================================================
#  主流程
# ============================================================
def check_all(cfg, state, mark_known_only=False):
    """检测所有用户，返回新作品总数"""
    cookie = cfg["douyin"]["cookie"]
    total_new = 0

    for user in cfg["douyin"].get("users", []):
        name = user.get("name", "")
        sec_uid = user.get("sec_uid", "")
        if not sec_uid:
            print(f"\n[{name}] 无 sec_uid，跳过")
            continue

        print(f"\n🔍 {name}")

        # 先获取用户信息 (抖音号/昵称/粉丝数/作品数)
        user_info, info_err = fetch_user_info(cookie, sec_uid)
        if user_info:
            uniq = user_info.get("unique_id", "")
            nk = user_info.get("nickname", "")
            fans = user_info.get("follower_count", 0)
            awemes = user_info.get("aweme_count", 0)
            display = uniq if uniq else nk
            print(f"    抖音号: {display} | 昵称: {nk} | 粉丝: {fans:,} | 作品: {awemes}")
        elif info_err:
            print(f"    [用户信息] {info_err}")

        videos, err = fetch_videos(cookie, sec_uid)

        if err:
            print(f"  ❌ {err}")
            continue

        if not videos:
            print(f"  ⚠️ 未获取到作品")
            continue

        new_count = 0
        for v in videos:
            aid = v["aweme_id"]
            # 注意: 不能遇到已知作品就 break!
            # 抖音会把"置顶"作品放在列表最前, 列表并非严格按时间排序,
            # 若在最前的置顶作品处 break, 会漏掉后面真正的新作品。
            if aid in state:
                continue
            new_count += 1

            no_wm = v.get("play_url", "")
            if not no_wm:
                # 列表里没地址时用详情接口
                from urllib.parse import urlencode as _ue
                params = {"device_platform": "webapp", "aid": "6383",
                          "aweme_id": aid, "version_code": "170400", "version_name": "17.4.0"}
                durl = "https://www.douyin.com/aweme/v1/web/aweme/detail/?" + _ue(params)
                try:
                    r = httpx.get(sign_url(durl, UA), headers=_hdrs(cookie), timeout=20)
                    detail = r.json().get("aweme_detail", {}) or {}
                    for key in ("play_addr", "download_addr"):
                        ul = detail.get("video", {}).get(key, {}).get("url_list", [])
                        if ul:
                            no_wm = ul[0].replace("playwm", "play").replace("/playwm/", "/play/")
                            break
                except Exception:
                    pass

            # 通知
            if not mark_known_only:
                print(f"  🆕 {v['title'][:50]}  (时长{v['duration']}秒)")
                if no_wm:
                    print(f"     ⬇️ {no_wm[:120]}")
                notify(cfg["notification"]["telegram"].get("bot_token", ""),
                       cfg["notification"]["telegram"].get("chat_id", ""),
                       v, no_wm, user_info)

            # 记录 (仅作品 ID, 无隐私数据)
            state.add(aid)

        total_new += new_count
        if new_count == 0:
            print(f"  ✅ 暂无新作品（本次获取 {len(videos)} 个作品均已知）")
        else:
            print(f"  🎉 发现 {new_count} 个新作品（本次获取 {len(videos)} 个作品）")

        time.sleep(3)
    return total_new


def main():
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        os.system('')

    parser = argparse.ArgumentParser(description="抖音作品监控")
    parser.add_argument("--once", action="store_true", help="只检测一次后退出")
    parser.add_argument("--ci", action="store_true", help="CI/GitHub Actions 模式")
    parser.add_argument("--init", action="store_true", help="建立基线(不通知)")
    parser.add_argument("--test", action="store_true", help="发送 Telegram 测试消息")
    args = parser.parse_args()

    cfg = load_config()
    cookie = clean_cookie(cfg["douyin"]["cookie"])
    if not cookie:
        print("[!] 未配置抖音 cookie（环境变量 DOUYIN_COOKIE 或 config.yaml）")
        sys.exit(1)
    if len(cookie) < 50:
        print("[!] 抖音 Cookie 内容异常过短，请检查 Secret 是否配置正确")
        print("    获取方式: 浏览器登录 douyin.com → F12 → Network → 复制 Cookie")
        sys.exit(1)
    if "=" not in cookie or ";" not in cookie:
        print("[!] 抖音 Cookie 格式异常（应包含多个 key=value; ... 对）")
        print("    请重新从浏览器复制完整的 Cookie 字符串")
        sys.exit(1)

    users = [u for u in cfg["douyin"].get("users", []) if u.get("sec_uid")]
    if not users:
        print("[!] 未配置要监控的用户（环境变量 USER_SEC_UID 或 config.yaml）")
        sys.exit(1)

    bt = cfg["notification"]["telegram"].get("bot_token", "")
    cid = cfg["notification"]["telegram"].get("chat_id", "")
    if not bt or not cid:
        print("⚠️  Telegram 未配置 (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")

    print("=" * 55)
    print("   🎬 抖音作品监控")
    print("   新作品检测 → Telegram 通知 → 无水印链接")
    print("=" * 55)
    print(f"   监控用户: {len(users)} 个")
    for u in users:
        print(f"     - {u.get('name', '?')} ({u['sec_uid'][:25]}...)")
    print()

    # 测试通知
    if args.test:
        ok = send_telegram(bt, cid, "✅ <b>抖音监控测试成功</b>\n\n如收到此消息，通知配置正常！")
        print("✅ 测试消息已发送" if ok else "❌ 发送失败")
        return

    state = load_state()

    # 建立基线
    if args.init:
        print("建立已知作品基线（不触发通知）...")
        check_all(cfg, state, mark_known_only=True)
        save_state(state)
        print(f"\n✅ 基线已建立！共记录 {len(state)} 个已知作品")
        return

    # 单次/CI 检测
    if args.once or args.ci:
        n = check_all(cfg, state)
        save_state(state)
        print(f"\n{'=' * 55}")
        print(f"本次检测完成，共发现 {n} 个新作品，状态文件已更新")
        return

    # 定时循环 (本地)
    interval = cfg["scheduler"].get("check_interval_minutes", 60)
    print(f"⏰ 定时检测，间隔 {interval} 分钟（Ctrl+C 停止）\n")
    while True:
        try:
            n = check_all(cfg, state)
            save_state(state)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"\n⚠️ 检测出错: {e}")
        print(f"\n⏳ {interval} 分钟后再次检测...\n")
        try:
            time.sleep(interval * 60)
        except KeyboardInterrupt:
            break
    print("\n已停止")


if __name__ == "__main__":
    main()