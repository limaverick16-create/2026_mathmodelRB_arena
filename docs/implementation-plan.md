# Arena 实施计划

日期：2026-09-14  
对应设计：人工操控与策略可视化辐射源搜索软件设计

## 原则

- 新仓库只包含 Arena、必要规则代码、示例策略、测试和使用文档。
- 人工模式与策略模式共用唯一 Python 规则引擎。
- 核心规则采用测试先行：先写失败测试，再实现最小代码，最后重构。
- 运行时优先使用 Python 标准库；前端不要求 Node 构建。
- 不连接官方模拟器。
- 每个阶段结束后都可独立运行和验收。

## 阶段一：规则引擎与公开状态

### 文件

- `arena_core/models.py`
- `arena_core/geometry.py`
- `arena_core/engine.py`
- `arena_core/serialization.py`
- `tests/test_engine.py`
- `tests/test_geometry.py`
- `tests/test_serialization.py`

### 测试先行顺序

1. 固定种子生成相同地图；不同种子生成不同地图。
2. 源数量在 10–16；频道不重复。
3. 非定向模式全部为非定向源。
4. 有定向源模式按 `6/16` 概率抽样，并保证至少一个定向源。
5. 移动耗时为距离除以 5。
6. 检测为 5 秒，实际换频另加 1 秒。
7. 清除成功为 5 秒、失败为 3 秒，且清除不换频。
8. 5 米近距离、20 米清除和接收半径边界正确。
9. 测向误差可复现并落在 ±1°。
10. 公开状态不泄漏源真值、隐藏总数、真实半径或方向。
11. 有信号更新可能区域；非定向无信号记录严格排除圆；有定向源模式无信号不错误排除空间。
12. 完整清除后结束并公开最终源数。

### 验收命令

```bash
python -m pytest tests/test_engine.py tests/test_geometry.py tests/test_serialization.py -q
```

## 阶段二：本地服务与人工浏览器玩法

### 文件

- `arena_server/app.py`
- `arena_server/sessions.py`
- `arena_server/http.py`
- `web/index.html`
- `web/styles.css`
- `web/app.js`
- `web/map.js`
- `tests/test_api.py`
- `tests/test_sessions.py`

### 功能

1. 首页提供功能展示、非定向源、有定向源和策略实验室入口。
2. 单页内新建、暂停、恢复、结束和切换会话，不刷新浏览器。
3. 地图点击和坐标输入移动。
4. 单频道检测和清除。
5. 20 个频道状态与可多选图层。
6. 有信号可能区域、非定向无信号排除区、定向负观测点。
7. 批量检测队列按频道逐步执行，可暂停和取消剩余动作。
8. 双计时、操作记录和完成结算。
9. 情报菜单和无辅助标记。
10. 按玩家命令撤销；批量检测整体回退，审计事件保留。
11. 每步自动保存，浏览器重连后恢复。

### 验收

- API 行为测试通过；
- 浏览器能完成一局；
- 批量检测与逐个检测的结果和虚拟耗时一致；
- 撤销不倒退现实时间，并永久标记辅助；
- 正式接口返回中不存在隐藏真值。

## 阶段三：策略实验室与回放

### 文件

- `arena_sdk/__init__.py`
- `arena_sdk/types.py`
- `arena_server/strategy_runner.py`
- `strategies/example_random.py`
- `strategies/template.py`
- `web/strategy.js`
- `tests/test_strategy_runner.py`
- `tests/test_replay.py`

### 功能

1. `Strategy.reset(game_info)` 与 `Strategy.next_action(observation)` 接口。
2. 点击“刷新策略列表”热加载 `strategies/`，不刷新网页。
3. 策略在独立子进程中运行。
4. 支持运行、暂停、单步、调速和停止。
5. 每步复用人工模式的事件与地图动画。
6. 超时、异常和非法动作暂停并显示错误。
7. 导出、导入和重放 JSON 日志。

### 验收

- 人工与策略执行相同动作得到相同状态；
- 示例策略能够完成至少一张固定小型测试地图；
- 策略崩溃不会终止本地服务；
- 回放哈希一致，篡改日志被拒绝。

## 阶段四：排行榜提交、验证与页面

### 文件

- `arena_leaderboard/schema.py`
- `arena_leaderboard/github_auth.py`
- `arena_leaderboard/submission.py`
- `leaderboard/config.example.json`
- `leaderboard/build.py`
- `leaderboard/index.html`
- `.github/workflows/validate-submission.yml`
- `.github/workflows/publish-leaderboard.yml`
- `tests/test_submission.py`
- `tests/test_leaderboard.py`

### 功能

1. 只允许无辅助完整通关局提交。
2. 单一排行榜页面含四个分类页签。
3. 排名指标为单局总虚拟耗时除以源数。
4. 显示总源数；有定向源类别显示定向与非定向数量。
5. 每个 GitHub 用户每类只显示最好成绩。
6. 首次使用 GitHub Device Flow，后续点击一次提交。
7. 自动创建或复用 fork、分支和排行榜 PR。
8. 自动流程失败时下载本地提交包。
9. 人工日志由 Actions 重放；策略由无密钥、无网络、限资源任务重跑。
10. 发布任务只读取规范化结果，不执行参赛者代码。
11. GitHub Pages 自动更新排行榜。

### 仓库所有者一次性操作

1. 注册启用 Device Flow 的 GitHub 应用。
2. 把公开 Client ID 和仓库地址写入正式配置。
3. 启用 Actions、Pages 和主分支保护。
4. 检查 fork PR 工作流保持只读且没有密钥。

### 验收

- 无辅助资格判断、哈希和 schema 测试通过；
- 四类成绩不混排；
- 同账户仅选择每类最低秒/源；
- 引擎版本不一致的提交被隔离或拒绝；
- 本地无 GitHub 配置时仍可导出提交包。

## 阶段五：打包、文档和最终验证

### 文件

- `start.py`
- `start.bat`
- `start.command`
- `requirements-dev.txt`
- `README.md`
- `docs/strategy-api.md`
- `docs/leaderboard-maintenance.md`

### 功能与验收

1. `python start.py` 寻找空闲端口、启动本地服务并打开浏览器。
2. Windows 与 macOS 双击脚本调用同一入口。
3. 缺少 Python 时给出明确提示；运行时不要求 Node。
4. README 覆盖人工游玩、策略接入、回放、排行榜提交和维护。
5. 运行全部测试及覆盖率；规则、隐藏信息和计时关键路径要求 100% 覆盖，整体目标不低于 80%。
6. 在干净目录执行一次安装与启动冒烟测试。
7. 确认没有官方模拟器地址、密钥、访问令牌、会话存档或本地成绩被提交。

### 最终命令

```bash
python -m pytest -q
python -m pytest --cov=arena_core --cov=arena_server --cov=arena_sdk --cov=arena_leaderboard --cov-report=term-missing
python start.py --no-browser
```

## 提交顺序

1. `feat: add deterministic arena rule engine`
2. `feat: add interactive browser game`
3. `feat: add strategy runner and replay`
4. `feat: add verified GitHub leaderboard flow`
5. `docs: add setup and maintenance guide`

每个提交只包含当前阶段文件；不携带原数学建模仓库的论文、实验或结果目录。
