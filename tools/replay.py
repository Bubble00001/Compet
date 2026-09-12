"""
tools/replay.py —— 本地回放测试脚本
======================================

用法：python tools/replay.py <request.json>

读取一个 Request JSON 文件，调用 decide()，校验输出：
1. Response 可被 JSON 解析
2. 所有指令通过 validate.sanitize 合法性校验
3. 打印各角色指令供人工检查

用于在本地快速验证代码改动不破坏协议合法性。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# 确保能找到 src 包
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.brain import decide  # noqa: E402
from agent.protocol import Turn  # noqa: E402
from agent.validate import sanitize  # noqa: E402


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python tools/replay.py <request.json>")

    path = Path(sys.argv[1])
    raw = path.read_text(encoding="utf-8")
    # 兼容样例文件中可能存在的尾随逗号
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    payload = json.loads(raw)

    commands, prompt, execute_cmd = decide(payload)
    turn = Turn.load(payload)
    clean = sanitize(turn, commands)

    print(f"=== Round {turn.round_no} | {'DAY' if turn.is_day else 'NIGHT'} "
          f"| team={turn.team_type} | gold={turn.gold} ===")
    print(f"Commands: {len(clean)} (raw {len(commands)}), "
          f"prompt={bool(prompt)}, executeCmd={bool(execute_cmd)}")
    print()
    for role_id, cmd in clean.items():
        # 反查角色类型
        kind = "?"
        for unit in turn.ours:
            if unit.unit_id == role_id:
                kind = unit.kind
                break
        print(f"  [{role_id}] {kind}: {json.dumps(cmd, ensure_ascii=False)}")

    # 校验：clean 后的指令数量应等于 raw 中合法的数量
    # （sanitize 会剔除非法指令，若有剔除则打印警告）
    dropped = len(commands) - len(clean)
    if dropped > 0:
        print(f"\n[WARN] {dropped} illegal command(s) dropped by sanitize!")
        sys.exit(1)
    else:
        print("\n[OK] All commands passed validation.")


if __name__ == "__main__":
    main()
