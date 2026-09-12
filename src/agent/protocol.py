"""
protocol.py —— 《未来战争》Bot 协议层
=====================================

职责：
1. 将判题器下发的 Request JSON 解析为强类型数据模型（Turn / Unit / Robot / ...）
2. 提供所有动作指令的构造函数（move / attack / sell / buy / build / ...）

所有常量从 constants.py 导入，避免魔数散落。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# 重新导出 constants 中被其他模块直接引用的名称，保持向后兼容
from .constants import (  # noqa: F401  (re-export)
    DAY_ROUNDS,
    NIGHT_ROUNDS,
    ROUNDS_PER_DAY,
    WEAPON_BUILD_COST,
    WALL_MATERIAL,
    LAND,
    STATION,
    WALL,
    WORKER,
    PIONEER,
    GATLING,
    RAILGUN,
    ROCKET,
    TOWER_TYPES,
    CONTROLLABLE_TYPES,
    WEAPON_RANGE_BY_LEVEL as TOWER_RANGE_BY_LEVEL,
)


# ============================================================================
# 坐标与距离
# ============================================================================

@dataclass(frozen=True, slots=True)
class Pos:
    """地图坐标，原点 (0,0) 在左下角，X 向右，Y 向上。"""

    x: int
    y: int

    @classmethod
    def load(cls, raw: Any) -> "Pos":
        """从 {"x": int, "y": int} 构造。"""
        return cls(int(raw["x"]), int(raw["y"]))

    def dump(self) -> dict[str, int]:
        """序列化为 {"x": x, "y": y}。"""
        return {"x": self.x, "y": self.y}


def distance(first: Pos, second: Pos) -> int:
    """切比雪夫距离：max(|x1-x2|, |y1-y2|)。"""
    return max(abs(first.x - second.x), abs(first.y - second.y))


def station_footprint(pos: Pos) -> tuple[Pos, ...]:
    """
    基地是 2×2 的，pos 是左上角坐标。
    返回基地占据的 4 个格子：
        (x,y) ─ (x+1,y)
          │       │
        (x,y-1) ─ (x+1,y-1)
    """
    return (
        pos,
        Pos(pos.x + 1, pos.y),
        Pos(pos.x, pos.y - 1),
        Pos(pos.x + 1, pos.y - 1),
    )


# ============================================================================
# 单位（己方角色 / 建筑）
# ============================================================================

@dataclass(frozen=True, slots=True)
class Unit:
    """
    己方单位：角色（工人/开拓者）或建筑（基地/塔/围墙）。
    字段说明见接口文档 1.3.1。
    """

    unit_id: int                  # 角色/单位唯一编号
    pos: Pos                      # 坐标（基地为左上角）
    kind: str                     # roleType：station/gatling/railgun/rocket/wall/pioneer/worker
    health: int                   # 当前剩余血量
    level: int                    # 等级（建筑持有，角色为 0）
    cooldown: int                 # 武器冷却剩余回合数（仅火箭）
    attack_range: int             # 攻击距离
    capacity: int | None          # 背包容量上限（角色有，建筑为 None）
    backpack: tuple[str, ...]     # 背包物品名称列表

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Unit":
        raw_capacity = raw.get("backPackCapability")
        return cls(
            int(raw.get("id") or 0),
            Pos.load(raw["pos"]),
            str(raw["roleType"]),
            int(raw.get("health") or 0),
            int(raw.get("level") or 0),
            int(raw.get("cooldown") or 0),
            int(raw.get("attackRange") or 0),
            int(raw_capacity) if raw_capacity is not None else None,
            tuple(str(item) for item in raw.get("backpack") or ()),
        )

    @property
    def backpack_full(self) -> bool:
        """背包是否已满。"""
        if self.capacity is None:
            return False
        return len(self.backpack) >= self.capacity

    def range_of_attack(self) -> int:
        """
        武器攻击距离。
        优先用接口下发的 attackRange（rocket L3 下发 2147483647），
        否则按等级从常量表查表。
        """
        if self.attack_range > 0 and self.attack_range < 10 ** 8:
            return self.attack_range
        table = TOWER_RANGE_BY_LEVEL.get(self.kind)
        if table is None:
            return 0
        level = min(max(self.level, 1), len(table))
        return table[level - 1]

    def has_item(self, name: str) -> bool:
        """背包中是否存在指定物品。"""
        return name in self.backpack

    def count_item(self, name: str) -> int:
        """背包中指定物品的数量。"""
        return self.backpack.count(name)


# ============================================================================
# 机器人
# ============================================================================

@dataclass(frozen=True, slots=True)
class Robot:
    """
    场上机器人单位（全图可见）。
    字段说明见接口文档 1.5.1。
    """

    robot_id: int                # 机器人唯一编号
    pos: Pos                     # 当前坐标
    health: int                  # 当前剩余血量
    role_type: str               # 机器人类型：smallRobot/middleRobot/largeRobot/bossRobot
    abnormal_state: str          # 异常状态：被眩晕时为 "dizzy"，否则 ""
    target_team: str             # 攻击目标阵营：challenger / defender

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "Robot":
        return cls(
            int(raw["id"]),
            Pos.load(raw["pos"]),
            int(raw.get("health") or 0),
            str(raw.get("roleType") or ""),
            str(raw.get("abnormalState") or ""),
            str(raw.get("targetTeam") or ""),
        )


# ============================================================================
# 任务点信息
# ============================================================================

@dataclass(frozen=True, slots=True)
class PlayerTask:
    """己方任务点信息，见接口文档 1.3.2。"""

    task_type: str          # 任务类型：自进化类1 / 自进化类2
    task_position: Pos      # 任务点坐标
    cold_down_rounds: int   # 任务刷新冷却剩余回合数（0=可接取）
    score_reward: int       # 积分奖励
    gold_reward: int        # 金币奖励
    is_valid: bool          # 当前是否允许领取任务
    timeout_rounds: int     # 任务超时回合数

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "PlayerTask":
        return cls(
            str(raw.get("taskType") or ""),
            Pos.load(raw["taskPosition"]),
            int(raw.get("coldDownRounds") or 0),
            int(raw.get("scoreReward") or 0),
            int(raw.get("goldReward") or 0),
            bool(raw.get("isValid", False)),
            int(raw.get("timeoutRounds") or 0),
        )


# ============================================================================
# 商店 / 新闻 / 错误
# ============================================================================

@dataclass(frozen=True, slots=True)
class ShopItem:
    """商品条目：名称 + 价格。"""

    name: str
    price: int

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "ShopItem":
        return cls(str(raw["name"]), int(raw["price"]))


@dataclass(frozen=True, slots=True)
class WorldNews:
    """世界新闻：官方消息 + 民间传闻。"""

    official_news: str
    folk_legends: str

    @classmethod
    def load(cls, raw: Any) -> "WorldNews":
        raw = raw or {}
        return cls(
            str(raw.get("officialNews") or ""),
            str(raw.get("folkLegends") or ""),
        )


@dataclass(frozen=True, slots=True)
class GameError:
    """错误信息结构体，见接口文档 1.7。"""

    error_code: int
    description: str

    @classmethod
    def load(cls, raw: dict[str, Any]) -> "GameError":
        return cls(int(raw.get("errorCode") or 0), str(raw.get("description") or ""))


# ============================================================================
# 敌方单位（仅可见部分）
# ============================================================================

@dataclass(frozen=True, slots=True)
class Enemy:
    """敌方可见单位。基地与围墙全图可见，其他需进入视野。"""

    roles: tuple[Unit, ...]

    @classmethod
    def load(cls, raw: Any) -> "Enemy":
        raw = raw or {}
        return cls(
            tuple(Unit.load(role) for role in raw.get("roles") or ()),
        )


# ============================================================================
# 回合整体状态 Turn
# ============================================================================

@dataclass(frozen=True, slots=True)
class Turn:
    """
    一回合的完整状态快照。
    对应接口文档 Request 顶层结构。
    """

    round_no: int                              # 当前回合数
    is_day: bool                               # 是否白天
    gold: int                                  # 队伍当前金币
    total_score: int                           # 队伍累计总积分
    team_type: str                             # 阵营：challenger / defender
    team_id: str                               # 队伍唯一 ID
    team_name: str                             # 队伍名称
    width: int                                 # 地图宽度
    height: int                                # 地图高度
    zones: dict[Pos, str]                      # 中立元素 pos -> neutralType
    ours: tuple[Unit, ...]                     # 己方所有单位
    robots: tuple[Robot, ...]                  # 场上机器人
    enemy: Enemy                               # 敌方可见单位
    player_tasks: tuple[PlayerTask, ...]       # 己方任务点列表
    world_news: WorldNews                      # 世界新闻
    vendor_shop: tuple[ShopItem, ...]          # 小贩收购清单
    weapon_shop: tuple[ShopItem, ...]          # 武器商店出售清单
    phase_task: str                            # 当前已领取任务原文
    last_action_results: dict[int, bool]       # 上回合各角色动作合法性
    last_summon_result: int                    # 上回合 summonTreasure 结果码
    llm_resp: str                              # 上回合 LLM 响应内容
    last_cmd_result: str                       # 上回合 executeCmd 执行结果
    errors: tuple[GameError, ...]              # 本轮错误信息

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "Turn":
        """从 Request JSON 解析 Turn。"""
        round_no = int(payload["roundNo"])
        info = payload["mapInfo"]
        team = payload["teamOur"]

        # 解析 zones：同一 neutralType 可能占多格（如任务点2占两格）
        zones: dict[Pos, str] = {}
        for zone in info.get("zones") or ():
            zones[Pos.load(zone["pos"])] = str(zone["neutralType"])

        # 上回合动作结果 key 是字符串角色 ID
        raw_results = payload.get("lastRoundRoleActionResults") or {}
        last_action_results = {
            int(k): bool(v) for k, v in raw_results.items()
        }

        return cls(
            round_no=round_no,
            is_day=(round_no - 1) % ROUNDS_PER_DAY < DAY_ROUNDS,
            gold=int(team.get("goldNum") or 0),
            total_score=int(team.get("totalScore") or 0),
            team_type=str(team.get("type") or ""),
            team_id=str(team.get("teamId") or ""),
            team_name=str(team.get("teamName") or ""),
            width=int(info["width"]),
            height=int(info["height"]),
            zones=zones,
            ours=tuple(Unit.load(role) for role in team.get("roles") or ()),
            robots=tuple(
                Robot.load(robot)
                for robot in (payload.get("robot") or {}).get("roles") or ()
            ),
            enemy=Enemy.load(payload.get("teamEnemy")),
            player_tasks=tuple(
                PlayerTask.load(t) for t in team.get("playerTasks") or ()
            ),
            world_news=WorldNews.load(payload.get("worldNews")),
            vendor_shop=tuple(
                ShopItem.load(item) for item in payload.get("vendorShopList") or ()
            ),
            weapon_shop=tuple(
                ShopItem.load(item) for item in payload.get("weaponShopList") or ()
            ),
            phase_task=str(payload.get("phaseTask") or ""),
            last_action_results=last_action_results,
            last_summon_result=int(payload.get("lastSummonTreasureResult") or 0),
            llm_resp=str(payload.get("llmResp") or ""),
            last_cmd_result=str(payload.get("lastCmdResult") or ""),
            errors=tuple(
                GameError.load(e) for e in payload.get("errors") or ()
            ),
        )

    # ---- 便捷查询方法 ----

    def day_no(self) -> int:
        """当前是第几天（1-based）。"""
        return (self.round_no - 1) // ROUNDS_PER_DAY + 1

    def day_phase(self) -> str:
        """当前是白天还是夜晚的第几回合（1-based）。"""
        phase = (self.round_no - 1) % ROUNDS_PER_DAY
        if phase < DAY_ROUNDS:
            return f"day_{phase + 1}"
        return f"night_{phase - DAY_ROUNDS + 1}"

    def station(self) -> Unit | None:
        """己方基地单位。"""
        for unit in self.ours:
            if unit.kind == STATION:
                return unit
        return None

    def alive(self, kinds: tuple[str, ...]) -> tuple[Unit, ...]:
        """筛选存活的指定类型单位。"""
        return tuple(
            unit for unit in self.ours
            if unit.kind in kinds and unit.health > 0
        )

    def controllable(self) -> tuple[Unit, ...]:
        """可操控角色（工人+开拓者），按 ID 排序。"""
        return tuple(sorted(
            self.alive(CONTROLLABLE_TYPES), key=lambda unit: unit.unit_id,
        ))

    def workers(self) -> tuple[Unit, ...]:
        """工人列表，按 ID 排序。"""
        return tuple(sorted(
            self.alive((WORKER,)), key=lambda unit: unit.unit_id,
        ))

    def pioneer(self) -> Unit | None:
        """开拓者。"""
        for unit in self.alive((PIONEER,)):
            return unit
        return None

    def weapons(self) -> tuple[Unit, ...]:
        """武器塔列表，按坐标排序。"""
        return tuple(sorted(
            self.alive(TOWER_TYPES),
            key=lambda unit: (unit.pos.x, unit.pos.y),
        ))

    def walls(self) -> tuple[Unit, ...]:
        """围墙列表。"""
        return self.alive((WALL,))

    def stone_mines(self) -> tuple[Pos, ...]:
        """石矿坐标列表。"""
        return tuple(pos for pos, kind in self.zones.items() if kind == "stone")

    def iron_mines(self) -> tuple[Pos, ...]:
        """铁矿坐标列表。"""
        return tuple(pos for pos, kind in self.zones.items() if kind == "iron")

    def copper_mines(self) -> tuple[Pos, ...]:
        """铜矿坐标列表。"""
        return tuple(pos for pos, kind in self.zones.items() if kind == "copper")

    def vendor_pos(self) -> Pos | None:
        """小贩坐标。"""
        for pos, kind in self.zones.items():
            if kind == "vendor":
                return pos
        return None

    def weapon_shop_pos(self) -> Pos | None:
        """武器商店坐标。"""
        for pos, kind in self.zones.items():
            if kind == "weaponShop":
                return pos
        return None

    def our_task_points(self) -> tuple[PlayerTask, ...]:
        """己方任务点列表（按阵营过滤 task_type）。"""
        return self.player_tasks

    def footprint(self, unit: Unit) -> tuple[Pos, ...]:
        """单位占据的格子（基地 2×2，其他 1×1）。"""
        if unit.kind == STATION:
            return station_footprint(unit.pos)
        return (unit.pos,)

    def land(self, pos: Pos) -> bool:
        """坐标是否在地图内且为空地（zones 中不存在的格子默认空地）。"""
        if not 0 <= pos.x < self.width or not 0 <= pos.y < self.height:
            return False
        return self.zones.get(pos, LAND) == LAND

    def occupied_cells(self) -> frozenset[Pos]:
        """己方所有单位占据的格子集合。"""
        cells: set[Pos] = set()
        for unit in self.ours:
            cells.update(self.footprint(unit))
        return frozenset(cells)

    def blocked(self, moving: Unit) -> frozenset[Pos]:
        """
        移动阻挡集合：
        - 所有中立元素（矿/小贩/商店/任务点）
        - 己方建筑占据的格子
        - 机器人所在格子
        moving 角色自身位置不算阻挡。
        """
        cells = {pos for pos, kind in self.zones.items() if kind != LAND}
        cells.update(self.occupied_cells())
        cells.discard(moving.pos)
        for robot in self.robots:
            cells.add(robot.pos)
        return frozenset(cells)


# ============================================================================
# 指令构造函数
# ============================================================================
# 每个函数返回一个 dict，对应 response.txt 中 RoleCommand 结构。
# targetPos 永远是数组，即使只有一个目标。
# ============================================================================

def move_command(pos: Pos) -> dict[str, Any]:
    """移动：每回合移动一格。"""
    return {"action": "move", "targetPos": [pos.dump()]}


def attack_command(controller_id: int, targets: list[Pos]) -> dict[str, Any]:
    """
    操控武器攻击。
    - controller_id：操控武器的角色 ID
    - targets：攻击目标坐标数组
        * 加特林/火箭：targets 长度 = 武器等级
        * 电磁狙击炮：1 个目标
    注意：attack 指令的 key 是武器 ID（在 brain 中放入 commands[tower.unit_id]）。
    """
    return {
        "action": "attack",
        "targetPos": [pos.dump() for pos in targets],
        "controllerId": str(controller_id),
    }


def collect_command(pos: Pos) -> dict[str, Any]:
    """采集矿石：需在矿周围一格内。"""
    return {"action": "collect", "targetPos": [pos.dump()]}


def build_command(pos: Pos, name: str) -> dict[str, Any]:
    """
    建造武器工事或围墙。
    - name: "gatling"/"railgun"/"rocket"/"wall"
    仅工人白天可用，目标需在自身一格内。
    """
    return {"action": "build", "targetPos": [pos.dump()], "name": name}


def remove_command(pos: Pos) -> dict[str, Any]:
    """拆除围墙：需指定围墙坐标，仅工人可用。"""
    return {"action": "remove", "targetPos": [pos.dump()]}


def sell_command(name: str, num: int = 1) -> dict[str, Any]:
    """
    贩卖矿石给小贩。
    - name: "stone"/"iron"/"copper"
    - num: 数量，默认 1
    需在小贩周围一格内使用，支持批量。
    """
    return {"action": "sell", "name": name, "num": num}


def buy_command(name: str, num: int = 1) -> dict[str, Any]:
    """
    在武器商店购买商品。
    - name: 商品名称
    - num: 数量，默认 1
    需在武器商店周围一格内使用。
    """
    return {"action": "buy", "name": name, "num": num}


def use_command(name: str, target_pos: Pos | None = None) -> dict[str, Any]:
    """
    使用背包内物品。
    - name: 物品名称
    - target_pos: 部分物品需要指定坐标（升级券/围墙修复包/眩晕法宝/范围炸弹）
    升级券需在目标建筑周围一格内使用。
    """
    cmd: dict[str, Any] = {"action": "use", "name": name}
    if target_pos is not None:
        cmd["targetPos"] = [target_pos.dump()]
    return cmd


def drop_command(name: str) -> dict[str, Any]:
    """丢弃背包内指定物品。"""
    return {"action": "drop", "name": name}


def accept_task_command() -> dict[str, Any]:
    """领取任务：开拓者在己方任务点周围一格内触发。"""
    return {"action": "acceptTask"}


def submit_answer_command(task_answer: str) -> dict[str, Any]:
    """提交任务答案。"""
    return {"action": "submitAnswer", "taskAnswer": task_answer}


def summon_treasure_command(target_pos: Pos, items: list[str]) -> dict[str, Any]:
    """
    召唤宝藏：开拓者在祭坛周围一格内献祭任务用品。
    - target_pos: 祭坛坐标
    - items: 献祭物品名称数组（不能多不能少，无顺序限制）
    动作合法即消耗物品，不论是否开启宝藏。
    """
    return {
        "action": "summonTreasure",
        "targetPos": [target_pos.dump()],
        "item": list(items),
    }
