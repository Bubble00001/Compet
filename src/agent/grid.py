"""
grid.py —— A* 寻路
====================

8 方向切比雪夫距离的 A* 寻路，用于角色移动。

特性：
- 8 方向移动（含对角线），对角相邻的两个障碍物不构成阻挡
- 障碍集合由 Turn.blocked(role) 提供：中立元素 + 己方建筑 + 机器人
- 返回从当前位置到目标的第一步坐标

多角色协同防碰撞：
调用方（brain/economy）维护 claimed 集合，每走一步将目标格加入 claimed，
后续角色寻路时避开这些格子，避免"抢点/互换"碰撞。
"""

from heapq import heappop, heappush
from itertools import count

from .protocol import Pos, Turn, Unit, distance

# 8 方向移动步长
_STEPS = (
    (-1, -1), (-1, 0), (-1, 1),
    (0, -1),           (0, 1),
    (1, -1),  (1, 0),  (1, 1),
)


def next_step(turn: Turn, moving: Unit, goal: Pos) -> Pos | None:
    """
    A* 寻路，返回从 moving.pos 到 goal 的第一步坐标。
    若不可达返回 None。

    若 goal 本身被阻挡（矿/任务点/小贩/商店/建筑等），
    则自动寻找 goal 周围 8 格中最近的可达格作为实际目标。
    这样角色能走到目标相邻格（采集/贩卖/建造/操塔都只需要相邻）。

    代价函数：每步 cost=1，启发函数=切比雪夫距离。
    """
    blocked = turn.blocked(moving)

    # 若目标被阻挡，找周围最近的可达格
    if goal in blocked or not turn.land(goal):
        adjacents = [
            Pos(goal.x + dx, goal.y + dy)
            for dx, dy in _STEPS
        ]
        reachable = [
            p for p in adjacents
            if p not in blocked and turn.land(p)
        ]
        if not reachable:
            return None
        # 选离当前位置最近的相邻格
        goal = min(reachable, key=lambda p: distance(moving.pos, p))

    # 用计数器打破堆排序的并列，保证稳定性
    order = count()
    # 堆元素：(f值, g值, 序号, 当前位置)
    frontier: list[tuple[int, int, int, Pos]] = [
        (distance(moving.pos, goal), 0, next(order), moving.pos)
    ]
    came_from: dict[Pos, Pos] = {}
    best: dict[Pos, int] = {moving.pos: 0}
    seen: set[Pos] = set()

    while frontier:
        f, g, _, current = heappop(frontier)
        if current in seen:
            continue
        if current == goal:
            return _first_step(came_from, moving.pos, goal)
        seen.add(current)
        for dx, dy in _STEPS:
            step = Pos(current.x + dx, current.y + dy)
            # 跳过障碍和非空地
            if step in blocked or not turn.land(step):
                continue
            new_cost = g + 1
            # 仅当新路径更优时更新
            if new_cost >= best.get(step, new_cost + 1):
                continue
            best[step] = new_cost
            came_from[step] = current
            heappush(
                frontier,
                (new_cost + distance(step, goal), new_cost, next(order), step),
            )
    # 不可达
    return None


def _first_step(came_from: dict[Pos, Pos], start: Pos, goal: Pos) -> Pos:
    """
    从 came_from 路径中回溯，找到起点的下一步坐标。
    """
    current = goal
    while came_from[current] != start:
        current = came_from[current]
    return current
