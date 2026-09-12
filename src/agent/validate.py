"""
validate.py —— 指令合法性校验层
================================

职责：
在 brain 生成所有指令后、发回判题器前，逐条校验每条指令的合法性。
非法指令直接剔除，保证输出 100% 合法（避免累计 5 次异常被停赛）。

校验维度（接口文档 2.2 + 任务书 4.4）：
1. 动作码是否在合法集合内
2. 昼夜限制（attack 仅黑夜；build/collect 仅白天）
3. 角色类型限制（build/collect/remove 仅工人；acceptTask/submitAnswer/summonTreasure 仅开拓者）
4. 相邻 1 格校验（移动/建造/拆除/采集/使用升级券/召唤宝藏/领任务）
5. targetPos 永远是数组，长度符合要求
6. 加特林/火箭目标数 = 武器等级；加特林 90° 锥角约束
7. 火箭 cooldown > 0 禁射
8. 金币/背包容量/物品存在性（sell/buy/use/drop）
9. attack 的 controllerId 角色必须站在武器相邻格
"""

from __future__ import annotations

import logging
from typing import Any

from .constants import (
    ACT_ATTACK, ACT_BUILD, ACT_BUY, ACT_COLLECT, ACT_DROP,
    ACT_REMOVE, ACT_SELL, ACT_SUBMIT_ANSWER, ACT_SUMMON_TREASURE,
    ACT_USE, ALL_ACTIONS, DAY_ONLY_ACTIONS, GATLING, NIGHT_ONLY_ACTIONS,
    PIONEER, RAILGUN, ROCKET, SHOP_PRICES, WORKER,
)
from .protocol import Pos, Turn, Unit, distance

LOGGER = logging.getLogger(__name__)


