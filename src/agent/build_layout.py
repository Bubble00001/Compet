"""
build_layout.py —— 建造布局规划
================================

根据实测结论：
- 蓝色武器区：基地周围第一圈（切比雪夫距离 1）
- 黄色围墙区：基地周围第二圈（切比雪夫距离 2）
- 机器人刷新位置：根据基地位置在对应的正左/正右侧
  * challenger（基地左上）→ 机器人从正右（+x）来
  * defender（基地右下）→ 机器人从正左（-x）来
- 墙布局：靠近机器人一侧 6 格 + 侧面靠近机器人的上下各 2 格 = 10 墙
  形成 C 形，开口朝向基地，机器人先撞平直的一侧

塔配置（实测结论）：1 火箭 + 2 电磁狙击炮（加特林不如电磁）
"""

from __future__ import annotations

from .constants import CHALLENGER, GATLING, RAILGUN, ROCKET
from .protocol import Pos, Turn, Unit, distance, station_footprint

# 塔建造顺序：火箭优先（AoE 核心），然后两座电磁
TOWER_LOADOUT = (ROCKET, RAILGUN, RAILGUN)


def robot_approach_dx(turn: Turn) -> int:
    """
    机器人来袭方向（x 方向偏移）。
    challenger 基地在左上 → 机器人从正右来 → dx = +1
    defender 基地在右下 → 机器人从正左来 → dx = -1
    """
    return 1 if turn.team_type == CHALLENGER else -1


def tower_sites(turn: Turn) -> tuple[Pos, ...]:
    """
    返回 3 个塔位（蓝色区，基地第一圈）。
    优先放在机器人来袭侧，使塔能越过墙射击。
    """
    station = turn.station()
    if station is None:
        return ()
    footprint = station_footprint(station.pos)
    xs = [p.x for p in footprint]
    ys = [p.y for p in footprint]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    dx = robot_approach_dx(turn)
    # 来袭侧的 x 坐标（蓝区最外侧）
    side_x = xmax + 1 if dx > 0 else xmin - 1
    # 沿 y 方向取 3 个格子：ymin-1, ymin, ymax（覆盖基地高度 + 下方一格）
    candidates = [
        Pos(side_x, ymin - 1),
        Pos(side_x, ymin),
        Pos(side_x, ymax),
    ]
    # 过滤掉非空地（被矿/中立元素占据）
    result = [pos for pos in candidates if turn.land(pos)]
    # 不足 3 个时，尝试补充另一侧的格子
    if len(result) < 3:
        other_x = xmin - 1 if dx > 0 else xmax + 1
        for y in (ymin - 1, ymin, ymax, ymax + 1):
            pos = Pos(other_x, y)
            if turn.land(pos) and pos not in result:
                result.append(pos)
            if len(result) >= 3:
                break
    return tuple(result[:3])


def wall_sites(turn: Turn) -> tuple[Pos, ...]:
    """
    返回 10 个墙位（黄色区，基地第二圈），形成 C 形。
    C 形开口朝向基地，平直的一面对着机器人来袭方向。

    布局（以 challenger 为例，机器人从右来）：
        T T           ← 顶部侧翼 2 格
      R R R R R R     ← 右侧主体 6 格（含上下角）
        B B           ← 底部侧翼 2 格
    """
    station = turn.station()
    if station is None:
        return ()
    footprint = station_footprint(station.pos)
    xs = [p.x for p in footprint]
    ys = [p.y for p in footprint]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)

    dx = robot_approach_dx(turn)
    # 来袭侧的墙列 x 坐标（黄区最外侧，距离 2）
    side_x = xmax + 2 if dx > 0 else xmin - 2

    walls: list[Pos] = []

    # 1. 来袭侧主体列：6 格（含上下角）
    #    y 范围：ymin-2, ymin-1, ymin, ymax, ymax+1, ymax+2
    for y in (ymin - 2, ymin - 1, ymin, ymax, ymax + 1, ymax + 2):
        walls.append(Pos(side_x, y))

    # 2. 顶部侧翼：2 格，从侧列向基地方向延伸
    #    y = ymax+2，x = side_x - dx, side_x - 2*dx
    for step in (1, 2):
        walls.append(Pos(side_x - dx * step, ymax + 2))

    # 3. 底部侧翼：2 格
    for step in (1, 2):
        walls.append(Pos(side_x - dx * step, ymin - 2))

    # 过滤掉非空地，保持顺序（主体优先）
    result = [pos for pos in walls if turn.land(pos)]
    return tuple(result)


def stand_cells_for_tower(turn: Turn, tower: Unit) -> list[Pos]:
    """
    返回某塔周围可供操控角色站立的格子（相邻 8 格中的空地）。
    优先选择远离机器人一侧（基地侧）的格子，保证操塔角色安全。
    """
    station = turn.station()
    footprint = station_footprint(station.pos) if station else ()
    dx = robot_approach_dx(turn)

    candidates: list[Pos] = []
    for ddx in (-1, 0, 1):
        for ddy in (-1, 0, 1):
            if ddx == 0 and ddy == 0:
                continue
            pos = Pos(tower.pos.x + ddx, tower.pos.y + ddy)
            if not turn.land(pos):
                continue
            candidates.append(pos)

    # 排序：优先基地侧（与 dx 反向）、离基地近的格子
    def sort_key(pos: Pos) -> tuple:
        station_dist = min(distance(pos, c) for c in footprint) if footprint else 0
        # 越靠基地侧越好（dx>0 时 x 越小越好）
        side_score = -pos.x if dx > 0 else pos.x
        return (station_dist, side_score, pos.y)

    candidates.sort(key=sort_key)
    return candidates
