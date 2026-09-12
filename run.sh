#!/bin/bash
# run.sh —— 比赛启动脚本
# 用法：bash run.sh <port>
# 判题系统会调用此脚本并传入端口号。

set -e

PORT=${1:?"Usage: bash run.sh <port>"}

# 切换到脚本所在目录
cd "$(dirname "$0")"

# 启动 Bot
exec python main3.py "$PORT"