def sanitize(turn: Turn, commands: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """
    对所有指令做合法性校验，返回剔除非法指令后的干净指令集。
    每个角色 ID 最多保留 1 条指令。
    """
    clean: dict[int, dict[str, Any]] = {}
    for role_id, cmd in commands.items():
        if not isinstance(cmd, dict):
            continue
        if validate_command(turn, role_id, cmd):
            clean[role_id] = cmd
        else:
            LOGGER.warning(
                "round %s: dropping illegal command role=%s cmd=%s",
                turn.round_no, role_id, cmd,
            )
    return clean


def validate_command(turn: Turn, role_id: int, cmd: dict[str, Any]) -> bool:
    """单条指令合法性校验，返回 True 表示合法。"""
    action = cmd.get("action")
    if action not in ALL_ACTIONS:
        return False

    # 昼夜限制
    if turn.is_day and action in NIGHT_ONLY_ACTIONS:
        return False
    if not turn.is_day and action in DAY_ONLY_ACTIONS:
        return False

    # 查找执行角色
    role = _find_unit(turn, role_id)
    if role is None:
        # 指令 key 是塔 ID 时（attack），执行角色是 controllerId
        if action == ACT_ATTACK:
            controller_id = cmd.get("controllerId")
            if controller_id is None:
                return False
            role = _find_unit(turn, int(controller_id))
            if role is None:
                return False
            tower = _find_unit(turn, role_id)
            if tower is None:
                return False
            return _validate_attack(turn, role, tower, cmd)
        return False

    # 角色类型限制
    if action in (ACT_BUILD, ACT_COLLECT, ACT_REMOVE) and role.kind != WORKER:
        return False
    if action in (ACT_SUBMIT_ANSWER, ACT_SUMMON_TREASURE) and role.kind != PIONEER:
        return False

    # 按动作分发校验
    if action == "move":
        return _validate_move(turn, role, cmd)
    if action == ACT_BUILD:
        return _validate_build(turn, role, cmd)
    if action == ACT_COLLECT:
        return _validate_collect(turn, role, cmd)
    if action == ACT_SELL:
        return _validate_sell(turn, role, cmd)
    if action == ACT_BUY:
        return _validate_buy(turn, role, cmd)
    if action == ACT_USE:
        return _validate_use(turn, role, cmd)
    if action == ACT_DROP:
        return _validate_drop(turn, role, cmd)
    if action == ACT_REMOVE:
        return _validate_remove(turn, role, cmd)
    if action == "acceptTask":
        return _validate_accept_task(turn, role)
    if action == ACT_SUBMIT_ANSWER:
        return True  # 内容合法性由判题器判定
    if action == ACT_SUMMON_TREASURE:
        return _validate_summon_treasure(turn, role, cmd)

    return True


# ---------------------------------------------------------------------------
# 辅助：查找单位
# ---------------------------------------------------------------------------

def _find_unit(turn: Turn, unit_id: int) -> Unit | None:
    """按 ID 查找己方单位。"""
    for unit in turn.ours:
        if unit.unit_id == unit_id:
            return unit
    return None


def _parse_target_pos(cmd: dict[str, Any]) -> Pos | None:
    """从指令中提取单个 targetPos。"""
    targets = cmd.get("targetPos")
    if not isinstance(targets, list) or not targets:
        return None
    raw = targets[0]
    if not isinstance(raw, dict):
        return None
    try:
        return Pos(int(raw["x"]), int(raw["y"]))
    except (KeyError, ValueError, TypeError):
        return None


def _parse_targets(cmd: dict[str, Any]) -> list[Pos]:
    """从指令中提取 targetPos 数组。"""
    targets = cmd.get("targetPos")
    if not isinstance(targets, list):
        return []
    result: list[Pos] = []
    for raw in targets:
        if not isinstance(raw, dict):
            continue
        try:
            result.append(Pos(int(raw["x"]), int(raw["y"])))
        except (KeyError, ValueError, TypeError):
            continue
    return result


# ---------------------------------------------------------------------------
# 各动作校验
# ---------------------------------------------------------------------------

def _validate_move(turn: Turn, role: Unit, cmd: dict[str, Any]) -> bool:
    """移动校验：目标在相邻 8 格内。"""
    target = _parse_target_pos(cmd)
    if target is None:
        return False
    return distance(role.pos, target) <= 1


def _validate_build(turn: Turn, role: Unit, cmd: dict[str, Any]) -> bool:
    """建造校验：工人白天、目标相邻 1 格、名称合法、金币/材料足够。"""
    target = _parse_target_pos(cmd)
    if target is None:
        return False
    if distance(role.pos, target) > 1:
        return False
    name = cmd.get("name")
    if name not in ("gatling", "railgun", "rocket", "wall"):
        return False
    # 围墙需要石头
    if name == "wall":
        if role.count_item("stone") < 1:
            return False
    else:
        # 武器需要金币
        if turn.gold < 25:
            return False
    return True


def _validate_collect(turn: Turn, role: Unit, cmd: dict[str, Any]) -> bool:
    """采集校验：工人白天、目标是矿且相邻 1 格。"""
    target = _parse_target_pos(cmd)
    if target is None:
        return False
    if distance(role.pos, target) > 1:
        return False
    kind = turn.zones.get(target)
    return kind in ("stone", "iron", "copper")


def _validate_sell(turn: Turn, role: Unit, cmd: dict[str, Any]) -> bool:
    """贩卖校验：在小贩相邻格、物品在背包、数量合法。"""
    vendor = turn.vendor_pos()
    if vendor is None or distance(role.pos, vendor) > 1:
        return False
    name = cmd.get("name")
    if name not in ("stone", "iron", "copper"):
        return False
    num = int(cmd.get("num") or 1)
    if num < 1 or role.count_item(name) < num:
        return False
    return True


def _validate_buy(turn: Turn, role: Unit, cmd: dict[str, Any]) -> bool:
    """购买校验：在商店相邻格、商品存在、金币足够、背包容量够。"""
    shop = turn.weapon_shop_pos()
    if shop is None or distance(role.pos, shop) > 1:
        return False
    name = cmd.get("name")
    if name not in SHOP_PRICES:
        return False
    num = int(cmd.get("num") or 1)
    if num < 1:
        return False
    total_cost = SHOP_PRICES[name] * num
    if turn.gold < total_cost:
        return False
    # 背包容量
    if role.capacity is not None:
        current = len(role.backpack)
        if current + num > role.capacity:
            return False
    return True


def _validate_use(turn: Turn, role: Unit, cmd: dict[str, Any]) -> bool:
    """使用校验：物品在背包；升级券需目标建筑相邻格。"""
    name = cmd.get("name")
    if not name or not role.has_item(name):
        return False
    # 需要 targetPos 的物品：升级券、围墙修复包、眩晕法宝、范围炸弹
    needs_target = name in (
        "WeaponUpgradeVoucher1", "WeaponUpgradeVoucher2",
        "WallUpgradeVoucher1", "WallUpgradeVoucher2",
        "StationUpgradeVoucher1", "StationUpgradeVoucher2",
        "WallFixer", "DizzyWeapon", "Bomb",
    )
    if needs_target:
        target = _parse_target_pos(cmd)
        if target is None:
            return False
        # 升级券和修复包需要在目标相邻格
        if name != "DizzyWeapon" and name != "Bomb":
            if distance(role.pos, target) > 1:
                return False
    return True


def _validate_drop(turn: Turn, role: Unit, cmd: dict[str, Any]) -> bool:
    """丢弃校验：物品在背包。"""
    name = cmd.get("name")
    return bool(name) and role.has_item(name)


def _validate_remove(turn: Turn, role: Unit, cmd: dict[str, Any]) -> bool:
    """拆除校验：工人、目标是围墙且相邻 1 格。"""
    target = _parse_target_pos(cmd)
    if target is None:
        return False
    if distance(role.pos, target) > 1:
        return False
    for wall in turn.walls():
        if wall.pos == target:
            return True
    return False


def _validate_accept_task(turn: Turn, role: Unit) -> bool:
    """领任务校验：开拓者在己方任务点相邻格。"""
    if role.kind != PIONEER:
        return False
    for task in turn.our_task_points():
        if distance(role.pos, task.task_position) <= 1 and task.is_valid:
            return True
    return False


def _validate_summon_treasure(turn: Turn, role: Unit, cmd: dict[str, Any]) -> bool:
    """召唤宝藏校验：开拓者、目标相邻格、物品都在背包。"""
    if role.kind != PIONEER:
        return False
    target = _parse_target_pos(cmd)
    if target is None or distance(role.pos, target) > 1:
        return False
    items = cmd.get("item")
    if not isinstance(items, list) or not items:
        return False
    for item in items:
        if not role.has_item(str(item)):
            return False
    return True


def _validate_attack(turn: Turn, controller: Unit, tower: Unit, cmd: dict[str, Any]) -> bool:
    """
    攻击校验（key=塔ID，controllerId=操控角色）：
    - 仅黑夜
    - 操控角色站在塔相邻格
    - 塔无冷却（火箭 cooldown>0 禁射）
    - 目标数 = 塔等级（加特林/火箭）；电磁 1 个
    - 加特林 90° 锥角约束
    - 目标在射程内
    """
    # 昼夜限制已在外层 NIGHT_ONLY_ACTIONS 校验过，此处不再重复
    if distance(controller.pos, tower.pos) > 1:
        return False
    if tower.cooldown > 0:
        return False

    targets = _parse_targets(cmd)
    if not targets:
        return False

    level = max(tower.level, 1)
    reach = tower.range_of_attack()

    # 目标数校验
    if tower.kind == RAILGUN:
        if len(targets) != 1:
            return False
    else:
        # 加特林 / 火箭：目标数 = 等级
        if len(targets) != level:
            return False

    # 射程校验
    for t in targets:
        if distance(tower.pos, t) > reach:
            return False

    # 加特林 90° 锥角校验
    if tower.kind == GATLING and len(targets) > 1:
        if not _check_gatling_cone(tower.pos, targets):
            return False

    return True


def _check_gatling_cone(tower_pos: Pos, targets: list[Pos]) -> bool:
    """
    加特林多目标须落在同一 90° 锥形内：
    任意两个目标相对塔的方向夹角 ≤ 90°。
    用向量点积判断：夹角 ≤ 90° 当且仅当点积 ≥ 0。
    """
    if len(targets) <= 1:
        return True
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            dx1 = targets[i].x - tower_pos.x
            dy1 = targets[i].y - tower_pos.y
            dx2 = targets[j].x - tower_pos.x
            dy2 = targets[j].y - tower_pos.y
            # 点积 < 0 表示夹角 > 90°
            if dx1 * dx2 + dy1 * dy2 < 0:
                return False
    return True
