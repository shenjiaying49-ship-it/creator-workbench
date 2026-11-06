#!/bin/bash
# 回填循环：每 25 分钟试一轮，成功（jocelyn>0 或 yuki>0）即退出
LOG="/Users/jyshen/claude folder/自我分析与规划/大号自媒体工作台/tools/backfill_loop.log"
while true; do
  "/Users/jyshen/claude folder/自我分析与规划/大号自媒体工作台/.venv/bin/python" -u "/Users/jyshen/claude folder/自我分析与规划/大号自媒体工作台/tools/backfill_all.py" >> "$LOG" 2>&1
  if tail -3 "$LOG" | grep -qE "RESULT: jocelyn=[1-9]|yuki=[1-9]"; then
    echo "[$(date '+%m-%d %H:%M')] 回填成功，退出循环" >> "$LOG"; break
  fi
  echo "[$(date '+%m-%d %H:%M')] 本轮无收获，25分钟后重试" >> "$LOG"
  sleep 1500
done
