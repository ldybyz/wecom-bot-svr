import logging
import os
import re
import sys
import threading
import uuid
import zipfile

import requests
from cachetools import TTLCache
from dotenv import load_dotenv

from wecom_bot_svr import WecomBotServer
from wecom_bot_svr.req_msg_json import FileReqMsg, ReqMsg, TextReqMsg
from wecom_bot_svr.rsp_msg_json import (
    RspTextMsg,
    TextContent,
    RspStreamTextMsg,
    StreamTextContent,
)

load_dotenv()

UNSUPPORTED_MSG = "不支持该消息类型"
RECEIVED_MSG = "已收到文件，正在导入解析，请稍候…"
WELCOME_MSG = (
    "请发送 .pdf、.docx 或 .xlsx 委托单文件（≤ 50MB）并告知委托单单号（如 FDD121582026073001）。\n"
    "顺序不限：可以先发单号再发文件，也可以先发文件再补单号。"
)
ANALYZE_FAILED_PREFIX = "导入失败："
NEED_FOLDERNO_MSG = "已收到文件，请再发送一条文本消息告知委托单单号（如 FDD121582026073001）"
NEED_FILE_MSG = "已记录委托单单号：{folderno}，请发送 .pdf、.docx 或 .xlsx 文件（≤ 50MB）"
FILE_TOO_LARGE_MSG = "文件超过 {limit}MB 限制，请压缩后重新发送"
INVALID_FOLDERNO_MSG = "单号格式不正确，应为字母和数字的组合（如 FDD121582026073001），请重新发送"

ANALYZE_API_URL = os.getenv("ANALYZE_API_URL", "")
ANALYZE_API_FILE_FIELD = os.getenv("ANALYZE_API_FILE_FIELD", "file")
ANALYZE_API_FOLDERNO_FIELD = os.getenv("ANALYZE_API_FOLDERNO_FIELD", "folderno")
ANALYZE_API_TOKEN = os.getenv("ANALYZE_API_TOKEN", "")
ANALYZE_RESULT_KEY = os.getenv("ANALYZE_RESULT_KEY", "")
ANALYZE_TIMEOUT = int(os.getenv("ANALYZE_TIMEOUT", "120"))
# 导入接口侧 WAF 会拦截非浏览器 UA（如默认的 python-requests），这里默认伪装为浏览器
ANALYZE_API_USER_AGENT = os.getenv(
    "ANALYZE_API_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
)
MAX_FILE_SIZE_MB = int(os.getenv("ANALYZE_MAX_FILE_SIZE_MB", "50"))
ALLOWED_EXTENSIONS = (".pdf", ".docx", ".xlsx")
# 单号为字母和数字的组合，如 FDD121582026073001
FOLDERNO_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9]{5,31}$")
# stream：被动流式回复（官方推荐，支持长任务，difybot 同款）；async：response_url 主动推送
_REPLY_MODE_RAW = os.getenv("REPLY_MODE", "stream").strip().lower()
REPLY_MODE = _REPLY_MODE_RAW if _REPLY_MODE_RAW in ("async", "stream") else "stream"

store_lock = threading.Lock()
conversations_store = TTLCache(maxsize=1024, ttl=600)
# 会话级"半成品"状态：{"folderno": str, "file_path": str}，等待另一要素到齐后提交
pending_store = TTLCache(maxsize=1024, ttl=600)


def detect_real_ext(local_path: str):
    """根据文件头识别真实类型。企业微信文件消息不携带原始文件名（参见
    https://developer.work.weixin.qq.com/document/path/100719），落盘扩展名可能为 .bin。"""
    try:
        with open(local_path, "rb") as f:
            header = f.read(4)
    except OSError:
        return None
    if header == b"%PDF":
        return ".pdf"
    if header == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(local_path) as zf:
                names = zf.namelist()
            if any(n.startswith("word/") for n in names):
                return ".docx"
            if any(n.startswith("xl/") for n in names):
                return ".xlsx"
        except zipfile.BadZipFile:
            pass
    return None


def is_supported_file(local_path: str) -> bool:
    """仅接受 .pdf / .docx / .xlsx：优先按文件头识别，其次按扩展名兜底。"""
    if not (local_path and os.path.isfile(local_path)):
        return False
    if detect_real_ext(local_path) in ALLOWED_EXTENSIONS:
        return True
    return local_path.lower().endswith(ALLOWED_EXTENSIONS)


