#!/usr/bin/env python3
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from routing import classify_task

@dataclass
class RunnerConfig:
    backend: str
    workdir: str
    timeout_secs: int = 600
    codex_bin: str = "codex"
    codex_model: str = ""
    codex_reasoning_effort: str = ""
    codex_sandbox: str = "workspace-write"
    claude_bin: str = "claude"
    claude_model: str = ""
    claude_permission_mode: str = "acceptEdits"
    gemini_bin: str = "gemini"
    gemini_model: str = ""
    gemini_approval_mode: str = "auto_edit"
    openclaw_bin: str = "openclaw"
    openclaw_agent_id: str = ""
    openclaw_router_coding_agent: str = "codex"
    openclaw_router_docs_agent: str = "gemini"
    openclaw_router_default_agent: str = "codex"


def run_task(prompt: str, config: RunnerConfig) -> str:
    if config.backend == "codex_cli":
        return run_codex(prompt, config)
    if config.backend == "claude_cli":
        return run_claude(prompt, config)
    if config.backend == "gemini_cli":
        return run_gemini(prompt, config)
    if config.backend == "openclaw_agent":
        return run_openclaw_agent(prompt, config)
    if config.backend == "openclaw_router":
        return run_openclaw_router(prompt, config)
    raise RuntimeError(f"Unsupported backend: {config.backend}")


def _resolve_bin(path_or_name: str) -> str:
    if Path(path_or_name).is_absolute():
        return path_or_name
    resolved = shutil.which(path_or_name)
    if not resolved:
        raise RuntimeError(f"Executable not found: {path_or_name}")
    return resolved


def run_codex(prompt: str, config: RunnerConfig) -> str:
    output_file = tempfile.NamedTemporaryFile(prefix="group-codex-", suffix=".txt", delete=False)
    output_path = output_file.name
    output_file.close()
    command = [
        _resolve_bin(config.codex_bin),
        "exec",
        "--skip-git-repo-check",
        "--ephemeral",
        "--disable",
        "memories",
        "-C",
        config.workdir,
        "-s",
        config.codex_sandbox,
        "-o",
        output_path,
    ]
    if config.codex_model:
        command.extend(["-m", config.codex_model])
    if config.codex_reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{config.codex_reasoning_effort}"'])
    command.append(prompt)
    try:
        result = subprocess.run(
            command,
            cwd=config.workdir,
            capture_output=True,
            text=True,
            timeout=config.timeout_secs,
            check=False,
        )
        output_text = Path(output_path).read_text(encoding="utf-8").strip()
    finally:
        Path(output_path).unlink(missing_ok=True)
    return _finalize_result(result, output_text)


def run_claude(prompt: str, config: RunnerConfig) -> str:
    command = [_resolve_bin(config.claude_bin), "-p", prompt, "--permission-mode", config.claude_permission_mode]
    if config.claude_model:
        command.extend(["--model", config.claude_model])
    result = subprocess.run(
        command,
        cwd=config.workdir,
        capture_output=True,
        text=True,
        timeout=config.timeout_secs,
        check=False,
    )
    return _finalize_result(result, (result.stdout or "").strip())


def run_gemini(prompt: str, config: RunnerConfig) -> str:
    command = [
        _resolve_bin(config.gemini_bin),
        "-p",
        prompt,
        "--output-format",
        "text",
        "--approval-mode",
        config.gemini_approval_mode,
    ]
    if config.gemini_model:
        command.extend(["--model", config.gemini_model])
    result = subprocess.run(
        command,
        cwd=config.workdir,
        capture_output=True,
        text=True,
        timeout=config.timeout_secs,
        check=False,
    )
    return _finalize_result(result, (result.stdout or "").strip())


def run_openclaw_agent(prompt: str, config: RunnerConfig) -> str:
    if not config.openclaw_agent_id:
        raise RuntimeError("openclaw_agent backend requires openclaw_agent_id")
    command = [
        _resolve_bin(config.openclaw_bin),
        "agent",
        "--agent",
        config.openclaw_agent_id,
        "--message",
        prompt,
        "--json",
    ]
    result = subprocess.run(
        command,
        cwd=config.workdir,
        capture_output=True,
        text=True,
        timeout=config.timeout_secs,
        check=False,
    )
    stdout = (result.stdout or "").strip()
    if result.returncode != 0:
        return _finalize_result(result, stdout)
    json_start = stdout.find("{")
    if json_start < 0:
        return _finalize_result(result, stdout)
    payload = json.loads(stdout[json_start:])
    messages = payload.get("result", {}).get("payloads", [])
    text = "\n".join(item.get("text", "").strip() for item in messages if item.get("text"))
    return text or "OpenClaw agent returned no text."


def run_openclaw_router(prompt: str, config: RunnerConfig) -> str:
    route = classify_task(prompt)
    category = route["category"]
    allowed = list(route["allowed_agents"])
    if category == "docs":
        selected_agent = config.openclaw_router_docs_agent
    elif category == "coding":
        selected_agent = config.openclaw_router_coding_agent
    elif allowed:
        selected_agent = allowed[0]
    else:
        selected_agent = config.openclaw_router_default_agent
    routed = replace(config, backend="openclaw_agent", openclaw_agent_id=selected_agent)
    return run_openclaw_agent(prompt, routed)


def _finalize_result(result: subprocess.CompletedProcess, output_text: str) -> str:
    if result.returncode == 0 and output_text:
        return output_text
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    error_text = stderr or stdout or output_text or "Unknown error"
    return f"Runner failed: {error_text[:2000]}"
