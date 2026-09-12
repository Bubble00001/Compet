"""
memory.py —— 跨回合持久状态
=============================

游戏进程常驻 1300 回合，需要跨回合记忆的信息：
- 矿石采集历史：每个矿已采集次数（0-10），用于检测枯竭
- 新闻事件表：官方消息导致的矿种停产/涨价时间表
- 升级计划：待购买/使用的升级券队列
- LLM 调用计数：每日 3 次配额
- 任务进度：自进化任务状态机
- 角色→塔配对：夜晚操塔的固定映射
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constants import CHALLENGER, DEFENDER, LLM_CALLS_PER_DAY
from .protocol import Pos


@dataclass
class NewsEvent:
    """
    官方新闻事件：影响某种矿石的采集与价格。
    示例：铁矿明天+后天停工，期间涨价。
    """
    ore: str              # 受影响矿种：stone/iron/copper
    stop_start_day: int   # 停工起始天（1-based）
    stop_end_day: int     # 停工结束天（含）
    price_multiplier: float  # 停工期间小贩收购价倍率


@dataclass
class Memory:
    """全局跨回合状态，单例模式通过 get_memory() 获取。"""

    # 矿石采集计数：pos -> 已采集次数
    mine_collect_count: dict[Pos, int] = field(default_factory=dict)
    # 已知矿的坐标集合（用于检测矿是否消失/刷新）
    known_mines: set[Pos] = field(default_factory=set)

    # 新闻事件表
    news_events: list[NewsEvent] = field(default_factory=list)

    # LLM 调用计数：day_no -> 已用次数
    llm_calls_today: dict[int, int] = field(default_factory=dict)
    last_llm_day: int = 0

    # 每日机器人召唤令使用计数
    summon_orders_today: dict[int, int] = field(default_factory=dict)

    # 角色 -> 塔 配对缓存（夜晚操塔用）
    role_tower_pairs: dict[int, int] = field(default_factory=dict)

    # 升级计划队列：待购买的商品名称列表（按优先级排序）
    upgrade_plan: list[str] = field(default_factory=list)

    # 任务状态机状态（由 tasks.py 管理）
    task_state: dict[str, Any] = field(default_factory=dict)

    # 上一回合的 roundNo（用于检测新的一天）
    last_round_no: int = 0

    # ---- 矿相关 ----

    def record_collect(self, mine_pos: Pos) -> None:
        """记录一次采集，次数+1。"""
        self.mine_collect_count[mine_pos] = self.mine_collect_count.get(mine_pos, 0) + 1
        self.known_mines.add(mine_pos)

    def mine_remaining(self, mine_pos: Pos) -> int:
        """矿剩余可采集次数（每个矿最多 10 次）。"""
        return max(0, 10 - self.mine_collect_count.get(mine_pos, 0))

    def sync_mines(self, current_mines: set[Pos]) -> None:
        """
        同步当前地图上的矿点：
        - 消失的矿从 known_mines 和计数中移除
        - 新出现的矿加入 known_mines，计数归零
        """
        # 移除已消失的矿
        vanished = self.known_mines - current_mines
        for pos in vanished:
            self.mine_collect_count.pop(pos, None)
        self.known_mines -= vanished
        # 新矿计数归零
        for pos in current_mines - self.known_mines:
            self.mine_collect_count[pos] = 0
        self.known_mines.update(current_mines)

    # ---- 新闻相关 ----

    def add_news_event(self, event: NewsEvent) -> None:
        """添加一条新闻事件。"""
        self.news_events.append(event)

    def ore_price_multiplier(self, ore: str, day_no: int) -> float:
        """获取某天某矿种的价格倍率。"""
        for event in self.news_events:
            if event.ore == ore and event.stop_start_day <= day_no <= event.stop_end_day:
                return event.price_multiplier
        return 1.0

    def ore_minable(self, ore: str, day_no: int) -> bool:
        """某天某矿种是否可采集。"""
        for event in self.news_events:
            if event.ore == ore and event.stop_start_day <= day_no <= event.stop_end_day:
                return False
        return True

    # ---- LLM 配额 ----

    def can_use_llm(self, day_no: int) -> bool:
        """今天是否还能调用 LLM（每日 3 次）。"""
        return self.llm_calls_today.get(day_no, 0) < LLM_CALLS_PER_DAY

    def record_llm_call(self, day_no: int) -> None:
        """记录一次 LLM 调用。"""
        self.llm_calls_today[day_no] = self.llm_calls_today.get(day_no, 0) + 1

    # ---- 召唤令计数 ----

    def can_use_summon(self, day_no: int, max_per_day: int) -> bool:
        """今天是否还能使用召唤令。"""
        return self.summon_orders_today.get(day_no, 0) < max_per_day

    def record_summon(self, day_no: int) -> None:
        """记录一次召唤令使用。"""
        self.summon_orders_today[day_no] = self.summon_orders_today.get(day_no, 0) + 1

    # ---- 升级计划 ----

    def pop_upgrade(self) -> str | None:
        """取出下一个待购买的升级商品。"""
        if self.upgrade_plan:
            return self.upgrade_plan.pop(0)
        return None

    def add_upgrade(self, name: str) -> None:
        """添加一个升级商品到计划末尾。"""
        if name not in self.upgrade_plan:
            self.upgrade_plan.append(name)

    # ---- 新闻解析 ----

    def parse_official_news(self, news: str, current_day: int) -> None:
        """
        解析官方消息，提取矿种停产/涨价事件。
        识别关键词：矿种名 + 停工/停产 + 时间词（明天/后天/2天）。
        示例："北部铁矿区昨夜发生塌方...明天全面停工...修复需要2天"
        → 铁矿从明天起停工2天，期间涨价。
        """
        if not news or "无重大新闻" in news:
            return

        ore_map = {
            "石": "stone", "石头": "stone",
            "铁": "iron", "铁矿": "iron",
            "铜": "copper", "铜矿": "copper",
        }
        # 识别矿种
        affected_ore = None
        for keyword, ore in ore_map.items():
            if keyword in news:
                affected_ore = ore
                break
        if affected_ore is None:
            return

        # 识别停工时长（天）
        stop_days = 2  # 默认2天
        for dur_word, days in [("2天", 2), ("两天", 2), ("3天", 3), ("三天", 3),
                                ("1天", 1), ("一天", 1), ("4天", 4), ("四天", 4)]:
            if dur_word in news:
                stop_days = days
                break

        # 识别停工起始：明天=current_day+1，后天=current_day+2
        start_day = current_day + 1  # 默认明天
        if "后天" in news:
            start_day = current_day + 2
        elif "明天" in news:
            start_day = current_day + 1
        elif "今日" in news or "今天" in news:
            start_day = current_day

        end_day = start_day + stop_days - 1
        # 停工期间价格翻倍（任务书示例：稀缺导致涨价）
        self.add_news_event(NewsEvent(
            ore=affected_ore,
            stop_start_day=start_day,
            stop_end_day=end_day,
            price_multiplier=2.0,
        ))


# 全局单例
_memory_instance: Memory | None = None


def get_memory() -> Memory:
    """获取全局 Memory 单例。"""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = Memory()
    return _memory_instance
