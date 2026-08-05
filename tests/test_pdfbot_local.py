"""pdfbot 本地快速测试脚本：直接驱动 msg_handler，不依赖企业微信加解密。

前置：先启动 mock 导入接口  uv run python tests/mock_import_api.py
运行：uv run python tests/test_pdfbot_local.py
"""
import io
import os
import sys
import time

# Windows 控制台默认 GBK 编码，强制 stdout 使用 UTF-8，避免中文/特殊字符报错
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 必须在 import pdfbot 之前设置环境变量（pdfbot 在模块加载时读取）
os.environ["ANALYZE_API_URL"] = "http://127.0.0.1:8000/import"
os.environ["REPLY_MODE"] = "async"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "app"))
import pdfbot  # noqa: E402
from wecom_bot_svr.req_msg_json import TextReqMsg, FileReqMsg  # noqa: E402

STORAGE = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "file_storage")
)
os.makedirs(STORAGE, exist_ok=True)

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


def base_json(chat_id="test-chat"):
    return {
        "chattype": "single",
        "chatid": chat_id,
        "from": {"alias": "t", "name": "tester", "userid": "u1"},
    }


def text_msg(content, chat_id="test-chat"):
    payload = base_json(chat_id)
    payload.update({"msgtype": "text", "text": {"content": content}})
    return TextReqMsg(payload)


def file_msg(local_name, chat_id="test-chat"):
    payload = base_json(chat_id)
    payload.update({"msgtype": "file", "file": {"url": "http://unused-in-local-test"}})
    m = FileReqMsg(payload)
    m.local_file_name = local_name  # 正常流程由 app.py 下载解密后填充，本地直接指定
    return m


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


if __name__ == "__main__":
    server = FakeServer()
    print(f"file_storage: {STORAGE}\n")

    # ---- 用例 1：非法单号 ----
    rsp = pdfbot.msg_handler(text_msg("abc!!!"), server)
    check("非法单号被拒绝", rsp.text.content == pdfbot.INVALID_FOLDERNO_MSG, rsp.text.content)

    # ---- 用例 2：先发单号 → 提示发文件；再发文件 → 提交并异步推送结果 ----
    rsp = pdfbot.msg_handler(text_msg("A2260119687101"), server)
    check("先发单号返回待文件提示", "A2260119687101" in rsp.text.content, rsp.text.content)

    write_file("test1.pdf", b"%PDF-1.4 fake pdf content for test")
    rsp = pdfbot.msg_handler(file_msg("test1.pdf"), server)
    check("文件到齐后返回已收到回执", rsp.text.content == pdfbot.RECEIVED_MSG, rsp.text.content)

    wait_push(server, 1)
    check(
        "async 模式推送导入结果",
        len(server.sent) == 1 and "委托单链接" in server.sent[0][1],
        str(server.sent),
    )

    # ---- 用例 3：反向顺序，先发文件 → 提示补单号；补单号后提交 ----
    write_file("test2.pdf", b"%PDF-1.4 second pdf")
    rsp = pdfbot.msg_handler(file_msg("test2.pdf"), server)
    check("先发文件返回待单号提示", rsp.text.content == pdfbot.NEED_FOLDERNO_MSG, rsp.text.content)

    rsp = pdfbot.msg_handler(text_msg("B1234567890"), server)
    check("补单号后返回已收到回执", rsp.text.content == pdfbot.RECEIVED_MSG, rsp.text.content)

    wait_push(server, 2)
    check(
        "反向顺序也推送导入结果",
        len(server.sent) == 2 and "委托单链接" in server.sent[1][1],
        str(server.sent),
    )

    # ---- 用例 4：.bin 文件按文件头纠正为 .pdf ----
    rsp = pdfbot.msg_handler(text_msg("C1234567"), server)  # 预置单号
    write_file("test3.bin", b"%PDF-1.4 disguised as bin")
    rsp = pdfbot.msg_handler(file_msg("test3.bin"), server)
    corrected = os.path.isfile(os.path.join(STORAGE, "test3.pdf"))
    check(".bin 被识别纠正为 .pdf", rsp.text.content == pdfbot.RECEIVED_MSG and corrected)

    wait_push(server, 3)
    check("纠正扩展名后推送导入结果", len(server.sent) == 3, str(server.sent))

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

    print()
    if failures:
        print(f"共 {len(failures)} 个用例失败: {failures}")
        sys.exit(1)
    print("全部用例通过 ✓")
