"""调用真实委托单导入接口验证 pdfbot.call_import_api。

接口：https://online.cticert.com/test-fdd/api/Fdd/WecomOfflineImport
用法：uv run python tests/test_real_import_api.py

测试文件为脚本自生成的最小合法 .docx，不依赖本地任何真实委托单。
"""
import io
import os
import sys
import tempfile
import zipfile

# 必须在 import pdfbot 之前设置环境变量（pdfbot 在模块加载时读取）
os.environ["ANALYZE_API_URL"] = "https://online.cticert.com/test-fdd/api/Fdd/WecomOfflineImport"
os.environ["ANALYZE_API_TOKEN"] = "cti-wecom-offline-import-token-change-me-32b"

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "app"))
import pdfbot  # noqa: E402

FOLDERNO = "FDD121582026073001"
BUSRNAM = "12158"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>测试委托单（本地自动生成，仅用于接口联调）</w:t></w:r></w:p>
    <w:p><w:r><w:t>委托单号：FDD121582026073001</w:t></w:r></w:p>
  </w:body>
</w:document>"""


def build_minimal_docx(path: str):
    """生成最小合法的 .docx（zip 容器 + OOXML 必需部件）。"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr("_rels/.rels", ROOT_RELS)
        zf.writestr("word/document.xml", DOCUMENT_XML)


if __name__ == "__main__":
    docx_path = os.path.join(tempfile.gettempdir(), "pdfbot_real_api_test.docx")
    build_minimal_docx(docx_path)
    print(f"已生成测试 docx: {docx_path} ({os.path.getsize(docx_path)} bytes)")
    print(f"接口: {pdfbot.ANALYZE_API_URL}")
    print(f"单号: {FOLDERNO}")
    print(f"工号: {BUSRNAM}\n")

    try:
        result = pdfbot.call_import_api(docx_path, FOLDERNO, BUSRNAM)
        print("接口返回结果文本:")
        print(result)
        if result.startswith(pdfbot.ANALYZE_FAILED_PREFIX):
            sys.exit(1)
    except Exception as e:
        print(f"调用失败: {type(e).__name__}: {e}")
        sys.exit(1)
