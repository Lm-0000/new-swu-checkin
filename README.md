该方法使用drissionpag库、基于模拟人在浏览器登录从而获取token，实现swu钉钉寝室自动打卡，在获取token部分可能失败。 

---
注释：一、该程序工作流未添加定时触发，请在网址https://console.cron-job.org/dashboard 设置定时触发或自行改写工作流。

---
二、该程序需要添加环境变量（账号SWU_USERNAME，密码SWU_PASSWORD）。

---

使用方法：
## 📦 1. Fork 本仓库

点击右上角 **Fork**，将本仓库复制到你的 GitHub 账号下。

---

## 🔐 2. 添加账号密码（Secrets）

进入你 Fork 后的仓库 → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`，依次添加：

| Name | Value |
|------|-------|
| `SWU_USERNAME` | 你的学号 |
| `SWU_PASSWORD` | 你的密码 |

---

## 🗝️ 3. 生成 GitHub 令牌（仅一次）

1. 点击右上角头像 → `Settings` → 最下方 `Developer settings` → `Personal access tokens` → `Tokens (classic)`。
2. 点击 `Generate new token (classic)`：
   - **Note**：随便填（如 `cron-trigger`）
   - **Expiration**：选 `No expiration`
   - **Scopes**：只勾选 **`workflow`**
3. 生成后 **立即复制令牌**（只显示一次，保存好）。

---

## ⏰ 4. 在 cron-job.org 设置定时触发

1. 打开 [cron-job.org](https://cron-job.org) 注册免费账号并登录。
2. 点击 `Create cronjob`，按以下内容填写：

| 字段 | 填写内容 |
|------|----------|
| **URL** | `https://api.github.com/repos/你的用户名/你的仓库名/actions/workflows/swu-check.yml/dispatches` <br>（例：`https://api.github.com/repos/zhangsan/new-swu-checkin/actions/workflows/swu-check.yml/dispatches`） |
| **Request method** | `POST` |
| **Headers**（添加 3 条） | `Authorization: token 你复制的令牌` <br> `Accept: application/vnd.github.v3+json` <br> `Content-Type: application/json` |
| **Request body** | 选 `Custom`，填入：`{"ref":"main"}` <br>（若默认分支为 `master`，则改为 `{"ref":"master"}`） |
| **Schedule** | 选 `Cron expression`，填入：`30 13 * * *`（代表每天 UTC 13:30 = 北京时间 21:30） <br> 可再加一个备用：`30 14 * * *`（22:30） |

3. 点击 **Save**，然后点击 **Run now** 测试。
   - 若返回状态码 **204**，表示成功。
   - 等待 10 秒，刷新 GitHub Actions 页面，应看到新的运行记录。

---

## ✅ 5. 验证

点击 Actions 中的运行记录，查看日志。如果显示 `✅ 打卡成功` 或 `✅ 今日已签到`，则一切正常。

---

## ❓ 常见问题

| 现象 | 解决办法 |
|------|----------|
| cron-job 返回 `401` | 检查 `Authorization: token 你的令牌` 中 `token` 和令牌之间**有空格** |
| cron-job 返回 `404` | 确认 URL 中的用户名、仓库名、文件名（`swu-check.yml`）拼写正确 |
| Actions 运行失败 | 检查 Secrets 中的账号密码是否正确 |
| 验证码识别失败 | 脚本有重试机制，通常 3 次内成功 |

---

## 🔒 安全提示

- 请勿将令牌或密码写在代码中，所有敏感信息通过 Secrets 和 cron-job 的 Headers 传递。
- 本仓库公开时，Secrets 依然安全（只有你本人可见）。

---

免责声明：该方法只用于编程练习，请勿商业化，如有违规，自负后果。
