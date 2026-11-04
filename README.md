# Telethon Userbot 适配器

> 这是 [outlook84/astrbot_plugin_telethon_adapter](https://github.com/outlook84/astrbot_plugin_telethon_adapter) 的修改版（GPL-2.0），配合 [Iris 活人感分支](https://github.com/Ayan0443/astrbot_plugin_iris_memory) 使用：增加发送回执、动态贴纸预览帧、致命错误看门狗、日志去正文，并修复了语音消息无法转写的问题。改动清单见 [MODIFICATIONS.md](MODIFICATIONS.md)。开箱即用请看 [Ayan0443/astrbot-lifelike-starter](https://github.com/Ayan0443/astrbot-lifelike-starter)。

为 AstrBot 增加基于 Telethon 的 Telegram Userbot 适配器。

> 重要：建议始终配合 AstrBot 的会话白名单使用本插件。如果未配置白名单，存在与其它 Bot 之间互相回复、形成消息循环的风险。

English README: [README_EN.md](README_EN.md)

## 功能

- 使用用户账户接收 Telegram 消息并回发文本与图片消息
- 基于用户账号连接 Telegram，不受非自部署 Bot API 50MB 上传限制约束
- 长文本自动按 Telegram 上限分片发送
- 支持引用回复（`Reply` 消息段）
- 提供 `tg profile` 命令，用于获取用户/群组/频道资料
- 提供 `tg status` 命令，用于查看当前 AstrBot 状态
- 提供 `tg sticker` 命令，用于把回复的图片/贴纸加入自己的贴纸包
- 提供 `tg prune` / `tg selfprune` / `tg youprune` 命令，用于批量删除消息
- 支持 `zh-CN` / `en-US` 多语言运行时回复与 WebUI 配置文案

## 注意事项

- 这是 Userbot 方案，账号风控由 Telegram 官方策略决定，账户被限制/封禁风险自负。
- `session_string` 具备 Telegram 账号完全权限，请妥善保管。
- 如果 `session_string` 失效，需要重新生成并更新配置。
- `fast_upload_enabled` 默认关闭。该功能仅对本地文件上传生效，启用后会优先走 Telethon fast upload 并行上传链路；它依赖 Telethon 私有内部接口，并会增加并发连接与资源占用，可能在 Telethon 升级、网络不稳定或账号风控较严时带来上传失败、触发限速或行为变化风险。
- `telethon_userbot` 不支持平台级流式展示；如果 AstrBot 开启了 `provider_settings.streaming_response`，请将“不支持流式回复的平台”设置为“关闭流式回复”。
- 批量删消息属于高风险操作。当前实现默认启用保守限制：所有 `prune` 命令单次最多删除 `200` 条；`selfprune` / `youprune` 最多向前扫描 `1000` 条历史；每 `100` 条删除批次之间增加节流。
- 删除权限、服务消息限制与 `FloodWait` 由 Telegram/Telethon 决定；即使命令参数正确，也可能因为会话权限或风控而部分成功或失败。

## 安装

将插件目录放置到 `AstrBot` 的 `data/plugins/` 目录下：

```
data/plugins/astrbot_plugin_telethon_adapter/
```
安装插件后，AstrBot 会自动根据 `requirements.txt` 为插件安装依赖库。

依赖里包含 `cryptg`，用于提升 Telethon 的加解密性能。
- 常见 glibc 发行版通常可以直接安装预编译 wheel。
- Alpine Linux 以及其它使用 musl 库的发行版，需要本地编译 `cryptg` 的编译环境，至少需要 `python3-dev`、`musl-dev`、`gcc`、`linux-headers`、`rust`、`cargo`。

## 生成 `session_string`

先在 [my.telegram.org](https://my.telegram.org) 申请 `api_id` 和 `api_hash`。如果无法申请到，更换代理出口 IP 地址。

`session_string` 需要通过交互授权生成。在`AstrBot` 的 `data/plugins/` 目录下运行：

```bash
python3 ./astrbot_plugin_telethon_adapter/scripts/generate_session.py
```

运行后会依次提示输入：

- `api_id`
- `api_hash`
- 手机号

然后脚本会向 Telegram 请求登录验证码，并继续要求输入：

- Telegram 登录验证码
- 二次验证密码（如果账号开启了 2FA）
- 代理信息（可选；支持 `socks5`、`socks4`、`http`、`mtproto`）

脚本最终会输出一段 `StringSession`，把它复制到 AstrBot 配置里的 `session_string` 即可。

注意：Telegram 的验证码很多时候不是短信，而是发到你已经登录的 Telegram 客户端里的官方 `Telegram` 会话。

## AstrBot 适配器配置

在 AstrBot 中新增平台适配器并选择 `telethon_userbot`，填入：

- `api_id`: Telegram API ID（整数）
- `api_hash`: Telegram API Hash
- `session_string`: 上一步得到的 StringSession
- `language`: 适配器实例语言，支持 `zh-CN` 与 `en-US`，默认 `zh-CN`
- `trigger_prefix`: 触发前缀，默认是 `-astr`。此为消息入口过滤前缀，用于减少无关消息日志和后续 AstrBot 管线调用；在本插件场景下可替代唤醒词使用。
- `reply_to_self_triggers_command`: 是否允许“回复自己”的消息触发命令，默认 `false`。仅群聊生效；开启后，回复当前 Telethon 账号发出的消息，也会视为一次唤醒继续处理。
- `download_incoming_media`: 是否下载收到的媒体文件（建议 `true`）
- `fast_upload_enabled`: 是否启用 Telethon fast upload 并行上传，默认 `false`。仅对本地文件路径上传生效；开启后会优先尝试 fast upload，条件不满足时自动回退到 Telethon 默认上传
- `telethon_media_group_timeout`: 媒体组聚合防抖延迟（秒，默认 `1.2`）
- `telethon_media_group_max_wait`: 媒体组最大等待时间（秒，默认 `8.0`）
- `proxy_type`: 代理类型，支持 `socks5`、`socks4`、`http`、`mtproto`
- `proxy_host`: 代理服务器地址
- `proxy_port`: 代理端口
- `proxy_username`: SOCKS/HTTP 代理用户名，可选
- `proxy_password`: SOCKS/HTTP 代理密码，可选
- `proxy_secret`: 仅 `mtproto` 代理需要填写

`language` 会影响：

- 运行时命令交互文案，例如 `tg profile` / `tg status` / `tg sticker` / `tg prune`

## 扩展命令

`tg profile` 用法：

```text
-astr tg profile
-astr tg profile @username
-astr tg profile https://t.me/channel_name
```

`tg profile` 的目标解析顺序如下：

- 显式参数：`@username`、数字 ID、`t.me` / `telegram.me` 链接、`me`
- 回复消息：查询被回复消息的发送者
- 私聊场景下的当前对话用户
- 群组 / 频道场景下的当前会话

`tg status` 用法：

```text
-astr tg status
```

`tg status` 会返回：

- 主机平台
- Python / AstrBot / Telethon / 插件版本
- 当前 Telegram 连接的数据中心
- 当前适配器 ID
- 系统 CPU / 内存 / Swap 占用
- 当前 AstrBot 进程 CPU / 内存占用
- 当前进程运行时长

`tg sticker` 用法：

```text
-astr tg sticker my_pack_name
-astr tg sticker
-astr tg sticker 😎
-astr tg sticker my_pack_name 😎
```

`tg sticker` 说明：

- 不回复消息时：`tg sticker <pack_name>` 用于设置当前账号的默认贴纸包名。
- 回复图片/贴纸时：`tg sticker` 会把该媒体加入默认贴纸包。
- 回复媒体时传一个参数且该参数不是合法包名时，会把它视为自定义 emoji，例如 `tg sticker 😎`。
- 回复媒体时传两个参数时，格式为 `tg sticker <pack_name> <emoji>`，会临时使用指定贴纸包和 emoji。
- 普通图片会自动缩放到 Telegram 贴纸要求的最大边 `512px`，并转换为 `webp`。
- 默认贴纸包名会保存在 AstrBot 的插件 KV 存储中，并按适配器 ID 区分多个适配器实例。

批量删除命令：

```text
-astr tg prune 20
-astr tg prune
-astr tg selfprune 20
-astr tg selfprune
-astr tg youprune @username 20
-astr tg youprune 20
```

批量删除命令说明：

- `tg prune [数量]`：删除当前会话中的最近消息；如果回复某条消息后执行，可省略数量，表示删除“回复锚点”和当前命令之间的消息；单次最多删除 `200` 条。
- `tg selfprune [数量]`：仅删除自己发出的消息；支持回复锚点模式；最多扫描最近 `1000` 条历史。
- `tg youprune [目标] [数量]`：仅删除指定用户的消息；目标支持 `@username`、`t.me` 链接、或直接回复目标消息；最多扫描最近 `1000` 条历史。
- `tg prune` / `tg selfprune` / `tg youprune` 在省略数量时，都要求当前命令是对某条消息的回复。
- 删除服务消息、无权限删除别人的消息、或命中 `FloodWait` 时，命令可能只完成部分删除。
