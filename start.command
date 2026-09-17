#!/bin/sh
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$SCRIPT_DIR" || exit 1
if command -v python3 >/dev/null 2>&1; then
  exec python3 start.py
fi
echo "未找到 Python 3。请先安装 Python 3.10 或更新版本。"
printf "按回车键关闭..."
read -r _
