"""本地 mock 委托单导入接口，用于快速测试 pdfbot。

启动方式：uv run python tests/mock_import_api.py
"""
from flask import Flask, request

app = Flask(__name__)


@app.post("/import")
def import_file():
    folderno = request.form.get("folderno")
    busrnam = request.form.get("busrnam")
    f = request.files.get("file")
    size = len(f.read()) if f else 0
    print(f"收到上传: folderno={folderno}, busrnam={busrnam}, file={f and f.filename}, size={size}")
    return {"success": True, "data": {"folderUrl": f"https://example.com/folder/{folderno}?busrnam={busrnam}"}}


if __name__ == "__main__":
    app.run(port=8000)