def is_file_too_large(local_path: str) -> bool:
    try:
        return os.path.getsize(local_path) > MAX_FILE_SIZE_MB * 1024 * 1024
    except OSError:
        return True


def is_valid_folderno(text: str) -> bool:
    """校验单号格式：字母和数字的组合，如 FDD121582026073001。"""
    return bool(FOLDERNO_PATTERN.fullmatch(text))


def _extract_result_text(response: requests.Response) -> str:
    """从导入接口响应中提取结果文本：成功返回 data.folderUrl，失败返回 msg。"""
    try:
        data = response.json()
    except ValueError:
        text = (response.text or "").strip()
        return text if text else "处理完成，但未返回内容"

    if isinstance(data, str):
        return data

    if not isinstance(data, dict):
        return str(data)

    success = data.get("success", True)
    status = data.get("status")
    if success is False or (isinstance(status, int) and status >= 400):
        return f"{ANALYZE_FAILED_PREFIX}{data.get('msg') or f'接口返回异常(status={status})'}"

    payload = data.get("data")
    if isinstance(payload, dict):
        # 兼容两种返回风格：folderUrl（驼峰）/ folderurl（全小写）
        folder_url = payload.get("folderUrl") or payload.get("folderurl")
        if folder_url:
            return f"解析完成，委托单链接：{folder_url}"
        inner_status = payload.get("status")
        if inner_status and inner_status != "Succeeded":
            return f"{ANALYZE_FAILED_PREFIX}解析状态：{inner_status}"

    if ANALYZE_RESULT_KEY and ANALYZE_RESULT_KEY in data:
        return str(data[ANALYZE_RESULT_KEY])

    for key in ("result", "message", "data", "content", "summary"):
        if key in data and data[key] is not None:
            return str(data[key])

    return str(data)


def call_import_api(file_path: str, folderno: str) -> str:
    """multipart 上传本地文件 + folderno 到导入接口，返回结果文本。"""
    if not ANALYZE_API_URL:
        raise ValueError("未配置 ANALYZE_API_URL")

    headers = {"User-Agent": ANALYZE_API_USER_AGENT}
    if ANALYZE_API_TOKEN:
        headers["Authorization"] = f"Bearer {ANALYZE_API_TOKEN}"

    filename = os.path.basename(file_path)
    mime_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    mime = mime_map.get(os.path.splitext(filename)[1].lower(), "application/octet-stream")
    with open(file_path, "rb") as f:
        response = requests.post(
            ANALYZE_API_URL,
            data={ANALYZE_API_FOLDERNO_FIELD: folderno},
            files={ANALYZE_API_FILE_FIELD: (filename, f, mime)},
            headers=headers,
            timeout=ANALYZE_TIMEOUT,
        )

    response.raise_for_status()
    return _extract_result_text(response)


def _resolve_chat_id(req_msg: ReqMsg) -> str:
    return req_msg.chat_id or (req_msg.from_user.user_id if req_msg.from_user else "")


def _resolve_webhook_url(req_msg: ReqMsg) -> str:
    return getattr(req_msg, "webhook_url", None) or ""


def _resolve_response_url(req_msg: ReqMsg) -> str:
    """智能机器人回调携带的主动回复临时url：每条消息仅可调用一次，有效期1小时。"""
    return getattr(req_msg, "response_url", None) or ""


