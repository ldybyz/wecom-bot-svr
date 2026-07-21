# 企业微信机器人回调服务

如果项目能给你带来些许便利，请不吝 Star

## 1. 介绍

本项目是一个基于 [Flask](https://flask.palletsprojects.com/) 的**企业微信机器人回调功能接口服务框架**，使用 Python 编写，发布为 `wecom-bot-svr` PyPI 包。

使用者只需实现**消息处理**和**事件处理**两个回调函数，即可快速搭建企业微信机器人回调服务，支持文本、Markdown、图片、混合消息、流式消息等多种消息类型。

实现过程参考企业微信机器人[回调功能说明文档](https://developer.work.weixin.qq.com/document/path/99399)，以及相关[加解密脚本](https://github.com/sbzhu/weworkapi_python/tree/master/callback)。

---

## 2. 项目结构

```
src/
├── wecom_bot_svr/              # 核心库（发布为 PyPI 包）
│   ├── __init__.py             # 包入口，导出核心公开类
│   ├── app.py                  # WecomBotServer 主服务类
│   ├── WXBizJsonMsgCrypt.py    # 企业微信 JSON 消息加解密实现
│   ├── ierror.py               # 加解密错误码定义
│   ├── req_msg.py              # 请求消息模型 —— XML 解析版本（兼容旧版）
│   ├── req_msg_json.py         # 请求消息模型 —— JSON 解析版本（当前默认）
│   ├── rsp_msg.py              # 响应消息模型 —— XML 格式（兼容旧版）
│   └── rsp_msg_json.py         # 响应消息模型 —— JSON/Pydantic 格式（当前默认）
├── app/                        # 示例应用：集成 Dify 大模型
│   ├── difybot.py              # Dify LLM 对话机器人完整示例
│   └── .env                    # 环境变量配置文件
└── wecom_bot_svr.egg-info/     # 包构建元信息（自动生成）
```

---

## 3. 核心库详解（`wecom_bot_svr`）

### 3.1 包入口（`__init__.py`）

导出以下公开类供外部使用：

```python
from wecom_bot_svr import WecomBotServer, RspMsg, ReqMsg, RspTextMsg, RspMarkdownMsg
```

| 导出名 | 来源 | 说明 |
|--------|------|------|
| `WecomBotServer` | `app.py` | 核心服务类 |
| `ReqMsg` | `req_msg.py` | 请求消息基类（XML 版） |
| `RspMsg` | `rsp_msg.py` | 响应消息基类（XML 版） |
| `RspTextMsg` | `rsp_msg.py` | 文本响应（XML 版） |
| `RspMarkdownMsg` | `rsp_msg.py` | Markdown 响应（XML 版） |

> 注：实际运行时框架内部默认使用 JSON 版本（`req_msg_json.py` / `rsp_msg_json.py`），业务代码应根据需要导入对应版本。

---

### 3.2 WecomBotServer 主服务类（`app.py`）

这是整个框架的核心，封装了企业微信机器人回调的完整流程。

#### 构造函数参数

```python
WecomBotServer(
    name,               # 服务名称（传入 Flask）
    host,               # 监听地址，如 "0.0.0.0"
    port,               # 监听端口，如 5001
    path,               # 回调路由路径，如 "/wecom_bot"
    token=None,         # Token，默认读环境变量 WX_BOT_TOKEN
    aes_key=None,       # AESKey，默认读环境变量 WX_BOT_AES_KEY
    corp_id=None,       # 企业 ID，默认读环境变量 WX_BOT_CORP_ID
    bot_key=None,       # Webhook Key，默认读环境变量 WX_BOT_KEY
    active_msg_path="/active_send",   # 主动发送消息的路由路径
    file_storage_dir="file_storage"   # 文件存储目录（图片解密等）
)
```

#### 公开方法一览

| 方法 | 说明 |
|------|------|
| `set_message_handler(handler)` | 注册消息处理回调函数 |
| `set_event_handler(handler)` | 注册事件处理回调函数 |
| `set_error_handler(handler)` | 注册解密错误处理回调 |
| `set_flask_error_handler(handler)` | 注册 Flask 全局异常处理 |
| `run()` | 注册路由并启动 HTTP 服务 |
| `get_crypto_obj()` | 获取加解密工具实例 |
| `upload_file(file_path)` | 上传文件到企业微信，返回 `media_id` |
| `send_file(chat_id, file_path)` | 上传并发送文件到群聊 |
| `send_text(chat_id, content, mentioned_list, mentioned_mobile_list)` | 主动发送文本消息 |
| `send_markdown(chat_id, content)` | 主动发送 Markdown 消息 |
| `send_encoded_image(chat_id, base64_image_data, md5)` | 主动发送 base64 编码图片 |
| `send_news(chat_id, title, description, url, pic_url)` | 主动发送图文消息 |
| `download_image(url)` | 下载图片到本地 `file_storage` 目录 |
| `decrypt_file(encrypted, decrypted)` | AES 解密已下载的加密文件 |
| `save_image(image_url)` | 下载 + 解密图片，返回 `(成功标志, 文件名)` |
| `remove_at_mentions(text)` | 去除文本中的 `@机器人` 内容 |
| `serve_file(filename)` | 静态文件服务路由处理函数 |

#### 路由注册

`run()` 方法启动时会自动注册以下路由：

| HTTP 方法 | 路径 | 处理函数 | 说明 |
|-----------|------|---------|------|
| GET | `{path}` | `handle_bot_call_get` | 企业微信回调 URL 验证 |
| POST | `{path}` | `handle_bot_call_post` | 接收并处理机器人消息 |
| POST | `{active_msg_path}` | `handle_active_send` | 本地主动发送消息入口 |
| GET | `{path}/{file_storage_dir}/<filename>` | `serve_file` | 静态文件访问（如解密后的图片） |

#### 消息处理流程（`handle_bot_call_post`）

1. 从 URL 参数获取 `msg_signature`、`timestamp`、`nonce`、`botid`
2. 读取请求体（加密的 JSON 数据）
3. 调用 `WXBizJsonMsgCrypt.DecryptMsg()` 解密
4. 将解密后的 JSON 通过 `ReqMsg.create_msg()` 解析为对应消息类型对象
5. 根据 `msg_type` 分发：
   - `event` → 调用 `event_handler`
   - `text`（群聊）→ 自动去除 `@机器人` 后调用 `message_handler`
   - `image` → 自动下载解密图片，设置 `local_file_name`，调用 `message_handler`
   - `mixed` → 遍历子消息项，分别处理图片和文本，调用 `message_handler`
   - 其他 → 直接调用 `message_handler`
6. 将回调函数返回的响应对象通过 `EncryptMsg()` 加密后回复

#### 主动发送消息（`handle_active_send`）

仅接受 `127.0.0.1` 的请求，支持的 `msg_type`：

| msg_type | 所需参数 | 说明 |
|----------|---------|------|
| `text` | `content` | 文本消息 |
| `markdown` | `content` | Markdown 消息 |
| `file` | `file_path` | 文件（先上传再发送） |
| `image` | `base64_image_data`, `md5` | Base64 编码图片 |
| `news` | `title`, `description`, `url`, `pic_url` | 图文消息 |

---

### 3.3 消息加解密（`WXBizJsonMsgCrypt.py`）

实现企业微信 JSON 格式消息的加解密逻辑，基于 AES-256-CBC 算法。

主要方法：
- `VerifyURL(msg_signature, timestamp, nonce, echostr)` —— 回调 URL 验证时解密 echostr
- `DecryptMsg(post_data, msg_signature, timestamp, nonce)` —— 解密接收到的消息
- `EncryptMsg(reply_msg, nonce, timestamp)` —— 加密回复消息

密钥由构造函数传入的 `aes_key` 参数经 Base64 解码后得到（32 字节），IV 取密钥前 16 字节。

### 3.4 错误码（`ierror.py`）

定义加解密过程中可能出现的错误码常量。

---

### 3.5 请求消息模型

框架同时维护了两套请求消息解析实现，当前默认使用 JSON 版本。

#### JSON 版本（`req_msg_json.py`） —— 当前默认

通过 `ReqMsg.create_msg(json_object)` 静态工厂方法，根据 `msgtype` 字段创建对应子类实例：

| 类名 | `msg_type` | 特有字段 | 说明 |
|------|-----------|---------|------|
| `TextReqMsg` | `text` | `content` | 纯文本消息 |
| `EventReqMsg` | `event` | `event_type` | 事件消息（`add_to_chat` 入群、`enter_chat` 进入会话等） |
| `ImageReqMsg` | `image` | `image_url`, `local_file_name` | 图片消息，框架自动下载解密后写入 `local_file_name` |
| `MixedMessageReqMsg` | `mixed` | `msg_items: List[SimpleTextMsg \| SimpleImageMsg]` | 图文混合消息 |
| `StreamReqMsg` | `stream` | `stream_id` | 流式消息（用于 LLM 多轮对话的分段返回） |
| `AttachmentReqMsg` | `attachment` | `callback_id`, `actions: List[AttachmentAction]` | 交互式附件消息 |

**所有消息共有的基类字段（`ReqMsg`）：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `from_user` | `UserInfo` | 发送者信息 |
| `from_user.en_name` | `str` | 英文名 |
| `from_user.cn_name` | `str` | 中文名 |
| `from_user.user_id` | `str` | 用户 ID |
| `msg_type` | `str` | 消息类型 |
| `chat_type` | `str` | 聊天类型（`single` / `group`） |
| `chat_id` | `str` | 会话 ID |
| `webhook_url` | `str` | Webhook 地址 |
| `msg_id` | `str` | 消息 ID |
| `aibot_id` | `str` | 机器人 ID |

#### XML 版本（`req_msg.py`） —— 兼容旧版

结构与 JSON 版本一致，区别在于从 XML ElementTree 中解析字段。支持的消息类型不含 `stream`。

---

### 3.6 响应消息模型

框架同样维护了两套响应消息实现，当前默认使用 JSON/Pydantic 版本。

#### JSON/Pydantic 版本（`rsp_msg_json.py`） —— 当前默认

基于 Pydantic `BaseModel`，支持 JSON 序列化：

| 类名 | `msgtype` | 内容字段 | 说明 |
|------|----------|---------|------|
| `RspTextMsg` | `"text"` | `text: TextContent` → `content: str` | 纯文本回复 |
| `RspMarkdownMsg` | `"markdown"` | `text: MarkdownContent` → `content: str` | Markdown 回复 |
| `RspStreamTextMsg` | `"stream"` | `stream: StreamTextContent` → `id: str, finish: bool, content: str` | 流式回复 |

**流式消息说明（`RspStreamTextMsg`）：**

适用于大模型（LLM）对话场景。客户端收到 `finish=False` 的响应后，会持续以 `stream` 类型请求相同 `id`，直到收到 `finish=True` 表示回答完毕。

```python
# 第一次返回：开始流式传输，content 为空
RspStreamTextMsg(stream=StreamTextContent(id="abc123", finish=False, content=""))

# 中间轮询：返回累积内容
RspStreamTextMsg(stream=StreamTextContent(id="abc123", finish=False, content="部分回答..."))

# 最终返回：完成
RspStreamTextMsg(stream=StreamTextContent(id="abc123", finish=True, content="完整回答内容"))
```

#### XML 版本（`rsp_msg.py`） —— 兼容旧版

| 类名 | `msg_type` | 内容字段 | 说明 |
|------|-----------|---------|------|
| `RspTextMsg` | `text` | `content` | 纯文本回复 |
| `RspMarkdownMsg` | `markdown` | `content` | Markdown 回复 |

通过 `dump_xml()` 方法序列化为 XML 字符串。支持 `visible_to_user` 字段控制消息可见范围。

---

## 4. 示例应用：Dify 大模型集成（`src/app/difybot.py`）

这是一个基于本框架集成 [Dify](https://dify.ai/) 平台的完整示例，展示了如何将企业微信机器人与大模型对话打通。

### 4.1 环境变量配置（`.env`）

| 变量名 | 说明 |
|--------|------|
| `bot_name` | 机器人名称（用于去除群聊 @提及） |
| `bot_id` | 机器人 Webhook Key |
| `bot_token` | 回调 Token |
| `bot_aes_key` | 回调 AESKey |
| `corp_id` | 企业 ID |
| `dify_api_url` | Dify Chat API 地址 |
| `dify_api_key` | Dify API Key |

可选变量（在代码中有默认值）：

| 变量名 | 默认值 | 说明 |
|--------|-------|------|
| `file_url_prefix` | `https://lims-dify.cticert.com/wecom_test/wecom_bot/file_storage/` | 图片文件访问 URL 前缀 |
| `default_msg` | 欢迎提示文本 | 无法识别消息时的默认回复 |
| `welcome_msg` | 欢迎提示文本 | 进入会话时的欢迎消息 |
| `default_image_msg` | `"咨询一下："` | 发送图片时附带的默认文本 |

### 4.2 核心类

#### `DifyLLM` —— Dify API 调用封装

| 方法 | 说明 |
|------|------|
| `get_dify_stream_generator(user_id, prompt)` | 同步调用 Dify API，返回流式文本生成器 |
| `invoke(user_id, question, files)` | 异步调用：启动后台线程调用 Dify 流式 API，返回 `stream_id` |
| `get_answer(stream_id)` | 查询指定 `stream_id` 的累积回答，返回 `(is_finished, answer_text)` |

异步调用使用 `threading.Thread` + `TTLCache`（10 分钟过期，最大 1024 条）实现线程安全的流式结果存储。

#### `LLMDemo` —— 本地模拟大模型（调试用）

模拟 LLM 的分步回答行为，通过文件缓存实现，`MAX_STEPS=10` 步后结束。仅用于开发调试。

### 4.3 消息处理逻辑（`msg_handler`）

```
收到消息
├── text（文本消息）
│   └── 调用 DifyLLM.invoke() 发起异步对话
│   └── 返回 RspStreamTextMsg(finish=False) 开始流式传输
├── stream（流式轮询）
│   └── 调用 DifyLLM.get_answer(stream_id) 获取累积回答
│   └── 返回 RspStreamTextMsg(finish=是否完成)
├── image（图片消息）
│   └── 构造远程图片 URL → 调用 DifyLLM.invoke() 带图片参数
│   └── 返回 RspStreamTextMsg(finish=False)
├── mixed（混合消息）
│   └── 遍历子消息，拼接文本、收集图片 URL
│   └── 调用 DifyLLM.invoke() 带文本+图片
│   └── 返回 RspStreamTextMsg(finish=False)
└── 其他类型
    └── 返回"不支持的消息类型"
```

### 4.4 事件处理逻辑（`event_handler`）

| 事件类型 | 处理 |
|---------|------|
| `add_to_chat` | 回复群 ID 和帮助信息 |
| `enter_chat` | 回复欢迎消息（`welcome_msg`） |
| 其他 | 回复事件类型名称 |

### 4.5 启动入口（`main`）

```python
server = WecomBotServer(
    bot_name, "0.0.0.0", 5001,
    path="/wecom_bot",
    token=token, aes_key=aes_key, corp_id=corp_id,
    bot_key=bot_key,
    active_msg_path="/active_send",
    file_storage_dir="file_storage"
)
server.set_message_handler(msg_handler)
server.set_event_handler(event_handler)
server.run()
```

---

## 5. 快速开始

### 5.1 安装

```bash
pip install wecom-bot-svr
```

### 5.2 最小示例

```python
from wecom_bot_svr import WecomBotServer
from wecom_bot_svr.req_msg_json import ReqMsg, TextReqMsg
from wecom_bot_svr.rsp_msg_json import RspTextMsg, TextContent

def msg_handler(req_msg, server):
    if req_msg.msg_type == 'text':
        return RspTextMsg(text=TextContent(content=f"你说的是：{req_msg.content}"))
    return RspTextMsg(text=TextContent(content="暂不支持该消息类型"))

def event_handler(req_msg):
    return RspTextMsg(text=TextContent(content=f"收到事件：{req_msg.event_type}"))

server = WecomBotServer(
    name="my_bot", host="0.0.0.0", port=5001,
    path="/wecom_bot",
    token="你的Token", aes_key="你的AESKey",
    corp_id="你的CorpID", bot_key="你的Webhook Key"
)
server.set_message_handler(msg_handler)
server.set_event_handler(event_handler)
server.run()
```

### 5.3 环境变量方式

Token 和 AESKey 等敏感信息可通过环境变量传入（框架自动读取）：

| 环境变量 | 说明 |
|---------|------|
| `WX_BOT_TOKEN` | 机器人回调配置的 Token |
| `WX_BOT_AES_KEY` | 机器人回调配置的 AESKey |
| `WX_BOT_CORP_ID` | 企业 ID |
| `WX_BOT_KEY` | 机器人 Webhook Key（用于主动发送消息） |

---

## 6. 功能详解

### 6.1 消息处理函数签名

框架自动识别参数个数，兼容两种签名：

```python
# 新版本：可获取 server 实例
def msg_handler(req_msg: ReqMsg, server: WecomBotServer):
    server.send_file(req_msg.chat_id, 'output.txt')
    ...

# 兼容旧版本
def msg_handler(req_msg: ReqMsg):
    ...
```

### 6.2 发送文件

```python
def msg_handler(req_msg, server):
    server.send_file(req_msg.chat_id, 'output.txt')
    return RspTextMsg(text=TextContent(content="文件已发送"))
```

需要构造时传入 `bot_key`。Webhook Key 可在机器人配置页面获取：

![webhook_key](images/webhook_key.png)

### 6.3 主动发送消息

通过本地 `/active_send` 端点触发，仅接受 `127.0.0.1` 请求：

```python
import requests

url = "http://127.0.0.1:5001/active_send"

# 文本
requests.post(url, data={"msg_type": "text", "chat_id": "群ID", "content": "你好"})
# Markdown
requests.post(url, data={"msg_type": "markdown", "chat_id": "群ID", "content": "**加粗**"})
# 文件
requests.post(url, data={"msg_type": "file", "chat_id": "群ID", "file_path": "/path/file"})
# 图片
requests.post(url, data={"msg_type": "image", "chat_id": "群ID", "base64_image_data": "...", "md5": "..."})
# 图文
requests.post(url, data={"msg_type": "news", "chat_id": "群ID", "title": "标题", "description": "描述", "url": "https://...", "pic_url": "https://..."})
```

`chat_id` 为个人 ID 或群聊 ID。

![active_send](images/active_send.png)

### 6.4 图片消息处理

框架自动完成以下流程：
1. 接收图片消息中的加密 URL
2. 下载加密图片数据
3. 使用 AES-256-CBC 解密（密钥同回调加解密）
4. 保存到 `file_storage` 目录，文件名写入 `req_msg.local_file_name`
5. 通过静态文件路由 `{path}/file_storage/<filename>` 提供访问

### 6.5 流式消息（LLM 对话场景）

`RspStreamTextMsg` 实现分段返回，适用于大模型生成时间较长的场景。企业微信客户端会自动轮询同一 `stream_id`，直到 `finish=True`。

---

## 7. Docker 部署

```bash
cd demo
docker build -t your-registry/wecom-bot-svr .
docker push your-registry/wecom-bot-svr
```

---

## 8. 配置企业微信群机器人

1. 打开群聊 → 右上角「...」→「添加群机器人」→「接收消息配置」
2. 填入回调地址、Token、AESKey

<img src="images/new_wecom_bot.png" alt="new_wecom_bot" style="zoom:33%;" />

3. 保存成功后在群中发送消息即可触发回调
4. 点击「发布到公司」后可被其他同事搜索和添加

<img src="images/publish_wecom_bot.png" alt="publish_wecom_bot" style="zoom:50%;" />

---

## 9. 依赖

- Python >= 3.8
- Flask >= 3.0.0
- requests >= 2.32.3
- pycryptodome >= 3.23.0
- pydantic >= 2.10.6
- cachetools >= 5.5.2

## 10. TODO

- 增加默认权限支持

## 11. Star History

[![Star History Chart](https://api.star-history.com/svg?repos=easy-wx/wecom-bot-svr&type=Date)](https://star-history.com/#easy-wx/wecom-bot-svr&Date)
