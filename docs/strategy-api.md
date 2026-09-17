# Python 策略接口

## 文件约定

把一个 `.py` 文件放入仓库的 `strategies/`。文件名不能以下划线开头，文件必须提供无参数构造的 `Strategy` 类。

```python
class Strategy:
    def reset(self, game_info):
        pass

    def next_action(self, observation):
        return {"type": "measure", "channel": 1}
```

`reset` 在接入当前局时调用一次。`next_action` 每次只返回一个动作；网页的“单步”调用一次，“连续运行”则按所选速度重复调用。切换策略会重新调用新策略的 `reset`，但保留当前地图、公开信息和虚拟时间。

## `game_info`

```json
{
  "mode": "omnidirectional",
  "start": [0.0, 0.0],
  "channel_count": 20,
  "rules": {
    "target_radius_m": 1800.0,
    "move_speed_mps": 5.0,
    "clear_radius_m": 20.0
  }
}
```

## `observation`

它与人工界面的公开状态一致，包含：

- `position`、`current_channel`、`virtual_time_s`、`distance_m`；
- `cleared_count`、`completed`、`assisted`；
- 20 个 `channels`，每个含状态、检测历史和公开几何图层；
- 已执行的公开 `events`。

未获取总数信息且尚未通关时，`source_count` 为 `null`。策略永远不会收到 `truth`、源坐标、真实接收半径或真实发射方向；即使策略被接入功能展示局，这些字段也会在进入子进程前删除。

## 合法动作

```python
{"type": "move", "x": 800.0, "y": -300.0}
{"type": "measure", "channel": 7}
{"type": "clear", "channel": 7}
```

坐标必须是有限数字，频道必须是 1–20 的整数。返回其他内容、抛出异常或单步超过默认 2 秒时，策略会暂停并在界面显示错误。修改文件后点击“刷新”再“切换”即可加载新代码。

策略可以 `import` 当前 Python 环境中已有的模块。为了让其他克隆仓库的人直接运行，推荐只使用 Python 标准库；如果必须依赖第三方包，请同时更新安装文档和依赖文件。

## 接入旧式阻塞策略

如果已有策略通过同步的 `measure(point, channel)`、`clear(point, channel)` 回调运行，可以使用 `arena_sdk.BlockingPolicyAdapter`，无需把整套算法改写成 `next_action` 状态机：

```python
from arena_sdk import BlockingPolicyAdapter
from my_policy import Policy

def factory(measure, clear, game_info):
    return Policy(measure, clear)

class Strategy(BlockingPolicyAdapter):
    def __init__(self):
        super().__init__(factory)
```

适配器会把旧接口中一次“移动到目标点并检测/清除”的调用拆成可视化的 Arena 单步动作。策略依赖的模块仍需安装在启动 Arena 所使用的同一个 Python 环境中。
