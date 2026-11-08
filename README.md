# data-update-workflows

赛尔号静态数据更新入口。工作流每 30 分钟检查一次淘米资源包；素材按包版本更新，配置同时核对解析器来源和导出完整性；无变化不提交：

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

## Parser refresh polling / 解析器补导出轮询

After successful checks and successful or skipped asset jobs, every normal poll
enters the configuration updater. The updater owns the final no-op decision:
configuration version, immutable parser SHA, Somua version and all 27 required
files must agree. Asset-version checks are advisory and cannot suppress a
parser-only refresh. Failed/cancelled prerequisite jobs and chip-icons-only
recovery still prevent configuration work. API dispatch remains gated by an
actual successful source commit; unchanged polling makes no commit or dispatch.

检查成功且素材任务成功或跳过后，每次普通轮询都会进入配置更新器。更新器统一
决定是否跳过：配置版本、不可变解析器 SHA、苏摩版本和全部27份必需文件须一致。
素材版本预检不能拦住仅解析器升级所需的补导出。前置失败／取消及仅图标恢复仍
阻止配置任务。API 派发仍仅由实际成功的配置提交触发；无变化轮询不提交、不派发。

This local correction does not run or publish a production workflow. Frozen
parser/model dependencies and all source export contracts remain unchanged.

本地修正不启动或发布生产工作流，固定解析器／模型依赖及全部配置导出契约不变。
