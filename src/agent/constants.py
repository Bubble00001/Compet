"""
constants.py —— 《未来战争》Bot 全局常量表
=============================================

本文件集中存放所有"魔数"，包括：
- 昼夜回合数、地图尺寸
- 单位/武器/机器人属性
- 商品价格与名称
- 角色 ID 段
- 动作码 / 中立元素类型 / 错误码

规则依据：docs/任务书.md 与 docs/接口文档.md。
若 demo 实测与文档冲突，实测结论标注在对应常量旁的注释中。
"""

from __future__ import annotations


# ============================================================================
# 时间 / 回合
# ============================================================================

DAY_ROUNDS = 70          # 每个白天 70 回合
NIGHT_ROUNDS = 60        # 每个夜晚 60 回合
ROUNDS_PER_DAY = DAY_ROUNDS + NIGHT_ROUNDS  # 130 回合/天
MAX_ROUNDS = 1300        # 单场最大 10 天

# 每日 LLM 调用次数上限（接口文档 errorCode=5 说明）
LLM_CALLS_PER_DAY = 3
# 沙盒 executeCmd 单回合执行时长上限（秒）
CMD_TIMEOUT_SECONDS = 15


# ============================================================================
# 地图
# ============================================================================

MAP_WIDTH = 41
MAP_HEIGHT = 32

# 视野距离
VISION_RANGE = 4


# ============================================================================
# 单位类型 / 角色类型（roleType 取值）
# ============================================================================

STATION = "station"           # 基地
GATLING = "gatling"           # 加特林炮台
RAILGUN = "railgun"           # 电磁狙击炮
ROCKET = "rocket"             # 火箭发射台
WALL = "wall"                 # 围墙
WORKER = "worker"             # 工人
PIONEER = "pioneer"           # 开拓者

# 可操控武器的塔
TOWER_TYPES = (GATLING, RAILGUN, ROCKET)
# 可被操控的角色（工人 + 开拓者）
CONTROLLABLE_TYPES = (WORKER, PIONEER)


# ============================================================================
# 中立元素类型（neutralType 取值）
# ============================================================================

STONE_MINE = "stone"          # 石矿
IRON_MINE = "iron"            # 铁矿
COPPER_MINE = "copper"        # 铜矿
VENDOR = "vendor"             # 小贩
WEAPON_SHOP = "weaponShop"    # 武器商店
CHALLENGER_TP1 = "challengerTaskPoint1"
CHALLENGER_TP2 = "challengerTaskPoint2"
DEFENDER_TP1 = "defenderTaskPoint1"
DEFENDER_TP2 = "defenderTaskPoint2"

# 己方任务点类型（根据阵营动态选择）
TASK_POINT_TYPES = (CHALLENGER_TP1, CHALLENGER_TP2)  # 默认 challenger，运行时按 type 切换
LAND = "land"  # 空地（zones 中不存在的格子默认为空地）


# ============================================================================
# 动作码（Response action 字段）
# ============================================================================

ACT_MOVE = "move"
ACT_ATTACK = "attack"
ACT_SELL = "sell"
ACT_BUY = "buy"
ACT_BUILD = "build"
ACT_REMOVE = "remove"
ACT_ACCEPT_TASK = "acceptTask"
ACT_SUBMIT_ANSWER = "submitAnswer"
ACT_SUMMON_TREASURE = "summonTreasure"
ACT_USE = "use"
ACT_DROP = "drop"
ACT_COLLECT = "collect"

# 全部合法动作码集合
ALL_ACTIONS = (
    ACT_MOVE, ACT_ATTACK, ACT_SELL, ACT_BUY, ACT_BUILD, ACT_REMOVE,
    ACT_ACCEPT_TASK, ACT_SUBMIT_ANSWER, ACT_SUMMON_TREASURE,
    ACT_USE, ACT_DROP, ACT_COLLECT,
)

# 仅白天可用的动作
DAY_ONLY_ACTIONS = (ACT_BUILD, ACT_COLLECT)
# 仅黑夜可用的动作
NIGHT_ONLY_ACTIONS = (ACT_ATTACK,)


# ============================================================================
# 机器人类型（robot roleType 取值）
# ============================================================================

ROBOT_SMALL = "smallRobot"
ROBOT_MIDDLE = "middleRobot"
ROBOT_LARGE = "largeRobot"
ROBOT_BOSS = "bossRobot"

# 机器人属性：(攻击力, 攻击距离, 血量, 击杀积分)
ROBOT_STATS = {
    ROBOT_SMALL:  (5,  3, 40,  1),
    ROBOT_MIDDLE: (10, 3, 60,  2),
    ROBOT_LARGE:  (20, 3, 500, 4),
    ROBOT_BOSS:   (40, 3, 800, 10),
}


# ============================================================================
# 建筑 / 武器属性
# ============================================================================

# 武器建造代价（金币）
WEAPON_BUILD_COST = 25

# 围墙建造材料
WALL_MATERIAL = "stone"

# 基地血量（按等级）
STATION_HEALTH = (1500, 3000, 4500)

# 围墙血量（按等级）
WALL_HEALTH = (1000, 1500, 2000)

# 武器属性表：
#   key: 武器类型
#   value: dict，level1/2/3 对应的 (攻击距离, 攻击力, 攻击冷却)
#   加特林攻击力为 10*level，每级子弹数=level
#   电磁狙击炮攻击力为 10*level（穿透伤害）
#   火箭发射台攻击力为 20*level，溅射=10*level，冷却3回合
WEAPON_RANGE_BY_LEVEL = {
    GATLING: (3, 5, 7),
    RAILGUN: (6, 8, 10),
    ROCKET: (10, 15, 10 ** 9),  # L3 全图射程
}
WEAPON_DAMAGE_BY_LEVEL = {
    GATLING: (10, 20, 30),    # 每发 10*level
    RAILGUN: (10, 20, 30),    # 穿透能量 10*level
    ROCKET: (20, 40, 60),     # 中心伤害 20*level，溅射 10*level
}
ROCKET_COOLDOWN = 3  # 火箭冷却回合数

