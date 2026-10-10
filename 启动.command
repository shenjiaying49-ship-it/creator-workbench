#!/bin/bash
cd "$(dirname "$0")"
# 看门狗（保持常驻：server + 运营引擎掉线自动拉起）
pgrep -f watchdog.sh >/dev/null || nohup ./watchdog.sh > /tmp/dhmt_watchdog.log 2>&1 &
sleep 2
open "http://127.0.0.1:8501/index.html"
