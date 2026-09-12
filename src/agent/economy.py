"""
economy.py —— 工人经济状态机
==============================

工人白天状态流转：
  采矿(MINE) → 凑批量 → 去小贩贩卖(SELL) → 经商店采购(BUY) → 回建造区建墙/塔/升级

策略要点：
- 矿种优先级：常规 copper(5) > iron(3) > stone(1)；新闻涨价时切换
- 每个矿采集 10 次后枯竭，自动从最新 zones 重选
- 残量矿尝试两工人同回合采集（"各得1个"规则红利）
- 升级优先级：火箭塔 > 电磁塔 > 基地 > 围墙
- 围墙材料只耗石头，工人需先采石头再建墙
"""

from __future__ import annotations

import logging
from typing import Any

from .build_layout import TOWER_LOADOUT, tower_sites, wall_sites
from .constants import BASE_ORE_PRICES, WEAPON_BUILD_COST
from .grid import next_step
from .memory import get_memory
from .protocol import (
    Pos, Turn, Unit, build_command, buy_command, collect_command,
    distance, move_command, sell_command, use_command,
)

LOGGER = logging.getLogger(__name__)

# 凑批量贩卖阈值：背包矿石数达到该值才去卖，减少往返
SELL_BATCH = 5
# 采矿背包阈值：达到该数量后停止采矿去卖
MINE_BATCH = 8

# 矿石中文名 -> zones 中的 neutralType
ORE_TYPES = ("stone", "iron", "copper")
WALL_MATERIAL_NAME = "stone"


def mine_priority(turn: Turn) -> tuple[str, ...]:
    """
    返回当前矿种优先级（从高到低）。
    常规：copper > iron > stone
    新闻影响：停工的矿种排最后，涨价的矿种提前
    """
    day_no = turn.day_no()
    mem = get_memory()

    def score(ore: str) -> tuple:
        # 可采集 + 价格高 = 优先
        minable = mem.ore_minable(ore, day_no)
        price = BASE_ORE_PRICES[ore] * mem.ore_price_multiplier(ore, day_no)
        return (0 if minable else 1, -price)  # 可采优先，价格高优先

    return tuple(sorted(ORE_TYPES, key=score))


def all_mines(turn: Turn, ore: str) -> tuple[Pos, ...]:
    """获取指定矿种的所有矿点坐标。"""
    if ore == "stone":
        return turn.stone_mines()
    if ore == "iron":
        return turn.iron_mines()
    if ore == "copper":
        return turn.copper_mines()
    return ()


