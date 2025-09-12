import logging
import sys

from wecom_bot_svr import WecomBotServer
# from wecom_bot_svr.req_msg import TextReqMsg
from wecom_bot_svr.req_msg_json import TextReqMsg,ReqMsg
from wecom_bot_svr.rsp_msg_json import RspTextMsg, RspMarkdownMsg, TextContent, MarkdownContent, RspStreamTextMsg, StreamTextContent

import os
from dotenv import load_dotenv

import string
import random
import json
import time
import requests
import threading

# 加载环境变量
load_dotenv()

# 常量定义
CACHE_DIR = "/tmp/llm_demo_cache"
MAX_STEPS = 10
ongoing_streams = {}

DIFY_API_KEY = os.getenv('dify_api_key')
DIFY_API_URL = os.getenv('dify_api_url')
store_lock = threading.Lock()

conversations_store = {}

def run_dify_stream_and_store(conversation_id: str, query: str, user_id: str):
    """
    这个函数在独立的后台线程中运行。
    它调用Dify的流式API，并线程安全地将累加结果存入 conversations_store。
    """

    # 初始化存储
    with store_lock:
        conversations_store[conversation_id] = {"status": "processing", "response": ""}

    DIFY_API_KEY = os.getenv('dify_api_key')
    DIFY_API_URL = os.getenv('dify_api_url')
    headers = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "inputs": {},
        "query": query,
        "user": user_id,
        "response_mode": "streaming",
    }

    try:
        response = requests.post(DIFY_API_URL, headers=headers, json=payload, stream=True)
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data:'):
                    try:
                        data = json.loads(decoded_line[5:])
                        if data['event'] == 'message':
                            with store_lock:
                                conversations_store[conversation_id]["response"] += data['answer']
                    except (json.JSONDecodeError, KeyError):
                        continue
        # Dify流结束，更新最终状态
        with store_lock:
            conversations_store[conversation_id]["status"] = "completed"

    except Exception as e:
        print(f"An error occurred in Dify stream for {conversation_id}: {e}")
        with store_lock:
            conversations_store[conversation_id]["status"] = "error"
            conversations_store[conversation_id]["response"] = f"An error occurred: {e}"

# TODO 这里模拟一个大模型的行为
class LLMDemo():
    def __init__(self):
        self.cache_dir = CACHE_DIR
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def invoke(self, question):
        stream_id = _generate_random_string(10) # 生成一个随机字符串作为任务ID
        # 创建任务缓存文件
        cache_file = os.path.join(self.cache_dir, "%s.json" % stream_id)
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({
                'question': question,
                'created_time': time.time(),
                'current_step': 0,
                'max_steps': MAX_STEPS
            }, f)
        return stream_id

    def get_answer(self, stream_id):
        cache_file = os.path.join(self.cache_dir, "%s.json" % stream_id)
        if not os.path.exists(cache_file):
            return u"任务不存在或已过期"
            
        with open(cache_file, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        # 更新缓存
        current_step = task_data['current_step'] + 1
        task_data['current_step'] = current_step
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(task_data, f)
            
        response = u'收到问题：%s\n' % task_data['question']
        for i in range(current_step):
            response += u'处理步骤 %d: 已完成\n' % (i)

        return response

    def is_task_finish(self, stream_id):
        cache_file = os.path.join(self.cache_dir, "%s.json" % stream_id)
        if not os.path.exists(cache_file):
            return True
            
        with open(cache_file, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
            
        return task_data['current_step'] >= task_data['max_steps']

class DifyLLM():
    def __init__(self):
        self.cache_dir = CACHE_DIR
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def get_dify_stream_generator(self,wecom_user_id, prompt):
        """调用 Dify API 并返回一个流式响应的生成器对象"""
        DIFY_API_KEY = os.getenv('dify_api_key')
        DIFY_API_URL = os.getenv('dify_api_url')
        headers = {"Authorization": f"Bearer {DIFY_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "inputs": {},
            "query": prompt,
            "user": wecom_user_id,
            "response_mode": "streaming",
        }
        response = requests.post(DIFY_API_URL, headers=headers, json=payload, stream=True)
        response.raise_for_status()

        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                if decoded_line.startswith('data:'):
                    try:
                        data = json.loads(decoded_line[5:])
                        if data['event'] == 'message':
                            yield data['answer']
                    except (json.JSONDecodeError, KeyError):
                        continue

    
    def invoke(self, user_id, question):
        stream_id = _generate_random_string(10) # 生成一个随机字符串作为任务ID
        # 创建并启动后台线程
        thread = threading.Thread(
            target=run_dify_stream_and_store,
            args=(stream_id, question, user_id)
        )
        thread.daemon = True  # 允许主程序退出而无需等待此线程结束
        thread.start()
        return stream_id

    def get_answer(self, stream_id):

        with store_lock:
            task_data = conversations_store.get(stream_id)

        if not task_data:
            return True,"任务不存在或已过期"
        answer = task_data["response"]
        status = task_data["status"]
        finish = status == "completed" or status == "error"
        return finish,answer

    def is_task_finish(self, stream_id):
        cache_file = os.path.join(self.cache_dir, "%s.json" % stream_id)
        if not os.path.exists(cache_file):
            return True
            
        with open(cache_file, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
            
        return task_data['current_step'] >= task_data['max_steps']
def help_md():
    return """### Help 列表
"""

def _generate_random_string(length):
    letters = string.ascii_letters + string.digits
    return ''.join(random.choice(letters) for _ in range(length))

def msg_handler(req_msg: ReqMsg, server: WecomBotServer):
    # @机器人 help 打印帮助信息
    ret = None
    if req_msg.msg_type == 'text' and isinstance(req_msg, TextReqMsg):
        content = req_msg.content.strip()
        # 询问大模型产生回复
        llm = DifyLLM()
        stream_id = llm.invoke(req_msg.from_user.user_id,content)
        # finish,answer = llm.get_answer(stream_id)
        ret = RspStreamTextMsg(stream=StreamTextContent(id=stream_id, finish=False, content=""))

    elif (req_msg.msg_type == 'stream'): 
        stream_id = req_msg.stream_id
        llm = DifyLLM()
        finish,answer = llm.get_answer(stream_id)
        ret = RspStreamTextMsg(stream=StreamTextContent(id=stream_id, finish=finish, content=answer))
    else:
        stream_id = _generate_random_string(10)
        ret = RspStreamTextMsg(stream=StreamTextContent(id=stream_id, finish=True, content="不支持的消息类型"))
    return ret


def event_handler(req_msg):
    if req_msg.event_type == 'add_to_chat':  # 入群事件处理
        # ret.content = f'msg_type: {req_msg.msg_type}\n群会话ID: {req_msg.chat_id}\n查询用法请回复: help'
        return RspTextMsg(text=TextContent(content= f'msg_type: {req_msg.msg_type}\n群会话ID: {req_msg.chat_id}\n查询用法请回复: help')) 
    return RspTextMsg(text=TextContent(content= req_msg.event_type))


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
