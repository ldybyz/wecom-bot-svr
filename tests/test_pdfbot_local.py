"""pdfbot 本地快速测试脚本：直接驱动 msg_handler，不依赖企业微信加解密。

前置：先启动 mock 导入接口  uv run python tests/mock_import_api.py
运行：uv run python tests/test_pdfbot_local.py
"""
import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# Windows 控制台默认 GBK 编码，强制 stdout 使用 UTF-8，避免中文/特殊字符报错
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 必须在 import pdfbot 之前设置环境变量（pdfbot 在模块加载时读取）
os.environ["ANALYZE_API_URL"] = "http://127.0.0.1:8000/import"
# 前半部分用例验证 async 模式；用例 7 会在运行中切换到 stream 模式（代码默认模式）
os.environ["REPLY_MODE"] = "async"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "app"))
import pdfbot  # noqa: E402
from wecom_bot_svr.req_msg_json import TextReqMsg, FileReqMsg, StreamReqMsg  # noqa: E402

STORAGE = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file_storage")
)
os.makedirs(STORAGE, exist_ok=True)

# 模拟企业微信 response_url 主动回复接口，记录收到的推送内容
RESPONSE_URL = "http://127.0.0.1:9100/aibot/response"
response_url_received = []


class _ResponseUrlHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        response_url_received.append(body.get("text", {}).get("content", ""))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"errcode": 0}')

    def log_message(self, *args):
        pass


_httpd = HTTPServer(("127.0.0.1", 9100), _ResponseUrlHandler)
threading.Thread(target=_httpd.serve_forever, daemon=True).start()

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
failures = []


class FakeServer:
    def __init__(self):
        self.file_storage_path = STORAGE
        self.sent = []

    def send_text(self, chat_id, content):
        self.sent.append((chat_id, content))
        print(f"  [主动推送] {chat_id}: {content}")
        return "ok"


def base_json(chat_id="test-chat", response_url=None):
    payload = {
        "chattype": "single",
        "chatid": chat_id,
        "from": {"alias": "t", "name": "tester", "userid": "u1"},
    }
    if response_url:
        payload["response_url"] = response_url
    return payload


def text_msg(content, chat_id="test-chat", response_url=None):
    payload = base_json(chat_id, response_url)
    payload.update({"msgtype": "text", "text": {"content": content}})
    return TextReqMsg(payload)


def file_msg(local_name, chat_id="test-chat", response_url=None):
    payload = base_json(chat_id, response_url)
    payload.update({"msgtype": "file", "file": {"url": "http://unused-in-local-test"}})
    m = FileReqMsg(payload)
    m.local_file_name = local_name  # 正常流程由 app.py 下载解密后填充，本地直接指定
    return m


def stream_msg(stream_id, chat_id="test-chat"):
    payload = base_json(chat_id)
    payload.update({"msgtype": "stream", "stream": {"id": stream_id}})
    return StreamReqMsg(payload)


