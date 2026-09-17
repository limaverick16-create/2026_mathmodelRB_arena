# B题机器狗竞技场

一个完全在本机运行的浏览器游戏。玩家可以代替机器狗移动、检测频道和清除辐射源，也可以把 Python 策略接进来逐步观看。人工与策略使用同一套规则引擎。

仓库地址：[limaverick16-create/2026_mathmodelRB_arena](https://github.com/limaverick16-create/2026_mathmodelRB_arena)

## 直接运行

需要 Python 3.10 或更新版本，不需要安装 Node，也没有运行时第三方依赖。

- Windows：双击 `start.bat`。
- macOS：双击 `start.command`；首次若被系统拦截，可在终端运行 `chmod +x start.command` 后再打开。
- Linux 或通用方式：在仓库目录运行 `python3 start.py`。

启动后浏览器会自动打开。游戏数据保存在本机 `data/sessions/`，刷新网页后仍能恢复当前局。程序只监听 `127.0.0.1`，不连接官方模拟器。

## 玩法入口

- 功能展示：显示真实源、接收范围和定向，用来理解规则，不进入排行榜。
- 非定向源：所有源均为非定向源的正式人工挑战。
- 有定向源：定向和非定向混合；每个源成为定向源的概率为 `6/16`，并保证至少有一个定向源。
- 策略实验室：选择本地 Python 策略，单步、连续运行、暂停、调速或在同一局切换策略。

频道列表每行只有一个选择框：勾选后显示该频道图层，同时把它加入批量检测。可以任意组合频道，也可以使用“频道全选”或“清空选择”。有信号频道显示可能区域和包围半径，无信号频道显示排除区域；功能展示中点击频道还会圈出对应的真实源位置。已清除频道隐藏旧图层，只保留清除点。地图上选定的待移动坐标只标出真实比例的 5 米圆，可用滚轮或地图上方按钮缩放查看。

获取源总数、频道存在性、精确位置或使用撤销，都会永久把本局标为“辅助局”。排行榜只接收完整、无辅助的通关局。虚拟时间按题目动作规则计算，玩家时间单独显示且不参与排名。

## 接入自己的策略

复制 `strategies/template.py`，换一个文件名并实现 `Strategy` 类。网页中点击“刷新策略列表”即可热加载，不需要重启服务或刷新浏览器。

```python
class Strategy:
    def reset(self, game_info):
        self.channel = 1

    def next_action(self, observation):
        action = {"type": "measure", "channel": self.channel}
        self.channel = self.channel % 20 + 1
        return action
```

详细字段、错误规则和调试方式见 [策略接口文档](docs/strategy-api.md)。策略在独立子进程运行，超时或异常只会暂停策略，不会关闭网页；这属于稳定性隔离，不是面向恶意代码的强安全沙箱，因此只运行你信任的本地策略。

## 排行榜

排行榜只有一个页面，包含四个分类：人工/策略 × 非定向源/有定向源。每局使用独立随机地图，按该局“总虚拟时间 ÷ 源数”排序；页面显示地图源总数，混合模式还显示定向和非定向源数。每个 GitHub 用户每类只显示自己的最好成绩。

竞技场首页同步展示人工榜和策略榜；两类地图分别切换查看，每个分类显示前 50 名并可上下滚动。页面每分钟读取一次 GitHub Pages 上的最新榜单数据。

完整无辅助通关后，点击“上传本局进入排行榜”：

1. 仓库配置了 GitHub OAuth Client ID 时，首次会打开 GitHub Device Flow；授权后程序自动创建 fork、成绩分支和 Pull Request，后续可直接提交。
2. 尚未配置时，程序下载一个简单 JSON 提交包；用户可把它放到 `submissions/<GitHub用户名>/` 后发 PR。

回放哈希和 GitHub Actions 能证明成绩可以由本仓库规则引擎重新计算。由于项目没有可信服务器，人工玩家仍可修改自己电脑上的程序，所以它不能构成不可伪造的反作弊证明。

## 开发与测试

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest --cov --cov-report=term-missing -q
```

当前规则、几何、会话、策略隔离、回放、排行榜聚合和本地 API 均有自动测试。内部实现说明见 [设计摘要](docs/design.md)。排行榜所有者设置与日常维护见 [维护指南](docs/leaderboard-maintenance.md)。