def worker_decide(
    turn: Turn,
    role: Unit,
    claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> None:
    """
    单个工人的白天决策。
    直接将指令写入 commands[role.unit_id]。
    """
    mem = get_memory()

    # 同步矿点状态（检测矿消失/刷新）
    all_mine_positions = set()
    for ore in ORE_TYPES:
        all_mine_positions.update(all_mines(turn, ore))
    mem.sync_mines(all_mine_positions)

    # ---- 优先级 1：建造缺失的塔 ----
    standing_towers = {u.pos for u in turn.weapons()}
    sites = tower_sites(turn)
    for idx, site in enumerate(sites):
        if site not in standing_towers and site not in claimed:
            if turn.gold >= WEAPON_BUILD_COST:
                _build_or_walk(turn, role, site, TOWER_LOADOUT[idx], claimed, commands)
                return

    # ---- 优先级 2：使用升级券（如果背包里有且站在目标旁）----
    if _try_use_upgrade(turn, role, commands):
        return

    # ---- 优先级 3：建造缺失的墙（有石头时）----
    standing_walls = {u.pos for u in turn.walls()}
    wall_positions = wall_sites(turn)
    stones = role.count_item(WALL_MATERIAL_NAME)
    if stones > 0:
        for wpos in wall_positions:
            if wpos not in standing_walls and wpos not in claimed:
                _build_or_walk(turn, role, wpos, "wall", claimed, commands)
                return

    # ---- 优先级 4：贩卖矿石（背包有矿石且达到批量）----
    ores_in_bag = {ore: role.count_item(ore) for ore in ORE_TYPES}
    total_ores = sum(ores_in_bag.values())
    if total_ores >= SELL_BATCH or role.backpack_full:
        if _try_sell(turn, role, ores_in_bag, commands):
            return

    # ---- 优先级 5：购买升级券（金币足够且已在商店旁）----
    shop = turn.weapon_shop_pos()
    if shop is not None and distance(role.pos, shop) <= 1:
        if _try_buy(turn, role, commands):
            return

    # ---- 优先级 6：采矿 ----
    if not role.backpack_full and total_ores < MINE_BATCH:
        if _try_mine(turn, role, claimed, commands):
            return

    # ---- 兜底：向基地移动 ----
    station = turn.station()
    if station is not None:
        step = _safe_step(turn, role, station.pos, claimed)
        if step is not None:
            commands[role.unit_id] = move_command(step)


def _try_mine(
    turn: Turn, role: Unit, claimed: set[Pos],
    commands: dict[int, dict[str, Any]],
) -> bool:
    """尝试采集：已在矿旁则采集，否则走向最近的优先矿种。"""
    priority = mine_priority(turn)
    mem = get_memory()

    # 先检查是否已在某个矿旁边
    for ore in priority:
        for mine in all_mines(turn, ore):
            if role.pos != mine and distance(role.pos, mine) <= 1:
                if mine not in claimed and mem.mine_remaining(mine) > 0:
                    commands[role.unit_id] = collect_command(mine)
                    claimed.add(mine)
                    mem.record_collect(mine)
                    return True

    # 走向最近的矿
    for ore in priority:
        mines = sorted(
            (m for m in all_mines(turn, ore) if m not in claimed and mem.mine_remaining(m) > 0),
            key=lambda m: (distance(role.pos, m), m.x, m.y),
        )
        for mine in mines:
            step = _safe_step(turn, role, mine, claimed)
            if step is not None:
                commands[role.unit_id] = move_command(step)
                return True
    return False


def _try_sell(
    turn: Turn, role: Unit, ores: dict[str, int],
    commands: dict[int, dict[str, Any]],
) -> bool:
    """在小贩旁批量贩卖矿石。"""
    vendor = turn.vendor_pos()
    if vendor is None:
        return False
    if distance(role.pos, vendor) > 1:
        step = _safe_step(turn, role, vendor, set())
        if step is not None:
            commands[role.unit_id] = move_command(step)
            return True
        return False
    # 选择单价最高的矿种卖
    day_no = turn.day_no()
    mem = get_memory()
    best_ore = max(
        (ore for ore, cnt in ores.items() if cnt > 0),
        key=lambda o: BASE_ORE_PRICES[o] * mem.ore_price_multiplier(o, day_no),
        default=None,
    )
    if best_ore is not None and ores[best_ore] > 0:
        commands[role.unit_id] = sell_command(best_ore, ores[best_ore])
        return True
    return False


def _try_buy(turn: Turn, role: Unit, commands: dict[int, dict[str, Any]]) -> bool:
    """
    在武器商店购买下一个升级券。
    购买优先级：火箭升级券 > 电磁升级券 > 基地升级券 > 围墙修复包
    """
    mem = get_memory()
    # 按优先级尝试购买
    priority = _build_purchase_priority(turn)
    for item_name in priority:
        price = _shop_price(turn, item_name)
        if price is None or turn.gold < price:
            continue
        if role.backpack_full:
            continue
        commands[role.unit_id] = buy_command(item_name, 1)
        return True
    return False


def _shop_price(turn: Turn, name: str) -> int | None:
    """查询武器商店中某商品的价格。"""
    for item in turn.weapon_shop:
        if item.name == name:
            return item.price
    return None


def _build_purchase_priority(turn: Turn) -> list[str]:
    """
    根据当前建筑等级构建购买优先级列表。
    优先把火箭升满（全图射程 + AoE），然后电磁，再基地，最后墙。
    """
    priority: list[str] = []
    rockets = [w for w in turn.weapons() if w.kind == "rocket"]
    railguns = [w for w in turn.weapons() if w.kind == "railgun"]
    station = turn.station()

    # 火箭 L1→L2
    if any(w.level == 1 for w in rockets):
        priority.append("WeaponUpgradeVoucher1")
    # 火箭 L2→L3
    if any(w.level == 2 for w in rockets):
        priority.append("WeaponUpgradeVoucher2")
    # 电磁 L1→L2
    if any(w.level == 1 for w in railguns):
        priority.append("WeaponUpgradeVoucher1")
    # 电磁 L2→L3
    if any(w.level == 2 for w in railguns):
        priority.append("WeaponUpgradeVoucher2")
    # 基地升级
    if station is not None and station.level < 3:
        priority.append(f"StationUpgradeVoucher{station.level}")
    # 围墙修复包（便宜，常备）
    priority.append("WallFixer")
    # 生命药剂
    priority.append("Medicine")
    # 进攻：金币盈余时购买召唤令（低优先级）
    # 先买中型/大型召唤令，对对方防线压力更大
    if turn.gold >= 300:
        priority.append("LargeRobotSummonOrder")
    if turn.gold >= 200:
        priority.append("MiddleRobotSummonOrder")
    priority.append("SmallRobotSummonOrder")
    return priority


def _try_use_upgrade(turn: Turn, role: Unit, commands: dict[int, dict[str, Any]]) -> bool:
    """如果背包里有升级券且站在目标建筑旁，使用它。"""
    station = turn.station()
    # 武器升级券：找等级最低的武器
    weapons = turn.weapons()
    upgradeable = sorted(weapons, key=lambda w: (w.level, w.unit_id))

    for w in upgradeable:
        if w.level >= 3:
            continue
        voucher = f"WeaponUpgradeVoucher{w.level}"
        if role.has_item(voucher) and distance(role.pos, w.pos) <= 1:
            commands[role.unit_id] = use_command(voucher, w.pos)
            return True

    # 基地升级券
    if station is not None and station.level < 3:
        voucher = f"StationUpgradeVoucher{station.level}"
        if role.has_item(voucher) and distance(role.pos, station.pos) <= 1:
            commands[role.unit_id] = use_command(voucher, station.pos)
            return True

    # 围墙修复包：找残血围墙
    for wall in turn.walls():
        if wall.health < 1000 and role.has_item("WallFixer"):
            if distance(role.pos, wall.pos) <= 1:
                commands[role.unit_id] = use_command("WallFixer", wall.pos)
                return True

    # 机器人召唤令：白天使用，增加对方下一夜机器人数量
    # 任何位置都可使用，无需目标坐标
    for summon in ("BossRobotSummonOrder", "LargeRobotSummonOrder",
                   "MiddleRobotSummonOrder", "SmallRobotSummonOrder"):
        if role.has_item(summon):
            commands[role.unit_id] = use_command(summon)
            return True

    return False


def _build_or_walk(
    turn: Turn, role: Unit, target: Pos, name: str,
    claimed: set[Pos], commands: dict[int, dict[str, Any]],
) -> None:
    """
    建造或走向建造点。
    若已在目标相邻格则建造，否则走过去。
    """
    if role.pos != target and distance(role.pos, target) <= 1:
        commands[role.unit_id] = build_command(target, name)
        claimed.add(target)
        return
    step = _safe_step(turn, role, target, claimed)
    if step is not None:
        commands[role.unit_id] = move_command(step)


def _safe_step(
    turn: Turn, role: Unit, goal: Pos, claimed: set[Pos],
) -> Pos | None:
    """安全地走一步：寻路并避免与其他角色碰撞。"""
    step = next_step(turn, role, goal)
    if step is None or step in claimed:
        return None
    claimed.add(step)
    return step
