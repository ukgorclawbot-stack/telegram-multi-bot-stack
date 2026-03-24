# 安装说明

这份说明是给第一次接触这套框架的人准备的。

## 1. 你需要准备什么

在开始之前，请先准备：

1. 一台 macOS 电脑
2. 已安装 `Python 3`
3. 已安装 `Git`
4. 已安装 `Telegram`
5. 你准备创建的 Telegram bot token

如果你不确定电脑有没有装好 `Python 3` 和 `Git`，先在终端执行：

```bash
python3 --version
git --version
```

如果其中任意一条报错，先安装对应软件，再继续下面步骤。

## 2. 如何创建 Telegram bot

在 Telegram 里搜索 `@BotFather`，然后按下面步骤做：

1. 发送 `/newbot`
2. 给 bot 起名字
3. 给 bot 设置用户名（必须以 `bot` 结尾）
4. 保存返回的 token

如果你要用推荐的 6 bot 结构，就需要准备 6 个 token。

## 3. 下载项目

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
```

## 4. 一键安装依赖

```bash
bash ./install.sh
```

这个脚本会自动：

- 创建 `.venv`
- 安装 Python 依赖
- 初始化本地目录
- 准备配置模板

## 5. 一键生成配置

```bash
bash ./configure.sh
```

配置向导会问你：

- 你的 home 目录
- 哪个 Telegram user_id 可以使用这些 bot
- 是否使用推荐的 6 bot 结构

如果你不知道自己的 `user_id`，可以先用任意临时 bot 或现有 bot 的 `/whoami` 来查。

## 6. 写入 token

如果你在配置向导里没有直接输入 token，就手动编辑：

```bash
open .bot_tokens.env
```

把每个 bot 的 token 填进去。首次安装后这个文件会自动生成。

如果你只想先搭最推荐的 6 bot 结构，通常只需要填这 6 行：

```bash
TG_OPENCLAW_GROUP_TOKEN=
TG_GEMINI_GROUP_TOKEN=
TG_CODEX_GROUP_TOKEN=
TG_OPENCLAW_PRIVATE_TOKEN=
TG_GEMINI_PRIVATE_TOKEN=
TG_CODEX_PRIVATE_TOKEN=
```

## 7. 启动

```bash
bash ./apply_stack.sh
```

这一步会：

- 读取 `.bot_tokens.env`
- 生成正式 env
- 生成正式 launchd plist
- 自动加载并启动服务

## 8. 只想先试运行

如果你还不想真正启动，只想先看会生成什么：

```bash
bash ./bootstrap_bot_stack.sh generate
```

生成后的文件在：

- `generated/bot-stack/env/`
- `generated/bot-stack/launchd/`
- `generated/bot-stack/STACK_SUMMARY.md`

## 9. 安装完成后怎么检查是否成功

直接执行：

```bash
bash ./health_check.sh
```

如果安装成功，你会看到：
- Telegram API 检查结果
- bot 服务状态
- 监控和晨报状态

## 10. 推荐给零基础用户的完整顺序

按这个顺序照做最稳：

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
bash ./install.sh
bash ./configure.sh
open .bot_tokens.env
bash ./apply_stack.sh
bash ./health_check.sh
```

## 11. 常见问题

### 11.1 提示没找到 Python

先安装 Python 3，再重试：

```bash
python3 --version
```

### 11.2 提示 token 没提供

说明 `.bot_tokens.env` 还没写完整。

### 11.3 机器人没响应

先检查 launchd 是否在线：

```bash
launchctl list | grep telegram
```

再看日志：

```bash
tail -n 100 generated/bot-stack/logs/*.log
```
