# 🎬 抖音作品监控 (GitHub Actions 自动版)

自动检测抖音用户是否有新作品，有新作品时通过 **Telegram 推送到你的手机**，并提供**无水印视频下载链接**。

## 功能

| 功能 | 说明 |
|------|------|
| 🔍 新作品检测 | 每小时自动检测指定用户是否发布新作品 |
| 📱 Telegram 通知 | 发现新作品立即推送：作者、标题、时长、原链接 |
| ⬇️ 无水印链接 | 推送中包含无水印视频下载地址 |
| 🚀 云端运行 | GitHub Actions 自动运行，无需电脑开机 |

---

## 快速部署 (3 步)

### 第 1 步：创建 GitHub 仓库

1. 打开 [github.com](https://github.com)，点右上角 **+** → **New repository**
2. 仓库名随意，如 `douyin-monitor`
3. **务必选择 Private（私有）**，因为会存放你的抖音 Cookie
4. Create repository

### 第 2 步：上传代码

在命令行执行（替换成你的仓库地址）：

```bash
cd C:\Users\Redmi\Desktop\自动上传
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/你的用户名/douyin-monitor.git
git push -u origin main
```

> ⚠️ 推送时 GitHub 会要求登录，输入你的 GitHub 用户名和 **Personal Access Token**（不是密码）。
> 创建 Token：GitHub → Settings → Developer settings → Personal access tokens → Generate new token → 勾选 `repo` 权限。

### 第 3 步：配置 Secrets (密钥)

在 GitHub 仓库页面：**Settings → Secrets and variables → Actions → New repository secret**

需要添加 **5 个** Secret（真实数据只保存在 Secrets 里，不要写进代码/文档）：

| Secret 名称 | 值 | 说明 |
|-------------|-----|------|
| `DOUYIN_COOKIE` | 你的抖音 Cookie 整串 | 浏览器 F12 复制 |
| `USER_SEC_UID` | 目标用户主页 URL 中 `/user/` 后面的 `MS4wLj...` 部分 | 要监控的用户 |
| `USER_NAME` | 目标用户的**抖音号**（数字，如 `89534762782`） | 用于显示防混淆 |
| `TELEGRAM_BOT_TOKEN` | 你的 Bot Token | 从 @BotFather 获取 |
| `TELEGRAM_CHAT_ID` | 你的 Chat ID | 数字 |

配置完成后，第一次运行可在仓库 **Actions 页 → 抖音作品监控 → Run workflow** 手动触发。

之后每天 **每小时自动运行一次**（北京时间），发现新作品自动推送。

---

## 工作原理

```
GitHub Actions (每小时)
    │
    ▼
python monitor.py --ci
    │  ├─ 读取 Secrets (Cookie/Telegram)
    │  ├─ 调用抖音 API (a_bogus 签名)
    │  ├─ 对比 known_videos.json (仓库内状态)
    │  ├─ 有新作品 → Telegram 推送 (含无水印链接)
    │  └─ 更新 known_videos.json
    │
    ▼
git commit 状态回仓库 (跨运行持久化)
```

**状态持久化**：`known_videos.json` 记录已通知过的作品 ID（仅含 ID，无隐私数据），每次运行后自动提交回仓库，避免重复通知。若不想提交任何状态到 GitHub，可在 `.gitignore` 中添加 `known_videos.json`（代价是每次运行都会重新提醒历史作品）。

---

## 本地运行（可选）

```bash
python monitor.py --once   # 检测一次
python monitor.py --init   # 建立基线（不通知）
python monitor.py --test   # 测试 Telegram
python monitor.py          # 本地循环检测
```

---

## 常见问题

**Q: 检测不到新作品？**
A: 检查 `DOUYIN_COOKIE` 是否过期（重新在浏览器复制 Cookie 更新 Secret）。

**Q: Telegram 收不到通知？**
A: 配置后先手动触发一次，查看 Actions 日志；也可本地运行 `python monitor.py --test` 验证。

**Q: 想监控其他用户？**
A: 打开对方主页，复制 URL 中 `/user/` 后面的 `MS4wLj...` 部分，更新 `USER_SEC_UID` Secret；同时把对方抖音号填入 `USER_NAME`。

**Q: 无水印链接打不开？**
A: 链接有时效性（数小时内有效），请尽快下载；或用原链接到网页打开。

---

## ⚠️ 注意事项

- **Cookie 会过期**（约几天到几周），过期后需重新获取并更新 `DOUYIN_COOKIE` Secret
- 抖音 API 有频率限制，请勿手动高频触发（每小时一次已足够安全）
- 仅用于个人学习/合法用途，请遵守相关法律法规和平台规则
- 仓库必须是 **Private**，防止 Cookie 泄露