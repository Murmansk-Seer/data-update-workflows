# data-update-workflows

赛尔号静态数据更新入口。工作流每 30 分钟检查一次淘米资源包；只有输入版本变化时才更新：

1. `Murmansk-Seer/seer-unity-assets`
2. `Murmansk-Seer/config-sources`
3. `Murmansk-Seer/api-data`（通过 `repository_dispatch` 触发）

## 必需 Secret

仓库 Actions Secret `PAT` 必须能够读取和写入上述组织仓库，并允许触发 Actions。普通仓库
`GITHUB_TOKEN` 只能写当前仓库，不能代替跨仓库令牌。

## 手动触发

- `force-update-assets`：强制重新提取 ConfigPackage 和 DefaultPackage。
- `force-update-config`：强制重新生成 `config-sources`。
- `dispatch-api-data`：更新配置后是否异步触发 `api-data`；IronsBot 的串行
  `/更新数据` 流水线会设为 `false`，随后自行等待 `api-data` 构建完成。
