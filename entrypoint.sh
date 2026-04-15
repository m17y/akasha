#!/bin/bash
set -e

# 初始化知识库（首次运行）
akasha init

# 启动 wiki 网站（后台）
akasha site serve &

# 启动 Agent（前台，飞书通道等）
exec akasha start
