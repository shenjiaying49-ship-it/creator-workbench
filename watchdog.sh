#!/bin/bash
# 看门狗：工作台 server 掉线自动拉起（每 30 秒巡检）
# 注：auto_ops 自动发布引擎已停用（用户切换到持穗/Rohini 双轨月度节奏，发布按月手动执行）
# 需要重新启用自动发布时：nohup .venv/bin/python auto_ops.py > /tmp/auto_ops.log 2>&1 &
cd "$(dirname "$0")"

while true; do
  if ! lsof -ti:8501 >/dev/null 2>&1; then
    echo "[$(date '+%m-%d %H:%M')] server 不在，重启"
    nohup .venv/bin/python server.py > /tmp/dhmt_server.log 2>&1 &
  fi
  sleep 30
done
