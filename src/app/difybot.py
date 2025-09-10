import logging
import sys

from wecom_bot_svr import WecomBotServer
# from wecom_bot_svr.req_msg import TextReqMsg
from wecom_bot_svr.req_msg_json import TextReqMsg,ReqMsg
from wecom_bot_svr.rsp_msg_json import RspTextMsg, RspMarkdownMsg, TextContent, MarkdownContent

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def help_md():
    return """### Help 列表
"""


def msg_handler(req_msg: ReqMsg, server: WecomBotServer):
    # @机器人 help 打印帮助信息
    if req_msg.msg_type == 'text' and isinstance(req_msg, TextReqMsg):
        if req_msg.content.strip() == 'help':
            ret =RspMarkdownMsg(text=MarkdownContent(content= help_md()))
            # ret = RspMarkdownMsg()
            # ret.content = help_md()
            return ret
        elif req_msg.content.strip() == 'give me a file' and server is not None:
            # 生成文件、发送文件可以新启线程异步处理
            with open('output.txt', 'w') as f:
                f.write("This is a test file. Welcome to star easy-wx/wecom-bot-svr!")
            server.send_file(req_msg.chat_id, 'output.txt')
            return RspTextMsg(text=TextContent(content= ''))  # 不发送消息，只回复文件

    # 返回消息类型
    #ret = RspTextMsg()
    # ret.content = f'msg_type: {req_msg.msg_type}'
    ret =RspTextMsg(text=TextContent(content= f'msg_type: {req_msg.msg_type}'))
    return ret


def event_handler(req_msg):
    ret = RspMarkdownMsg()
    if req_msg.event_type == 'add_to_chat':  # 入群事件处理
        # ret.content = f'msg_type: {req_msg.msg_type}\n群会话ID: {req_msg.chat_id}\n查询用法请回复: help'
        ret.text.content = f'msg_type: {req_msg.msg_type}\n群会话ID: {req_msg.chat_id}\n查询用法请回复: help'
    return ret


def main():
    logging.basicConfig(stream=sys.stdout)
    logging.getLogger().setLevel(logging.INFO)

    token = os.getenv('bot_token')
    aes_key = os.getenv('bot_aes_key')
    corp_id = os.getenv('corp_id')
    host = '0.0.0.0'
    port = 5001
    bot_key = os.getenv('bot_id')  # 机器人配置中的webhook key

    # 这里要跟机器人名字一样，用于切分群组聊天中的@消息
    bot_name = os.getenv('bot_name')
    server = WecomBotServer(bot_name, host, port, path='/wecom_bot', token=token, aes_key=aes_key, corp_id=corp_id,
                            bot_key=bot_key)

    server.set_message_handler(msg_handler)
    server.set_event_handler(event_handler)
    server.run()


if __name__ == '__main__':
    main()
