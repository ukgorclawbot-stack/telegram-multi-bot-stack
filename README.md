# Telegram Multi-Bot Stack

一个面向 Telegram 的多 bot 协作框架，支持：

- 群聊 bot 和私聊 bot 分离
- `OpenClaw / Gemini / Codex / Claude` 多角色协作
- 共享任务队列
- 共享记忆摘要
- 一键生成 env 和 launchd
- 可扩容到任意数量 bot

适合这些场景：
- 团队协作群里的任务拆分和汇报
- 私聊里的高权限开发与执行
- 多 bot 同时在线但职责明确分离

## 快速开始

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
bash ./install.sh
bash ./configure.sh
bash ./apply_stack.sh
```

更适合零基础的详细说明见：
- [INSTALL.md](./INSTALL.md)

如果你只想先看会生成什么，不真正启动服务：

```bash
git clone https://github.com/ukgorclawbot-stack/telegram-multi-bot-stack.git
cd telegram-multi-bot-stack
bash ./install.sh
bash ./configure.sh
bash ./bootstrap_bot_stack.sh generate
```

## 主要文件

- `group_bot.py`: 群聊 / 私聊通用入口
- `bot.py`: 兼容旧 Codex 直连入口
- `bootstrap_bot_stack.py`: 根据 TOML 清单生成 env 和 launchd
- `configure_stack.py`: 交互式配置向导
- `bootstrap_bot_stack.sh`: generate/apply/export-live/migration-template 包装器
- `apply_stack.sh`: 读取本地 token 后一键应用

## 常用命令

```bash
# 安装依赖
bash ./install.sh

# 交互式生成配置
bash ./configure.sh

# 只生成，不启动
bash ./bootstrap_bot_stack.sh generate

# 生成并启动
bash ./apply_stack.sh

# 一键健康检查
bash ./health_check.sh
```

## 高级能力

```bash
# 从当前线上正式配置反向导出
bash ./bootstrap_bot_stack.sh export-live

# 生成更适合新机器迁移的模板
bash ./bootstrap_bot_stack.sh migration-template
```

## 许可证

MIT