# 武器最大可建造数量
MAX_WEAPON_COUNT = 3


# ============================================================================
# 角色属性
# ============================================================================

PIONEER_HP = 200
PIONEER_CAPACITY = 40
WORKER_HP = 220
WORKER_CAPACITY = 100

# 角色阵亡后复活回合数（次日白天开始后 20 回合）
REVIVE_DELAY_ROUNDS = 20

# 初始资源
INITIAL_GOLD = 75


# ============================================================================
# 武器商店商品（名称 -> 价格）
# ============================================================================

# 建筑升级券
WEAPON_UPGRADE_VOUCHER_1 = "WeaponUpgradeVoucher1"   # L1→L2
WEAPON_UPGRADE_VOUCHER_2 = "WeaponUpgradeVoucher2"   # L2→L3
WALL_UPGRADE_VOUCHER_1 = "WallUpgradeVoucher1"
WALL_UPGRADE_VOUCHER_2 = "WallUpgradeVoucher2"
STATION_UPGRADE_VOUCHER_1 = "StationUpgradeVoucher1"
STATION_UPGRADE_VOUCHER_2 = "StationUpgradeVoucher2"

# 消耗品
WALL_FIXER = "WallFixer"
MEDICINE = "Medicine"
DIZZY_WEAPON = "DizzyWeapon"
BOMB = "Bomb"
SMALL_ROBOT_SUMMON = "SmallRobotSummonOrder"
MIDDLE_ROBOT_SUMMON = "MiddleRobotSummonOrder"
LARGE_ROBOT_SUMMON = "LargeRobotSummonOrder"
BOSS_ROBOT_SUMMON = "BossRobotSummonOrder"

# 任务用品（6 种，各 15 金；列表不固定，随地图刷新）
ACIENT_TABLET = "AcientTablet"
STAR_SAND = "StarSand"
FLAME_BREATH = "FlameBreath"
FROST_POTION = "FrostPotion"
THORN_AMULET = "ThornAmulet"
IRON_WHISTLE = "IronWhistle"

# 全商品价格表
SHOP_PRICES = {
    WEAPON_UPGRADE_VOUCHER_1: 100,
    WEAPON_UPGRADE_VOUCHER_2: 150,
    WALL_UPGRADE_VOUCHER_1: 20,
    WALL_UPGRADE_VOUCHER_2: 30,
    STATION_UPGRADE_VOUCHER_1: 100,
    STATION_UPGRADE_VOUCHER_2: 150,
    WALL_FIXER: 10,
    MEDICINE: 10,
    DIZZY_WEAPON: 100,
    BOMB: 100,
    SMALL_ROBOT_SUMMON: 20,
    MIDDLE_ROBOT_SUMMON: 30,
    LARGE_ROBOT_SUMMON: 100,
    BOSS_ROBOT_SUMMON: 200,
    ACIENT_TABLET: 15,
    STAR_SAND: 15,
    FLAME_BREATH: 15,
    FROST_POTION: 15,
    THORN_AMULET: 15,
    IRON_WHISTLE: 15,
}

# 每日机器人召唤令使用上限
MAX_SUMMON_ORDERS_PER_DAY = 10


# ============================================================================
# 小贩矿石收购价（基础价；新闻会波动）
# ============================================================================

BASE_ORE_PRICES = {
    "stone": 1,
    "iron": 3,
    "copper": 5,
}


# ============================================================================
# 角色 ID 段（接口文档 1.3.1）
# ============================================================================

# 挑战者方 ID 段
CHALLENGER_WORKER1_ID = 10010
CHALLENGER_PIONEER_ID = 10011
CHALLENGER_WORKER2_ID = 10012
CHALLENGER_STATION_ID = 10013
# 挑战者塔 ID 段：gatling 10020-10022, railgun 10030-10032, rocket 10040-10042
CHALLENGER_TOWER_ID_RANGES = {
    GATLING: (10020, 10022),
    RAILGUN: (10030, 10032),
    ROCKET: (10040, 10042),
}
CHALLENGER_WALL_ID_START = 40000

# 防守者方 ID 段
DEFENDER_WORKER1_ID = 20010
DEFENDER_PIONEER_ID = 20011
DEFENDER_WORKER2_ID = 20012
DEFENDER_STATION_ID = 20013
DEFENDER_TOWER_ID_RANGES = {
    GATLING: (20020, 20022),
    RAILGUN: (20030, 20032),
    ROCKET: (20040, 20042),
}
DEFENDER_WALL_ID_START = 41000


# ============================================================================
# 错误码（接口文档 1.7）
# ============================================================================

ERR_UNKNOWN = 0
ERR_TASK_TIMEOUT = 1
ERR_ANSWER_WRONG = 2
ERR_NETWORK = 3
ERR_COMMAND = 4
ERR_LLM_QUOTA = 5


# ============================================================================
# summonTreasure 结果码（接口文档 Request lastSummonTreasureResult）
# ============================================================================

TREASURE_NOT_PROBED = 0       # 未探测（没使用或非法）
TREASURE_SUCCESS = 1          # 成功获取宝藏
TREASURE_NOT_AVAILABLE = 2    # 无宝藏或暂未开启
TREASURE_WRONG_ITEM = 3       # 献祭物品错误
TREASURE_EMPTY = 4            # 宝藏已空


# ============================================================================
# 阵营
# ============================================================================

CHALLENGER = "challenger"
DEFENDER = "defender"
