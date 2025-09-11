
from typing import Literal
from pydantic import BaseModel

# --- 1. 定义内部内容模型 ---
class TextContent(BaseModel):
    content: str

class MarkdownContent(BaseModel):
    content: str

class StreamTextContent(BaseModel):
    id: str
    finish: bool
    content: str

# --- 2. 定义具体的消息模型 ---
# 基类，定义所有消息共有的字段
class RspMsg(BaseModel):
    # msgtype: str  # 在子类中具体定义
    pass

# 文本消息模型
class RspTextMsg(RspMsg):
    msgtype: str = "text" 
    text: TextContent

# Markdown消息模型
class RspMarkdownMsg(RspMsg):
    msgtype: str = "markdown"
    text: MarkdownContent

class RspStreamTextMsg(RspMsg):
    msgtype: str = "stream" 
    stream: StreamTextContent