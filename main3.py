#!/usr/bin/env python3
"""
main3.py —— 程序入口
======================

启动方式：python main3.py <port>
  - 解析命令行端口参数
  - 设置工作目录、Python 路径
  - 配置日志
  - 启动 agent.server.serve(port) 监听 0.0.0.0:port
"""

import logging
import os
import sys
from pathlib import Path


def main() -> None:
    """主函数：解析参数并启动 HTTP 服务。"""
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python main3.py <port>")
    port = int(sys.argv[1])
    root = Path(__file__).resolve().parent
    os.chdir(root)
    sys.path.insert(0, str(root / "src"))

    # 日志输出到 stdout，便于判题器采集
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s | %(message)s",
    )

    from agent.server import serve

    logging.info("listening on 0.0.0.0:%d", port)
    serve(port)


if __name__ == "__main__":
    main()
