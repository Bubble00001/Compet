"""
combat.py —— 夜晚火控
======================

三种武器的目标选择策略：
- 电磁狙击炮(railgun)：选射程内血量最高的目标，1 个目标，穿透直线
- 火箭发射台(rocket)：选机器人聚堆位置最大化 3×3 溅射覆盖，目标数=等级，
  cooldown>0 时禁射
- 加特林炮台(gatling)：选同一 90° 锥内的 level 个目标，每发 10 伤

目标威胁度排序：距基地近 + 血量高 + 类型积分高 的优先。
"""

from __future__ import annotations

from .constants import (
    GATLING, RAILGUN, ROBOT_BOSS, ROBOT_LARGE, ROBOT_MIDDLE, ROBOT_SMALL,
    ROBOT_STATS, ROCKET,
)
from .protocol import Pos, Robot, Turn, Unit, distance

# 机器人类型积分权重（用于目标排序）
_ROBOT_SCORE = {
    ROBOT_SMALL: 1,
    ROBOT_MIDDLE: 2,
    ROBOT_LARGE: 4,
    ROBOT_BOSS: 10,
}


def choose_targets(turn: Turn, tower: Unit) -> list[Pos] | None:
    """
    为某塔选择攻击目标。
    返回目标坐标列表（长度 = 武器等级，电磁为 1），无目标返回 None。
    """
    if tower.cooldown > 0:
        return None

    reach = tower.range_of_attack()
    # 射程内的存活机器人
    in_range = [
        r for r in turn.robots
        if r.health > 0 and distance(tower.pos, r.pos) <= reach
    ]
    if not in_range:
        return None

    if tower.kind == RAILGUN:
        return _choose_railgun(in_range)
    if tower.kind == ROCKET:
        return _choose_rocket(turn, tower, in_range)
    if tower.kind == GATLING:
        return _choose_gatling(tower.pos, in_range, tower.level)
    return None


def _threat_sort_key(robot: Robot, tower_pos: Pos) -> tuple:
    """
    目标威胁度排序键：
    1. 距塔距离（近的优先）
    2. 血量（高的优先，电磁打大怪）
    3. 类型积分（BOSS > 大 > 中 > 小）
    """
    score = _ROBOT_SCORE.get(robot.role_type, 0)
    return (distance(tower_pos, robot.pos), -robot.health, -score)


def _choose_railgun(in_range: list[Robot]) -> list[Pos] | None:
    """电磁狙击炮：选血量最高的目标，1 个目标。"""
    target = max(in_range, key=lambda r: (r.health, _ROBOT_SCORE.get(r.role_type, 0)))
    return [target.pos]


def _choose_rocket(
    turn: Turn, tower: Unit, in_range: list[Robot],
) -> list[Pos] | None:
    """
    火箭发射台：选择 level 个落点，最大化 3×3 溅射覆盖的机器人总血量。
    多落点可重叠叠加伤害。
    """
    level = max(tower.level, 1)
    if level == 1:
        best = _best_splash_pos(turn, tower, in_range)
        return [best] if best else None

    # 多级：贪心选多个不重叠或少重叠的落点
    chosen: list[Pos] = []
    remaining = list(in_range)
    for _ in range(level):
        if not remaining:
            # 没有更多机器人，用最后一个落点填充
            if chosen:
                chosen.append(chosen[-1])
            continue
        best = _best_splash_pos(turn, tower, remaining)
        if best is None:
            break
        chosen.append(best)
        # 移除已被覆盖的机器人（近似：3×3 内的）
        remaining = [
            r for r in remaining if distance(r.pos, best) > 1
        ]
    # 不足 level 个时复制最后一个
    while len(chosen) < level and chosen:
        chosen.append(chosen[-1])
    return chosen if chosen else None


def _best_splash_pos(
    turn: Turn, tower: Unit, robots: list[Robot],
) -> Pos | None:
    """
    找到使 3×3 溅射覆盖机器人总血量最大的落点。
    候选点：每个机器人周围 3×3 的格子中，在射程内的点。
    """
    reach = tower.range_of_attack()
    candidates: set[Pos] = set()
    for r in robots:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                pos = Pos(r.pos.x + dx, r.pos.y + dy)
                if distance(tower.pos, pos) <= reach:
                    candidates.add(pos)

    if not candidates:
        return None

    def total_covered_hp(pos: Pos) -> int:
        return sum(
            r.health for r in robots if distance(r.pos, pos) <= 1
        )

    best = max(candidates, key=total_covered_hp)
    return best


def _choose_gatling(
    tower_pos: Pos, in_range: list[Robot], level: int,
) -> list[Pos] | None:
    """
    加特林炮台：选 level 个落在同一 90° 锥内的目标。
    策略：以血量最高的目标为基准方向，选同方向夹角 ≤ 90° 的目标。
    """
    level = max(level, 1)
    if len(in_range) < level:
        # 目标不足，能选几个选几个（但指令要求目标数=等级，这里返回所有可用目标，
        # validate 层会修正；实际应复制目标补足）
        targets = sorted(in_range, key=lambda r: _threat_sort_key(r, tower_pos))
        positions = [r.pos for r in targets]
        while len(positions) < level:
            positions.append(positions[-1])
        return positions

    # 按威胁度排序
    sorted_robots = sorted(in_range, key=lambda r: _threat_sort_key(r, tower_pos))
    # 尝试以每个机器人为基准方向，找 level 个同锥角目标
    for base in sorted_robots:
        bx, by = base.pos.x - tower_pos.x, base.pos.y - tower_pos.y
        if bx == 0 and by == 0:
            continue
        cone = [base]
        for r in sorted_robots:
            if r is base:
                continue
            rx, ry = r.pos.x - tower_pos.x, r.pos.y - tower_pos.y
            # 点积 >= 0 表示夹角 <= 90°
            if bx * rx + by * ry >= 0:
                cone.append(r)
            if len(cone) >= level:
                break
        if len(cone) >= level:
            return [r.pos for r in cone[:level]]

    # 兜底：取前 level 个
    return [r.pos for r in sorted_robots[:level]]
