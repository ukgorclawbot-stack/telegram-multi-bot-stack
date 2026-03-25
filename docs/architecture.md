# Architecture

This document explains how the public Telegram Multi-Bot Stack is structured.

这份文档解释公开版 Telegram Multi-Bot Stack 的整体架构。

## 1. High-Level Idea / 总体思路

The stack separates:

- group bots for collaboration, routing, and reporting
- private bots for deeper execution and personal workflows
- shared layers for task queue, memory summaries, and reusable skills

这套系统把能力拆成三层：

- 群聊 bots：负责协作、分派、汇报
- 私聊 bots：负责深度执行和个人工作流
- 共享层：负责任务队列、记忆摘要和复用 skill

## 2. Default 6-Bot Layout / 默认 6 Bot 结构

| Bot | Scene | Main responsibility |
|---|---|---|
| `OpenClaw-Group` | Group | routing, task decomposition, status, shared memory write-back |
| `Gemini-Group` | Group | daily report, research summary, analysis, reporting |
| `Codex-Group` | Group | coding, scripts, debugging, technical execution |
| `OpenClaw-Private` | Private | personal control plane, private delegation |
| `Gemini-Private` | Private | high-permission autonomous execution |
| `Codex-Private` | Private | private coding execution |

## 3. Shared Layers / 共享层

### 3.1 Task Queue

Used for:

- delegated execution
- worker pickup
- final result handoff

用途：

- 跨 bot 任务委派
- worker 认领执行
- 最终结果回传

### 3.2 Memory Summaries

The stack does not rely only on raw chat history.

Instead, it keeps short summaries so bots can:

- recall recent context faster
- share important outcomes without copying full conversations
- reduce group/private cross-contamination

这套系统不是只靠原始聊天历史。

它会保留简短摘要，帮助 bot：

- 更快召回最近上下文
- 共享关键结论而不是整段聊天
- 降低群聊和私聊上下文串线

### 3.3 Shared Skills

Skills are designed to be shared across bots.

That means:

- new skills can be installed once
- multiple bots can reuse the same capability
- the stack stays extensible without hardcoding everything into bot logic

skill 设计成可共享：

- 新 skill 装一次即可
- 多个 bot 可以复用
- 扩展能力不需要都写死进 bot 逻辑

## 4. Message Routing / 消息路由

### Group Chat

Typical pattern:

1. `OpenClaw-Group` receives an unassigned task-like message
2. it decomposes the task
3. it routes to `Gemini-Group` or `Codex-Group`
4. final result is written back into shared memory

群聊典型链路：

1. `OpenClaw-Group` 接住未点名的任务型消息
2. 它先拆分任务
3. 再分派给 `Gemini-Group` 或 `Codex-Group`
4. 最终结果写回共享记忆

### Private Chat

Typical pattern:

- private bots handle deeper direct requests
- private execution can use broader local permissions
- group-facing behavior stays more stable and lower-risk

私聊典型链路：

- 私聊 bot 直接接住深度请求
- 私聊执行可以拥有更高的本机权限
- 群聊侧保持更稳、更低风险

## 5. Permission Model / 权限模型

The default stack usually uses:

- more constrained workdirs for some group bots
- broader home-directory workdirs for private bots

默认情况下通常是：

- 群聊部分 bot 使用更收敛的工作目录
- 私聊 bot 使用更宽的 home 目录工作范围

Why:

- group bots should be safer and more predictable
- private bots are expected to do deeper personal work

原因：

- 群聊 bot 更强调安全和稳定
- 私聊 bot 更强调深度执行能力

## 6. Config Model / 配置模型

The stack is generated from a TOML spec.

Important pieces:

- `bot_stack.bootstrap.toml`
- generated env files
- generated launchd plist files

这套系统通过 TOML 清单生成配置。

关键文件：

- `bot_stack.bootstrap.toml`
- 生成出来的 env 文件
- 生成出来的 launchd plist 文件

## 7. Migration and Rebuild / 迁移与重建

The project supports:

- reverse export from a live stack
- migration-ready templates for a fresh machine

支持：

- 从线上运行中的配置反向导出
- 为新机器生成可落地的迁移模板

This makes it easier to:

- move to another Mac
- clone the setup safely
- document a running deployment

这样更方便：

- 迁移到另一台 Mac
- 安全复制一套环境
- 文档化当前运行架构

## 8. Recommended Reading Order / 建议阅读顺序

If you are new, read in this order:

1. `README.md` or `README.en.md`
2. `INSTALL.md` or `INSTALL.en.md`
3. `docs/faq.md`
4. this file
5. `CONTRIBUTING.md` and `SECURITY.md` if you plan to contribute
