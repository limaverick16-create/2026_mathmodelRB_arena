# 排行榜维护指南

## 一次性设置

1. 在 GitHub `Settings → Developer settings → OAuth Apps` 新建 OAuth App。
2. Homepage URL 填仓库或 Pages 地址；Callback URL 可同样填写 Pages 地址。
3. 勾选 **Enable Device Flow**。本地应用不需要也不应保存 Client Secret。
4. 将 `leaderboard/config.example.json` 复制为 `leaderboard/config.json`，只把 `oauth_client_id` 改为公开 Client ID，然后提交到 `main`。
5. 在仓库 `Settings → Pages` 中把 Source 设为 **GitHub Actions**。
6. 在分支保护中要求 `Validate leaderboard submission / validate` 通过，并要求维护者审核后才能合并。

Device Flow 会请求 `public_repo`，用于在用户自己的 fork 创建成绩分支并向本仓库发 PR。令牌保存在用户系统配置目录的 `BProblemArena/github-token.json`，权限在支持的系统上设置为仅当前用户可读写；它不写入克隆仓库。

## 平时如何维护

提交者点击一次按钮后，程序会创建或复用 fork、上传 `submissions/<用户名>/<成绩ID>.json` 并创建 PR。验证工作流自动检查：

- PR 恰好只修改一个提交 JSON；
- 目录与 PR 作者 GitHub 用户名一致；
- 引擎版本、类别、总时间、源数和秒/源一致；
- 回放哈希正确，且重新执行后完整通关、未标记辅助。

维护者仍需检查并合并 PR。合并后 `Publish leaderboard` 自动验证主分支全部记录、生成一个含四类页签的静态页面并部署到 Pages。因此“验证和榜单更新自动，合并决定不自动”。如果未来启用自动合并，至少保留必需检查和仅允许 `submissions/**/*.json` 的规则。

## 升级规则

修改计时、地图生成、信号或清除规则时，同时更新 `arena_core.ENGINE_VERSION`、测试和文档。旧版本提交会被新验证器拒绝；若要保留历史榜单，应按引擎版本生成独立页面，不要把不同规则成绩混排。

## 故障处理

- 页面没有更新：检查仓库 Actions 中 `Publish leaderboard`，并确认 Pages Source 为 GitHub Actions。
- 登录提示未配置：确认存在 `leaderboard/config.json`，且 Client ID 不是示例占位符。
- fork 刚创建时失败：等待几秒再次点击提交；GitHub 创建 fork 可能有延迟。
- 自动提交失败：让用户下载 JSON 包，手动放入自己 fork 的 `submissions/<用户名>/` 再发 PR。
- 撤销 GitHub 授权：在 GitHub Applications 设置中撤销，并删除本机系统配置目录中的令牌文件。

GitHub Device Flow 的端点与轮询间隔按[官方授权文档](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps)实现。
