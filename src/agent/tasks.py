"""
tasks.py —— 任务 / LLM / CMD 异步状态机
=========================================

自进化类任务流程：
  IDLE → 走向任务点 → ACCEPTED(领任务) → EXPLORING(沙盒探索)
  → ANSWERING(迭代求解) → SUBMIT(提交答案) → DONE(冷却30回合)

异步机制：
- 本回合在 response 中提交 prompt / executeCmd
- 结果在下一回合的 llmResp / lastCmdResult 中获取
- 每日 LLM 仅 3 次（白天首回合重置），自进化任务期间不限量
- 沙盒 executeCmd 单回合 15s 超时，结果格式 "[exitCode:N]\n<输出>"

开拓者白天调度：
- 若有进行中的任务，继续执行
- 否则寻找可接取的任务点前往
- 临近夜晚（白天最后 15 回合）必须撤回基地操塔
"""

from __future__ import annotations

import logging
from typing import Any

from .constants import LLM_CALLS_PER_DAY
from .grid import next_step
from .memory import NewsEvent, get_memory
from .protocol import (
    Pos, Turn, Unit, accept_task_command, distance, move_command,
    submit_answer_command,
)

LOGGER = logging.getLogger(__name__)

# 任务状态
STATE_IDLE = "idle"
STATE_MOVING = "moving"
STATE_ACCEPTED = "accepted"
STATE_EXPLORING = "exploring"
STATE_ANSWERING = "answering"
STATE_DONE = "done"


def pioneer_decide(
    turn: Turn, role: Unit, claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> None:
    """
    开拓者白天决策：执行自进化任务。
    直接将指令写入 commands[role.unit_id]。
    """
    mem = get_memory()
    state = mem.task_state.get("state", STATE_IDLE)

    # 若有进行中的任务，继续
    if state in (STATE_ACCEPTED, STATE_EXPLORING, STATE_ANSWERING):
        _continue_task(turn, role, commands)
        return

    # 否则寻找可接取的任务点
    target_task = _find_available_task(turn)
    if target_task is None:
        # 没有可做的任务，回基地附近待命
        _return_to_base(turn, role, claimed, commands)
        return

    task_pos = target_task.task_position
    if distance(role.pos, task_pos) <= 1:
        # 在任务点旁，领取任务
        commands[role.unit_id] = accept_task_command()
        mem.task_state["state"] = STATE_ACCEPTED
        mem.task_state["task_pos"] = (task_pos.x, task_pos.y)
        mem.task_state["exploration"] = ""
        return

    # 走向任务点
    step = _safe_step(turn, role, task_pos, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)
        mem.task_state["state"] = STATE_MOVING


def _find_available_task(turn: Turn):
    """找一个可接取的己方任务点。"""
    for task in turn.our_task_points():
        if task.is_valid and task.cold_down_rounds == 0:
            return task
    return None


def _continue_task(
    turn: Turn, role: Unit, commands: dict[int, dict[str, Any]],
) -> None:
    """
    继续执行已领取的任务。
    目前采用简化策略：如果有 lastCmdResult 则解析并提交答案，
    否则发送一个探索命令到沙盒。
    """
    mem = get_memory()
    state = mem.task_state.get("state", STATE_IDLE)

    # 读取上回合沙盒执行结果
    last_cmd = turn.last_cmd_result
    llm_resp = turn.llm_resp

    # 策略 1：如果有 LLM 响应，直接作为答案提交
    if llm_resp and state == STATE_ANSWERING:
        commands[role.unit_id] = submit_answer_command(llm_resp.strip())
        mem.task_state["state"] = STATE_DONE
        return

    # 策略 2：如果有沙盒输出，用 LLM 解析答案（消耗 1 次 LLM）
    if last_cmd and state == STATE_EXPLORING:
        day_no = turn.day_no()
        if mem.can_use_llm(day_no):
            mem.record_llm_call(day_no)
            # 将沙盒输出作为 prompt 发给 LLM，请求提取答案
            prompt = (
                f"任务原文：{turn.phase_task}\n"
                f"沙盒执行结果：{last_cmd}\n"
                f"请根据以上信息，直接给出任务答案，只输出答案内容。"
            )
            # 注意：prompt 是在 response 顶层返回的，不是 roleCommand
            # 这里需要通过 brain 的返回值传递，暂用全局标记
            mem.task_state["pending_prompt"] = prompt
            mem.task_state["state"] = STATE_ANSWERING
            return

    # 策略 3：发送沙盒探索命令
    if state == STATE_ACCEPTED:
        # 构造一个探索命令：先打印任务内容，再尝试基础探索
        cmd = _build_explore_cmd(turn.phase_task)
        if cmd:
            # executeCmd 通过 response 顶层返回，暂存
            mem.task_state["pending_cmd"] = cmd
            mem.task_state["state"] = STATE_EXPLORING
            return

    # 兜底：直接提交一个简单答案（避免任务超时全无收益）
    if turn.phase_task:
        commands[role.unit_id] = submit_answer_command("unknown")
        mem.task_state["state"] = STATE_DONE


def _build_explore_cmd(phase_task: str) -> str:
    """
    根据任务原文构造沙盒探索命令。
    自进化类任务通常涉及调用某个 API，这里先尝试常见模式。
    """
    if not phase_task:
        return ""
    # 先尝试列出沙盒环境，看看有什么可用资源
    # 注意：沙盒无外网，15s 超时
    return f'echo "TASK_START"; python3 -c "print(\'hello\')"; echo "TASK_END"'


def _return_to_base(
    turn: Turn, role: Unit, claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> None:
    """没有任务时回基地附近待命。"""
    station = turn.station()
    if station is None:
        return
    if distance(role.pos, station.pos) <= 2:
        return
    step = _safe_step(turn, role, station.pos, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)


def _safe_step(
    turn: Turn, role: Unit, goal: Pos, claimed: set[Pos],
) -> Pos | None:
    """安全走一步，避免碰撞。"""
    step = next_step(turn, role, goal)
    if step is None or step in claimed:
        return None
    claimed.add(step)
    return step


def get_pending_prompt() -> str:
    """获取待发送的 LLM prompt（由 brain 层读取并放入 response）。"""
    mem = get_memory()
    prompt = mem.task_state.get("pending_prompt", "")
    mem.task_state["pending_prompt"] = ""
    return prompt


def get_pending_cmd() -> str:
    """获取待执行的沙盒命令（由 brain 层读取并放入 response）。"""
    mem = get_memory()
    cmd = mem.task_state.get("pending_cmd", "")
    mem.task_state["pending_cmd"] = ""
    return cmd
