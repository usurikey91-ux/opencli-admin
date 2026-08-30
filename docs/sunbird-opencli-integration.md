# 自媒体内容拆解工作台 × OpenCLI Admin 最小接口（MVP）

自媒体内容拆解工作台是主界面和内容生产系统；OpenCLI Admin 只提供对标账号巡检、公开互动数据快照和热度筛选。

## 账号绑定

`POST /api/v1/integrations/sunbird/accounts`

请求至少包含 `platform`、稳定的 `external_account_id`（抖音优先使用 `sec_uid`）。抖音未指定 `source_id` 时，系统会自动创建或复用标准 OpenCLI 数据源：`douyin user-videos <sec_uid>`，并幂等创建每 4 小时一次的巡检计划；其他平台仍需显式指定采集源。

绑定不会自动登录、上传 Cookie 或声称平台字段已验证；采集器实际拿到的字段仍以运行结果为准。工作台主界面已可直接添加监控账号并读取队列。

## 抖音公开作品字段

OpenCLI 的抖音公开作品适配器默认会返回作品 ID、标题、时长、点赞和播放地址，但部分版本没有把原始 `create_time` 及其它公开互动计数带到输出层。为了让账号自身基线和 7 天观察窗口有可验证的时间依据，部署 OpenCLI 后执行：

```bash
node scripts/patch-opencli.js
```

补丁只扩展 `douyin user-videos` 的输出字段：稳定作品 `url`、`published_at`、`comment_count`、`collect_count`、`share_count`、`play_count`；没有原始值时保持空值或 0，不会猜测数据。后续 OpenCLI 官方适配器若原生提供这些字段，可移除该补丁。

## 手动检查

`POST /api/v1/integrations/sunbird/accounts/{account_id}/check`

用于验证账号绑定和 OpenCLI 数据源是否可用。任务参数会带上 `sunbird_account_id` 和账号稳定 ID，任务完成后回写账号采集状态。

## 作品队列

- `GET /api/v1/integrations/sunbird/works`
- `GET /api/v1/integrations/sunbird/works/{work_id}`

返回工作台所需的最小契约：作品身份、链接、发布时间、当前/最终公开互动数据、相对倍数、`hot`/`very_hot` 状态、优先级和检测证据。播放量缺失时不淘汰作品；完播率不属于对标公开数据契约。

采集到新作品后，如果账号已经有 20 条历史作品，系统会先用历史作品的最新快照做一次早期筛选，达到阈值即可进入待分析队列；作品满 7 天后再用最终快照复核。早期结果会在证据中标记为 `observation_stage=early_snapshot`，不会伪装成最终结论。

## 失败状态

账号绑定和巡检状态统一使用：

`unconfigured`、`ready`、`checking`、`ok`、`account_invalid`、`login_required`、`login_expired`、`missing_metric`、`collection_failed`、`published_at_missing`。

当前错误码由采集错误文本做保守映射；真实平台返回字段验证后再细化。远程 OpenCLI 调用可通过 `OPENCLI_ADMIN_API_TOKEN` 配置 Bearer Token。
