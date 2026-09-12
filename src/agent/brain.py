"""
brain.py —— 决策中枢
=====================

职责：
- 每回合入口 decide(payload) -> (commands, prompt, executeCmd)
- 按昼夜分发：
  * 白天：工人走 economy 状态机（采矿/贩卖/采购/建造/升级）；
          开拓者做任务或准备夜战
  * 夜晚：3 角色各分配 1 座塔，站到操塔位后开火控
- 操塔配对：worker1→tower1, pioneer→tower2, worker2→tower3
- 残血角色使用生命药剂
"""

from __future__ import annotations

import logging
from typing import Any

from .build_layout import stand_cells_for_tower
from .combat import choose_targets
from .constants import MEDICINE, PIONEER_HP, WORKER_HP
from .economy import worker_decide
from .grid import next_step
from .memory import get_memory
from .protocol import (
    Pos, Turn, Unit, attack_command, distance, move_command, use_command,
)
from .tasks import get_pending_cmd, get_pending_prompt, pioneer_decide

LOGGER = logging.getLogger(__name__)


def decide(payload: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], str, str]:
    """
    决策入口。
    返回 (指令集, prompt, executeCmd)。
    """
    turn = Turn.load(payload)
    commands: dict[int, dict[str, Any]] = {}

    # 每天首个回合解析官方新闻，更新矿种停产/涨价时间表
    mem = get_memory()
    day_no = turn.day_no()
    if mem.last_round_no != turn.round_no:
        phase = (turn.round_no - 1) % 130
        if phase == 0:
            mem.parse_official_news(turn.world_news.official_news, day_no)
        mem.last_round_no = turn.round_no

    if turn.is_day:
        _day(turn, commands)
    else:
        _night(turn, commands)

    # 从任务模块取出待发送的 LLM prompt 和沙盒命令
    prompt = get_pending_prompt()
    execute_cmd = get_pending_cmd()

    return commands, prompt, execute_cmd


# ============================================================================
# 白天
# ============================================================================

def _day(turn: Turn, commands: dict[int, dict[str, Any]]) -> None:
    """白天决策：工人经济循环 + 开拓者任务/备战。"""
    claimed: set[Pos] = set()

    # 工人：走经济状态机
    for role in turn.workers():
        if role.unit_id in commands:
            continue
        worker_decide(turn, role, claimed, commands)

    # 开拓者：任务优先，临近夜晚则回基地操塔
    pioneer = turn.pioneer()
    if pioneer is not None and pioneer.unit_id not in commands:
        # 白天最后 15 回合开始撤退回基地准备夜战
        day_phase = (turn.round_no - 1) % 130
        if day_phase >= 55:
            _move_to_night_post(turn, pioneer, claimed, commands)
        else:
            pioneer_decide(turn, pioneer, claimed, commands)


def _move_to_night_post(
    turn: Turn, role: Unit, claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> None:
    """让角色移动到夜晚操塔位。"""
    tower = _assigned_tower(turn, role)
    if tower is None:
        return
    if distance(role.pos, tower.pos) <= 1:
        return
    step = _safe_step(turn, role, tower.pos, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)


# ============================================================================
# 夜晚
# ============================================================================

def _night(turn: Turn, commands: dict[int, dict[str, Any]]) -> None:
    """夜晚决策：各角色到分配的塔旁操塔开火。"""
    claimed: set[Pos] = set()

    for role in turn.controllable():
        if role.unit_id in commands:
            continue
        tower = _assigned_tower(turn, role)
        if tower is None:
            continue

        # 残血用药：HP 低于 50% 时使用生命药剂
        max_hp = PIONEER_HP if role.kind == "pioneer" else WORKER_HP
        if role.health < max_hp // 2 and role.has_item(MEDICINE):
            commands[role.unit_id] = use_command(MEDICINE)
            continue

        # 已在塔旁：开火
        if distance(role.pos, tower.pos) <= 1:
            if tower.cooldown > 0:
                continue
            targets = choose_targets(turn, tower)
            if targets is not None:
                commands[tower.unit_id] = attack_command(role.unit_id, targets)
            continue

        # 走向塔的操塔位
        step = _step_to_tower(turn, role, tower, claimed)
        if step is not None:
            commands[role.unit_id] = move_command(step)


def _assigned_tower(turn: Turn, role: Unit) -> Unit | None:
    """
    为角色分配固定的塔。
    配对规则：controllable 按 ID 排序，weapons 按坐标排序，一一对应。
    worker1(最小ID) → tower1, pioneer → tower2, worker2 → tower3
    """
    roles = turn.controllable()
    towers = turn.weapons()
    if not towers:
        return None
    try:
        idx = roles.index(role)
    except ValueError:
        return None
    if idx < len(towers):
        return towers[idx]
    # 角色多于塔时，循环分配
    return towers[idx % len(towers)]


def _step_to_tower(
    turn: Turn, role: Unit, tower: Unit, claimed: set[Pos],
) -> Pos | None:
    """走向塔的某个安全操塔位。"""
    for stand in stand_cells_for_tower(turn, tower):
        if stand in claimed:
            continue
        if stand == role.pos:
            return None
        step = next_step(turn, role, stand)
        if step is not None and step not in claimed:
            claimed.add(step)
            return step
    return None


def _safe_step(
    turn: Turn, role: Unit, goal: Pos, claimed: set[Pos],
) -> Pos | None:
    """安全走一步，避免碰撞。"""
    step = next_step(turn, role, goal)
    if step is None or step in claimed:
        return None
    claimed.add(step)
    return step
