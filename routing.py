#!/usr/bin/env python3
import re
from typing import Dict, List


EXPLICIT_AGENT_TAGS = {
    "#codex": ["codex"],
    "#claude": ["claude"],
    "#claudecode": ["claude"],
    "#gemini": ["gemini"],
}

DOC_KEYWORDS = [
    "翻译",
    "润色",
    "文档",
    "资料搜索",
    "搜资料",
    "搜集资料",
    "数据采集",
    "数据整理",
    "数据分析",
    "信息采集",
    "情报整理",
    "总结",
    "总结成文",
    "邮件",
    "报告",
    "ppt",
    "presentation",
    "translate",
    "polish",
    "rewrite",
    "document",
]

AUTOMATION_KEYWORDS = [
    "自动化",
    "定时",
    "准时",
    "监测",
    "监控",
    "实时",
    "异动",
    "告警",
    "抓取",
    "采集",
    "轮询",
    "同步",
    "推送",
    "scheduler",
    "cron",
]

CODE_KEYWORDS = [
    "代码",
    "编程",
    "开发",
    "修复",
    "bug",
    "debug",
    "安装",
    "配置",
    "review",
    "审核",
    "检查",
    "skill",
    "脚本",
    "部署",
    "测试",
]

EXECUTION_INTENT_KEYWORDS = [
    "运行",
    "执行",
    "调用",
    "读取",
    "基于",
    "用",
    "启动",
    "后台运行",
    "盯着",
    "跟踪",
]

EXISTING_ARTIFACT_KEYWORDS = [
    "现成脚本",
    "现有脚本",
    "已有脚本",
    "现成代码",
    "现有代码",
    "已有代码",
    "已经开发好的脚本",
    "已经编辑好可以直接运行的代码",
    "脚本输出",
    "脚本结果",
    "运行结果",
    "启动脚本",
    "监控脚本",
    "现有监控",
    "已有监控",
]

RUNTIME_MONITOR_KEYWORDS = [
    "帮我监控",
    "持续监控",
    "持续跟踪",
    "后台运行",
    "启动脚本",
    "启动监控",
    "盯着",
    "盯盘",
    "跟踪",
    "出现",
    "马上通知我",
]

EDITING_KEYWORDS = [
    "修改",
    "重写",
    "编写",
    "实现",
    "新建",
    "新增",
    "补齐",
    "接入",
    "修复",
    "优化",
    "部署",
    "配置",
    "开发一个",
    "开发新",
    "开发脚本",
    "写脚本",
    "改脚本",
    "写代码",
    "改代码",
]

DIGEST_QUERY_KEYWORDS = [
    "晨报",
    "日报",
    "早报",
    "币安异动",
    "github 热门",
    "x 情报",
    "市场情绪",
    "长版报告",
    "长板报告",
    "完整日报",
    "完整晨报",
]

STATUS_QUERY_KEYWORDS = [
    "正在跑的脚本",
    "在跑的脚本",
    "哪些脚本正在跑",
    "有哪些脚本正在跑",
    "运行中的脚本",
    "当前在跑的脚本",
    "现在在跑的脚本",
    "现在我们群正在跑的脚本",
]

TASK_HINT_KEYWORDS = [
    "修复",
    "开发",
    "实现",
    "安装",
    "配置",
    "部署",
    "编写",
    "创建",
    "新建",
    "修改",
    "检查",
    "审核",
    "测试",
    "翻译",
    "润色",
    "整理",
    "总结",
    "生成",
    "完成",
    "处理",
    "监控",
    "监测",
    "实时",
    "异动",
    "抓取",
    "采集",
    "汇报",
    "运行",
    "执行",
    "调用",
    "读取",
    "帮我",
]


def classify_task(text: str) -> Dict[str, object]:
    lowered = text.lower()

    for tag, agents in EXPLICIT_AGENT_TAGS.items():
        if tag in lowered:
            return {
                "category": "explicit",
                "allowed_agents": agents,
                "route_reason": f"matched explicit tag {tag}",
            }

    existing_artifact_hint = any(keyword in lowered for keyword in EXISTING_ARTIFACT_KEYWORDS) or bool(
        re.search(r"(现有|已有|现成).{0,8}(脚本|代码)", lowered)
    )
    runtime_monitor_request = any(keyword in lowered for keyword in RUNTIME_MONITOR_KEYWORDS)
    execution_only = existing_artifact_hint and any(keyword in lowered for keyword in EXECUTION_INTENT_KEYWORDS)
    editing_request = any(keyword in lowered for keyword in EDITING_KEYWORDS)
    if runtime_monitor_request and not editing_request:
        return {
            "category": "docs",
            "allowed_agents": ["gemini"],
            "route_reason": "matched runtime-monitoring execution keywords",
        }
    if execution_only and not editing_request:
        return {
            "category": "docs",
            "allowed_agents": ["gemini"],
            "route_reason": "matched existing-script/data-collection keywords",
        }

    if any(keyword in lowered for keyword in AUTOMATION_KEYWORDS):
        return {
            "category": "coding",
            "allowed_agents": ["codex", "claude"],
            "route_reason": "matched automation/monitoring keywords",
        }

    if any(keyword in lowered for keyword in DOC_KEYWORDS):
        return {
            "category": "docs",
            "allowed_agents": ["gemini"],
            "route_reason": "matched docs/translation/polish keywords",
        }

    if any(keyword in lowered for keyword in CODE_KEYWORDS):
        return {
            "category": "coding",
            "allowed_agents": ["codex", "claude"],
            "route_reason": "matched coding/setup/review keywords",
        }

    if re.search(r"\b(pdf|markdown|slides|proposal|copy)\b", lowered):
        return {
            "category": "docs",
            "allowed_agents": ["gemini"],
            "route_reason": "matched generic office-writing keywords",
        }

    return {
        "category": "coding",
        "allowed_agents": ["codex", "claude"],
        "route_reason": "defaulted to coding pair for ambiguous task",
    }


def classify_group_message_semantics(text: str) -> str:
    lowered = text.strip().lower()
    if not lowered:
        return "casual"

    if any(keyword in lowered for keyword in STATUS_QUERY_KEYWORDS):
        return "status"

    if any(tag in lowered for tag in EXPLICIT_AGENT_TAGS):
        return "task"

    if any(keyword in lowered for keyword in DIGEST_QUERY_KEYWORDS):
        if not any(keyword in lowered for keyword in EDITING_KEYWORDS):
            return "digest"

    route = classify_task(text)
    if str(route.get("route_reason", "")) != "defaulted to coding pair for ambiguous task":
        return "task"

    if any(keyword in lowered for keyword in TASK_HINT_KEYWORDS):
        return "task"

    return "casual"


def format_allowed_agents(agents: List[str]) -> str:
    return ", ".join(agents)