def check(name, cond, detail=""):
    print(f"[{PASS if cond else FAIL}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def write_file(name, data):
    path = os.path.join(STORAGE, name)
    with open(path, "wb") as f:
        f.write(data)
    return name


def wait_push(server, expect_count, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline and len(server.sent) < expect_count:
        time.sleep(0.2)


def wait_response_url_push(expect_count, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline and len(response_url_received) < expect_count:
        time.sleep(0.2)


def last_push():
    return response_url_received[-1] if response_url_received else ""


if __name__ == "__main__":
    server = FakeServer()
    print(f"file_storage: {STORAGE}\n")

    # ---- 用例 1：文本未含单号/工号 → 仍接受请求，回复携带 userid（工号回退用）----
    rsp = pdfbot.msg_handler(text_msg("abc!!!"), server)
    check(
        "未识别到要素仍接受且回复携带 userid",
        "u1" in rsp.text.content and "请发送" in rsp.text.content,
        rsp.text.content,
    )

    # ---- 用例 2：先发单号 → 提示发文件；再发文件 → 提交并异步推送结果 ----
    rsp = pdfbot.msg_handler(text_msg("A2260119687101", response_url=RESPONSE_URL), server)
    check("先发单号同步回复为空", rsp.text.content == "", rsp.text.content)
    wait_response_url_push(1)
    check(
        "待发文件提示经 response_url 推送",
        len(response_url_received) == 1 and "A2260119687101" in last_push(),
        str(response_url_received),
    )

    write_file("test1.pdf", b"%PDF-1.4 fake pdf content for test")
    rsp = pdfbot.msg_handler(file_msg("test1.pdf"), server)
    check("文件到齐后同步回执为空(留给response_url)", rsp.text.content == "", rsp.text.content)

    wait_push(server, 1)
    check(
        "async 模式推送导入结果",
        len(server.sent) == 1 and "委托单链接" in server.sent[0][1],
        str(server.sent),
    )

    # ---- 用例 3：反向顺序，先发文件 → 提示补文本；补文本后提交 ----
    write_file("test2.pdf", b"%PDF-1.4 second pdf")
    rsp = pdfbot.msg_handler(file_msg("test2.pdf"), server)
    check("先发文件返回待文本提示", rsp.text.content == pdfbot.NEED_TEXT_MSG, rsp.text.content)

    rsp = pdfbot.msg_handler(text_msg("B1234567890"), server)
    check("补单号后同步回执为空", rsp.text.content == "", rsp.text.content)

    wait_push(server, 2)
    check(
        "反向顺序也推送导入结果",
        len(server.sent) == 2 and "委托单链接" in server.sent[1][1],
        str(server.sent),
    )

    # ---- 用例 3b：文件先到且携带 response_url，补单号提示经 response_url 推送 ----
    write_file("test6.pdf", b"%PDF-1.4 prompt via response_url")
    rsp = pdfbot.msg_handler(file_msg("test6.pdf", response_url=RESPONSE_URL), server)
    check("暂存文件时同步回复为空", rsp.text.content == "", rsp.text.content)
    wait_response_url_push(2)
    check(
        "补单号提示经 response_url 推送",
        len(response_url_received) == 2 and "单号" in last_push(),
        str(response_url_received),
    )
    rsp = pdfbot.msg_handler(text_msg("D7654321", response_url=RESPONSE_URL), server)
    check("补单号提交后同步回执为空", rsp.text.content == "", rsp.text.content)
    wait_response_url_push(3)
    check(
        "该会话导入结果也经 response_url 推送",
        len(response_url_received) == 3 and "委托单链接" in last_push()
        and len(server.sent) == 2,
        str(response_url_received),
    )

    # ---- 用例 4：.bin 文件按文件头纠正为 .pdf，且结果经 response_url 推送 ----
    rsp = pdfbot.msg_handler(text_msg("C1234567"), server)  # 预置单号
    write_file("test3.bin", b"%PDF-1.4 disguised as bin")
    rsp = pdfbot.msg_handler(file_msg("test3.bin", response_url=RESPONSE_URL), server)
    corrected = os.path.isfile(os.path.join(STORAGE, "test3.pdf"))
    check(".bin 被识别纠正为 .pdf", rsp.text.content == "" and corrected)

    wait_response_url_push(4)
    check(
        "结果经 response_url 推送",
        len(response_url_received) == 4 and "委托单链接" in last_push()
        and len(server.sent) == 2,  # 未走全局 webhook 回退路径
        str(response_url_received),
    )

    # ---- 用例 5：不支持的文件类型 ----
    write_file("test4.txt", b"plain text, not allowed")
    rsp = pdfbot.msg_handler(file_msg("test4.txt"), server)
    check("非 pdf/docx 文件被拒绝", rsp.text.content == pdfbot.UNSUPPORTED_MSG, rsp.text.content)

    # ---- 用例 6：超过大小限制 ----
    pdfbot.MAX_FILE_SIZE_MB = 0
    write_file("test5.pdf", b"%PDF-1.4 size limit check")
    rsp = pdfbot.msg_handler(file_msg("test5.pdf"), server)
    check("超过大小上限被拒绝", "超过" in rsp.text.content, rsp.text.content)
    pdfbot.MAX_FILE_SIZE_MB = 50

    # ---- 用例 7：stream 模式（被动流式回复，difybot 同款，长任务推荐，代码默认模式）----
    pdfbot.REPLY_MODE = "stream"
    rsp = pdfbot.msg_handler(text_msg("E9876543"), server)
    check(
        "stream 模式提示以已完成流式消息返回",
        rsp.msgtype == "stream" and rsp.stream.finish is True and "E9876543" in rsp.stream.content,
        str(rsp),
    )

    write_file("test7.pdf", b"%PDF-1.4 stream mode test")
    rsp = pdfbot.msg_handler(file_msg("test7.pdf"), server)
    check(
        "stream 模式提交返回未结束流式消息",
        rsp.msgtype == "stream" and rsp.stream.finish is False and bool(rsp.stream.id)
        and rsp.stream.content == pdfbot.RECEIVED_MSG,
        str(rsp),
    )

    sid = rsp.stream.id
    deadline = time.time() + 5
    poll_rsp = None
    while time.time() < deadline:
        poll_rsp = pdfbot.msg_handler(stream_msg(sid), server)
        if poll_rsp.stream.finish:
            break
        time.sleep(0.2)
    check(
        "stream 轮询最终返回导入结果",
        poll_rsp is not None and poll_rsp.stream.finish and "委托单链接" in poll_rsp.stream.content,
        str(poll_rsp),
    )
    pdfbot.REPLY_MODE = "async"

    # ---- 用例 8：文本同时含单号与工号 → 提取工号并随导入接口提交 ----
    rsp = pdfbot.msg_handler(text_msg("委托单 FDD121582026073001，工号 12345"), server)
    check(
        "同时提取单号与工号",
        "FDD121582026073001" in rsp.text.content and "工号：12345" in rsp.text.content
        and "u1" not in rsp.text.content,
        rsp.text.content,
    )
    write_file("test8.pdf", b"%PDF-1.4 busrnam extract test")
    rsp = pdfbot.msg_handler(file_msg("test8.pdf"), server)
    wait_push(server, 3)
    check(
        "提取的工号随导入接口提交",
        len(server.sent) == 3 and "busrnam=12345" in server.sent[2][1],
        str(server.sent),
    )

    # ---- 用例 9：文本仅含工号、无单号 → 接受请求，folderno 缺省提交 ----
    rsp = pdfbot.msg_handler(text_msg("工号123456"), server)
    check(
        "仅工号也接受且不带 userid 回退说明",
        "工号：123456" in rsp.text.content and "u1" not in rsp.text.content,
        rsp.text.content,
    )
    write_file("test9.pdf", b"%PDF-1.4 no folderno test")
    rsp = pdfbot.msg_handler(file_msg("test9.pdf"), server)
    wait_push(server, 4)
    check(
        "缺省单号仍可导入且工号正确",
        len(server.sent) == 4 and "委托单链接" in server.sent[3][1]
        and "busrnam=123456" in server.sent[3][1],
        str(server.sent),
    )

    # ---- 用例 10：文本提取不到单号与工号 → 接受请求，工号回退为 userid 提交 ----
    rsp = pdfbot.msg_handler(text_msg("你好，请帮忙导入"), server)
    check("未识别到要素时回复携带 userid", "u1" in rsp.text.content, rsp.text.content)
    write_file("test10.pdf", b"%PDF-1.4 fallback userid test")
    rsp = pdfbot.msg_handler(file_msg("test10.pdf"), server)
    wait_push(server, 5)
    check(
        "工号回退为 userid 提交",
        len(server.sent) == 5 and "busrnam=u1" in server.sent[4][1],
        str(server.sent),
    )

    print()
    if failures:
        print(f"共 {len(failures)} 个用例失败: {failures}")
        sys.exit(1)
    print("全部用例通过 ✓")