def _post_text(url: str, content: str, channel: str) -> bool:
    """向指定 url POST 文本消息（response_url / webhook_url 报文格式一致），
    返回是否推送成功，失败时记录日志。"""
    try:
        resp = requests.post(
            url,
            json={"msgtype": "text", "text": {"content": content}},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") == 0:
            logging.info("推送成功(%s)", channel)
            return True
        logging.error("推送失败(%s)，企业微信返回: %s", channel, data)
        return False
    except Exception:
        logging.exception("推送异常(%s)", channel)
        return False


def _push_text(
    server: WecomBotServer, response_url: str, webhook_url: str, chat_id: str, content: str
):
    """推送结果文本：优先用当前消息携带的 response_url（智能机器人主动回复，
    单聊/群聊均可），失败或不可用时依次回退 webhook_url、全局 webhook key，
    并记录日志，绝不静默。"""
    if response_url and _post_text(response_url, content, "response_url"):
        return
    if webhook_url and _post_text(webhook_url, content, "webhook_url"):
        return
    if not chat_id:
        logging.error("推送失败：response_url/webhook_url/chat_id 均不可用，内容: %s", content)
        return
    result = server.send_text(chat_id, content)
    logging.info("推送结果(全局webhook): %s", result)


def _reply_text(req_msg: ReqMsg, content: str):
    """回复提示类文本。官方文档（101031 被动回复）：接收消息回调不支持被动回复文本，
    但支持被动回复流式消息：
    - stream 模式：直接以 finish=True 的流式消息回复（无需轮询）
    - async 模式：通过消息携带的 response_url（101138 主动回复）推送；
      无 response_url 时才退回同步文本回复"""
    if REPLY_MODE == "stream":
        return RspStreamTextMsg(
            stream=StreamTextContent(id=str(uuid.uuid4()), finish=True, content=content)
        )
    response_url = _resolve_response_url(req_msg)
    if response_url:
        threading.Thread(
            target=_post_text, args=(response_url, content, "response_url"), daemon=True
        ).start()
        return RspTextMsg(text=TextContent(content=""))
    return RspTextMsg(text=TextContent(content=content))


def _resolve_local_path(server: WecomBotServer, local_file_name: str) -> str:
    return os.path.join(server.file_storage_path, local_file_name)


def _run_import_and_store(stream_id: str, file_path: str, folderno: str):
    with store_lock:
        conversations_store[stream_id] = {"status": "processing", "response": "正在导入解析，请稍候…"}

    try:
        result = call_import_api(file_path, folderno)
    except Exception as e:
        logging.exception("委托单导入失败")
        result = f"{ANALYZE_FAILED_PREFIX}{e}"
    logging.info("导入结果: %s", result)
    with store_lock:
        conversations_store[stream_id] = {"status": "finished", "response": result}


def _run_import_and_push(
    server: WecomBotServer,
    response_url: str,
    webhook_url: str,
    chat_id: str,
    file_path: str,
    folderno: str,
):
    try:
        result = call_import_api(file_path, folderno)
    except Exception as e:
        logging.exception("委托单导入失败")
        result = f"{ANALYZE_FAILED_PREFIX}{e}"
    logging.info("导入结果: %s", result)
    _push_text(server, response_url, webhook_url, chat_id, result)


def _submit(server: WecomBotServer, req_msg: ReqMsg, session_key: str, folderno: str, file_path: str):
    """单号与文件两要素齐全，清除待办并按 REPLY_MODE 提交。"""
    with store_lock:
        pending_store.pop(session_key, None)

    if REPLY_MODE == "stream":
        stream_id = str(uuid.uuid4())
        threading.Thread(
            target=_run_import_and_store,
            args=(stream_id, file_path, folderno),
            daemon=True,
        ).start()
        return RspStreamTextMsg(
            stream=StreamTextContent(id=stream_id, finish=False, content=RECEIVED_MSG)
        )

    # async 模式：后台导入后主动推送结果。response_url 每条消息仅可调用一次，
    # 需留给最终结果，故不再另发同步回执，直接返回空响应
    chat_id = _resolve_chat_id(req_msg)
    response_url = _resolve_response_url(req_msg)
    webhook_url = _resolve_webhook_url(req_msg)
    if not chat_id and not response_url and not webhook_url:
        return RspTextMsg(
            text=TextContent(content=f"{ANALYZE_FAILED_PREFIX}无法确定会话目标")
        )
    threading.Thread(
        target=_run_import_and_push,
        args=(server, response_url, webhook_url, chat_id, file_path, folderno),
        daemon=True,
    ).start()
    return RspTextMsg(text=TextContent(content=""))


def _unsupported(req_msg: ReqMsg = None):
    if req_msg is not None:
        return _reply_text(req_msg, UNSUPPORTED_MSG)
    return RspTextMsg(text=TextContent(content=UNSUPPORTED_MSG))


def _handle_text(req_msg: TextReqMsg, server: WecomBotServer):
    """文本消息视为 folderno：校验格式后，若已暂存文件则立即提交，否则先记下单号。"""
    folderno = (req_msg.content or "").strip()
    if not folderno:
        return _unsupported(req_msg)
    if not is_valid_folderno(folderno):
        return _reply_text(req_msg, INVALID_FOLDERNO_MSG)

    session_key = _resolve_chat_id(req_msg)
    with store_lock:
        pending = dict(pending_store.get(session_key, {}))
    file_path = pending.get("file_path")
    if file_path and os.path.isfile(file_path):
        return _submit(server, req_msg, session_key, folderno, file_path)

    with store_lock:
        pending_store[session_key] = {**pending, "folderno": folderno}
    return _reply_text(req_msg, NEED_FILE_MSG.format(folderno=folderno))


def _handle_file(req_msg: FileReqMsg, server: WecomBotServer):
    """文件消息：若已记下单号则立即提交，否则暂存文件并提示补单号。"""
    if not req_msg.local_file_name:
        return _reply_text(req_msg, f"{ANALYZE_FAILED_PREFIX}文件下载或解密失败")

    local_path = _resolve_local_path(server, req_msg.local_file_name)
    if not is_supported_file(local_path):
        return _unsupported(req_msg)
    if is_file_too_large(local_path):
        return _reply_text(req_msg, FILE_TOO_LARGE_MSG.format(limit=MAX_FILE_SIZE_MB))

    # 落盘文件可能为 .bin，按文件头纠正扩展名，保证上传导入接口时文件名/MIME 正确
    real_ext = detect_real_ext(local_path)
    if real_ext and not local_path.lower().endswith(real_ext):
        new_path = os.path.splitext(local_path)[0] + real_ext
        try:
            os.replace(local_path, new_path)
            local_path = new_path
        except OSError:
            logging.warning("纠正文件扩展名失败: %s", local_path)

    session_key = _resolve_chat_id(req_msg)
    with store_lock:
        pending = dict(pending_store.get(session_key, {}))
    folderno = pending.get("folderno")
    if folderno:
        return _submit(server, req_msg, session_key, folderno, local_path)

    with store_lock:
        pending_store[session_key] = {**pending, "file_path": local_path}
    return _reply_text(req_msg, NEED_FOLDERNO_MSG)


def msg_handler(req_msg: ReqMsg, server: WecomBotServer):
    try:
        return _msg_handler_impl(req_msg, server)
    except Exception as e:
        logging.exception("消息处理异常")
        return _reply_text(req_msg, f"处理消息时发生异常：{e}")


def _msg_handler_impl(req_msg: ReqMsg, server: WecomBotServer):
    # 流式轮询
    if req_msg.msg_type == "stream":
        if REPLY_MODE != "stream":
            return _unsupported()
        stream_id = req_msg.stream_id
        with store_lock:
            item = conversations_store.get(stream_id)
        if item is None:
            return RspStreamTextMsg(
                stream=StreamTextContent(
                    id=stream_id, finish=True, content=f"{ANALYZE_FAILED_PREFIX}任务不存在或已过期"
                )
            )
        finished = item.get("status") == "finished"
        return RspStreamTextMsg(
            stream=StreamTextContent(
                id=stream_id,
                finish=finished,
                content=item.get("response") or "",
            )
        )

    if req_msg.msg_type == "text" and isinstance(req_msg, TextReqMsg):
        return _handle_text(req_msg, server)

    if req_msg.msg_type == "file" and isinstance(req_msg, FileReqMsg):
        return _handle_file(req_msg, server)

    return _unsupported()


def event_handler(req_msg):
    if req_msg.event_type == "enter_chat":
        return RspTextMsg(text=TextContent(content=WELCOME_MSG))
    if req_msg.event_type == "add_to_chat":
        return RspTextMsg(
            text=TextContent(content=f"已加入群聊。群会话ID: {req_msg.chat_id}\n{WELCOME_MSG}")
        )
    return RspTextMsg(text=TextContent(content=WELCOME_MSG))


def main():
    logging.basicConfig(stream=sys.stdout)
    logging.getLogger().setLevel(logging.INFO)

    if not ANALYZE_API_URL:
        logging.warning("ANALYZE_API_URL 未配置，收到文件后将无法调用导入接口")

    if _REPLY_MODE_RAW not in ("async", "stream"):
        logging.warning("REPLY_MODE=%s 无效，已回退为 stream", _REPLY_MODE_RAW)

    token = os.getenv("bot_token")
    aes_key = os.getenv("bot_aes_key")
    corp_id = os.getenv("corp_id")
    host = "0.0.0.0"
    port = int(os.getenv("port", "5001"))
    bot_key = os.getenv("bot_id")
    bot_name = os.getenv("bot_name")

    server = WecomBotServer(
        bot_name,
        host,
        port,
        path="/wecom_bot",
        token=token,
        aes_key=aes_key,
        corp_id=corp_id,
        bot_key=bot_key,
        active_msg_path="/active_send",
        file_storage_dir="file_storage",
    )
    server.set_message_handler(msg_handler)
    server.set_event_handler(event_handler)
    server.run()


if __name__ == "__main__":
    main()
