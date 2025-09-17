import inspect
import logging
import os
import xml.etree.cElementTree as ET

import requests
from flask import Flask, request,send_from_directory 
from .WXBizJsonMsgCrypt import WXBizJsonMsgCrypt
# from .req_msg import ReqMsg
from .req_msg_json import ReqMsg
import json
from pydantic import BaseModel, Field, TypeAdapter
from urllib.parse import urlparse, parse_qs, unquote
import uuid
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad


# 参考文档：https://km.woa.com/articles/show/387107?kmref=search&from_page=1&no=2#10128


def _encode_rsp(wx_cpt, rsp_str):
    xml = ET.Element('xml')
    ET.SubElement(xml, 'MsgType').text = 'markdown'
    markdown = ET.SubElement(xml, 'Markdown')
    ET.SubElement(markdown, 'Content').text = rsp_str
    plain = ET.tostring(xml).decode()

    # 加密消息
    params = request.args
    timestamp = params.get("timestamp")
    nonce = params.get("nonce")
    ret, rsp = wx_cpt.EncryptMsg(plain, nonce, timestamp)
    if ret != 0:
        print("err: encrypt fail: " + str(ret))
    return rsp


class WecomBotServer(object):
    def __init__(self, name, host, port, path, token=None, aes_key=None, corp_id=None, bot_key=None,
                 active_msg_path="/active_send",file_storage_dir="file_storage"):
        """
        :param name:
        :param host:
        :param port:
        :param path:
        :param token:
        :param aes_key:
        :param corp_id:
        :param bot_key:
        :param active_msg_path: 主动发送消息的路径
        """
        self.host = host
        self.port = port
        self.path = path
        self.active_msg_path = active_msg_path
        self._bot_key = bot_key if bot_key is not None else os.getenv("WX_BOT_KEY")
        self._token = token if token is not None else os.getenv("WX_BOT_TOKEN")
        self._aes_key = aes_key if aes_key is not None else os.getenv("WX_BOT_AES_KEY")
        self._corp_id = corp_id if corp_id is not None else os.getenv("WX_BOT_CORP_ID", default="")
        self._app = Flask(name)
        self._message_handler = None
        self._event_handler = None
        self._error_handler = None
        self.name = name
        self.logger = logging.getLogger()
        self.file_storage_dir = file_storage_dir

        self.file_storage_path = os.path.abspath(self.file_storage_dir)
        os.makedirs(self.file_storage_path, exist_ok=True)

    def set_message_handler(self, handler):
        self._message_handler = handler

    def set_event_handler(self, handler):
        self._event_handler = handler

    def set_error_handler(self, handler):
        self._error_handler = handler

    def set_flask_error_handler(self, handler):
        self._app.errorhandler(Exception)(handler)

    def run(self):
        if self._message_handler is None:
            raise Exception("message handler is not set")
        if self._event_handler is None:
            raise Exception("event handler is not set")
        self._app.get(self.path)(self.handle_bot_call_get)
        self._app.post(self.path)(self.handle_bot_call_post)
        self._app.post(self.active_msg_path)(self.handle_active_send)
        self._app.get(f"{self.path}/{self.file_storage_dir}/<path:filename>")(self.serve_file)
        self._app.run(host=self.host, port=self.port)

    def handle_active_send(self):
        # 避免外网直接访问：判断来源IP如果非本地地址，直接返回
        if request.remote_addr != "127.0.0.1":
            return "Invalid request"

        # 获取请求参数
        params = request.values
        msg_type = params.get("msg_type")
        chat_id = params.get("chat_id")
        if msg_type == "file":
            file_path = params.get("file_path")
            send_ret = self.send_file(chat_id, file_path)
        elif msg_type == "markdown":
            content = params.get("content")
            send_ret = self.send_markdown(chat_id, content)
        elif msg_type == "text":
            content = params.get("content")
            send_ret = self.send_text(chat_id, content)
        elif msg_type == "image":
            base64_image_data = params.get("base64_image_data")
            md5 = params.get("md5")
            send_ret = self.send_encoded_image(chat_id, base64_image_data, md5)
        elif msg_type == "news":
            title = params.get("title")
            description = params.get("description")
            url = params.get("url")
            pic_url = params.get("pic_url")
            send_ret = self.send_news(chat_id, title, description, url, pic_url)
        else:
            return "Invalid msg_type"

        return "发送消息结果：" + send_ret

    def get_crypto_obj(self):
        return WXBizJsonMsgCrypt(self._token, self._aes_key, self._corp_id)

    def handle_bot_call_get(self):
        # 获取请求参数
        params = request.args
        msg_signature = params.get("msg_signature")
        timestamp = params.get("timestamp")
        nonce = params.get("nonce")
        encrypted_echo_str = params.get("echostr")
        wx_cpt = self.get_crypto_obj()
        ret, decrypted_echo_str = wx_cpt.VerifyURL(msg_signature, timestamp, nonce, encrypted_echo_str)
        if ret != 0:
            print("err: encrypt fail: " + str(ret))
            return None
        return decrypted_echo_str

    def handle_bot_call_post(self):
        # 获取请求参数
        params = request.args
        msg_signature = params.get("msg_signature")
        timestamp = params.get("timestamp")
        nonce = params.get("nonce")
        botid = params.get("botid")
        wx_cpt = self.get_crypto_obj()

        data_as_string = request.get_data().decode('utf-8')

        print(f"@收到消息，botid={botid}, msg_signature={msg_signature}, timestamp={timestamp}, nonce={nonce},body={data_as_string}")
        # 解密出明文的echostr
        ret, msg = wx_cpt.DecryptMsg(data_as_string, msg_signature, timestamp, nonce)
        if ret != 0:
            print("err: encrypt fail: " + str(ret))
            print("err: encrypt fail,data= " + data_as_string)
            if self._error_handler:
                self._error_handler(ret)
            else:
                return None
            
        # 解密后的数据是xml格式，用python的标准库xml.etree.cElementTree可以解析
        # xml_tree = ET.fromstring(msg)
        json_object = json.loads(msg)
        msg = ReqMsg.create_msg(json_object)
        if msg.msg_type == 'event':
            rsp_msg = self._event_handler(msg)
        else:  # 消息
            if msg.msg_type == 'text' and msg.chat_type == 'group':
                msg.content = msg.content.replace(f"@{self.name}", "")

            # 图片消息类型
            if msg.msg_type == 'image':
                #local_file_name = self.download_image(msg.image_url)
                #decrypt_file_name = f"decrypt_{local_file_name}"
                #decrypt_filed = self.decrypt_file(local_file_name, decrypt_file_name)

                decrypt_filed,decrypt_file_name = self.save_image(msg.image_url)
                if decrypt_filed:
                    msg.local_file_name = decrypt_file_name
                    print("local_file_name:" +  msg.local_file_name)
                else:
                    print("下载图片失败:" + msg.image_url)

            # 混合消息类型
            if msg.msg_type == 'mixed':
                for item in msg.msg_items:
                    if item.msg_type == 'image':
                        # local_file_name = self.download_image(item.image_url)
                        # decrypt_file_name = f"decrypt_{local_file_name}"
                        #decrypt_filed = self.decrypt_file(local_file_name, decrypt_file_name)
                        decrypt_filed,decrypt_file_name = self.save_image(item.image_url)
                        if decrypt_filed:
                            item.local_file_name = decrypt_file_name
                            print("local_file_name:" +  item.local_file_name)
                        else:
                            print("下载图片失败:" + item.image_url)

            if len(inspect.signature(self._message_handler).parameters) == 2:
                rsp_msg = self._message_handler(msg, self)
            else:  # 兼容旧版本
                rsp_msg = self._message_handler(msg)

        nonce = params.get("nonce")

        # ret, rsp = wx_cpt.EncryptMsg(rsp_msg.dump_xml(), nonce, timestamp)
        ret, rsp = wx_cpt.EncryptMsg(rsp_msg.model_dump_json(indent=2), nonce, timestamp)
        if ret != 0:
            print("err: encrypt fail: " + str(ret))
        print("rsp: " + rsp)
        return rsp

    def upload_file(self, file_path):
        filename = os.path.basename(file_path)
        try:
            # 打开文件并上传
            with open(file_path, 'rb') as file:
                files = {'file': (filename, file)}
                response = requests.post(
                    url=f'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={self._bot_key}&type=file',
                    files=files)
                # 检查响应
                if response.status_code != 200 and response.json().get("errcode") == 0:
                    return None
                return response.json()['media_id']
        except:
            return None

    def proactively_send(self, chat_id, msg_type, msg_type_name, msg_data):
        """"""
        try:
            payload = {
                "chatid": chat_id,
                "msgtype": msg_type,
            }
            payload.update(msg_data)

            r = requests.post(url=f'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={self._bot_key}',
                              json=payload)
            if r.status_code == 200 and r.json().get("errcode") == 0:
                return f"发送{msg_type_name}成功"
            else:
                return f"发送{msg_type_name}失败"
        except:
            return f"发送{msg_type_name}失败"

    def send_file(self, chat_id, file_path):
        media_id = self.upload_file(file_path)
        if media_id is None:
            return "上传文件失败"

        return self.proactively_send(chat_id, "file", "文件", {"file": {"media_id": media_id}})

    def send_markdown(self, chat_id, content):
        return self.proactively_send(chat_id, "markdown", "Markdown", {"markdown": {"content": content}})

    def send_text(self, chat_id, content, mentioned_list=None, mentioned_mobile_list=None):
        msg_data = {
            "text": {
                "content": content,
            }
        }
        if mentioned_list is not None:
            msg_data["text"]["mentioned_list"] = mentioned_list
        if mentioned_mobile_list is not None:
            msg_data["text"]["mentioned_mobile_list"] = mentioned_mobile_list
        return self.proactively_send(chat_id, "text", "文本", msg_data)

    def send_encoded_image(self, chat_id, base64_image_data, md5):
        return self.proactively_send(chat_id, "image", "图片", {"image": {"base64": base64_image_data, "md5": md5}})

    def send_news(self, chat_id, title, description, url, pic_url):
        return self.proactively_send(chat_id, "news", "图文", {"news": {"articles": [
            {
                "title": title,
                "description": description,
                "url": url,
                "picurl": pic_url
            }
        ]}})

    def serve_file(self, filename):
        self.logger.info(f"Attempting to serve file: {filename} from {self.file_storage_dir}")
        try:
            # 使用 send_from_directory 来安全地提供文件，它能防止目录遍历攻击
            return send_from_directory(self.file_storage_dir, filename)
        except Exception as e:
            self.logger.error(f"Error serving file {filename}: {e}")
            return "File not found", 404
        
    def download_image(self, url):
        try:
            # 从URL中解析出文件名
            parsed_url = urlparse(url)
            file_name = os.path.basename(parsed_url.path)
            if not file_name:
                # 如果URL路径中没有文件名，则使用一个默认名称或基于URL生成
                file_name = f"{str(uuid.uuid4())}.jpg"
            else: 
                file_name = f"{str(uuid.uuid4())}_{file_name}"
            save_path = os.path.join(self.file_storage_path, file_name)

            # 发送请求
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, stream=True, timeout=60)
            
            # 检查响应状态
            response.raise_for_status()  # 如果状态码不是200-299，会抛出HTTPError异常

            # 写入文件
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"图片成功下载到: {save_path}")
            return file_name

        except requests.exceptions.RequestException as e:
            print(f"下载失败: {e}")
            return None
        except Exception as e:
            print(f"发生未知错误: {e}")
            return None


    def decrypt_file(self,encrypted_file_name, decrypted_file_name):
        encrypted_file_path = os.path.join(self.file_storage_path, encrypted_file_name)
        decrypted_file_path = os.path.join(self.file_storage_path, decrypted_file_name)
        wx_cpt = self.get_crypto_obj()
        key = wx_cpt.key
        iv =  key[:16]
        # ... (代码同上) ...
        # 确保 key 是32字节，iv 是16字节
        if len(key) != 32:
            print("错误: 密钥长度必须是 32 字节。")
            return False
        if len(iv) != 16:
            print("错误: IV 长度必须是 16 字节。")
            return False
        try:
            # 1. 以二进制模式读取加密文件
            with open(encrypted_file_path, 'rb') as f_in:
                ciphertext = f_in.read()

            # 2. 创建 AES 密码器
            cipher = AES.new(key, AES.MODE_CBC, iv)

            # 3. 解密数据
            decrypted_data_padded = cipher.decrypt(ciphertext)
            
            # 4. 去除填充 (Padding)
            decrypted_data = unpad(decrypted_data_padded, AES.block_size)
            
            # 5. 将解密后的数据写入新文件
            with open(decrypted_file_path, 'wb') as f_out:
                f_out.write(decrypted_data)
            
            print(f"文件成功解密并保存到: {decrypted_file_path}")
            return True

        except ValueError as e:
            print(f"解密失败: {e}. 请检查密钥、IV和文件完整性。")
            return False
        except FileNotFoundError:
            print(f"错误: 加密文件未找到于 {encrypted_file_path}")
            return False
        except Exception as e:
            print(f"发生未知错误: {e}")
            return False

    def save_image(self,image_url):
        try:
            parsed_url = urlparse(image_url)
            file_name = os.path.basename(parsed_url.path)
            if not file_name:
                # 如果URL路径中没有文件名，则使用一个默认名称或基于URL生成
                file_name = f"{str(uuid.uuid4())}.jpg"
            else: 
                file_name = f"{str(uuid.uuid4())}_{file_name}"
            save_path = os.path.join(self.file_storage_path, file_name)
            # 1. 下载加密图片
            print(f"开始下载加密图片:{image_url}", )
            response = requests.get(image_url, timeout=60)
            response.raise_for_status()
            encrypted_data = response.content

            wx_cpt = self.get_crypto_obj()
            aes_key = wx_cpt.key
            if not aes_key:
                raise ValueError("AES密钥不能为空")
            
            if len(aes_key) != 32:
                raise ValueError("无效的AES密钥长度: 应为32字节")
                
            iv = aes_key[:16]  # 初始向量为密钥前16字节
            
            # 3. 解密图片数据
            cipher = AES.new(aes_key, AES.MODE_CBC, iv)
            decrypted_data = cipher.decrypt(encrypted_data)
            
            # 4. 去除PKCS#7填充 (Python 3兼容写法)
            pad_len = decrypted_data[-1]  # 直接获取最后一个字节的整数值
            if pad_len > 32:  # AES-256块大小为32字节
                raise ValueError("无效的填充长度 (大于32字节)")
                
            decrypted_data = decrypted_data[:-pad_len]
            
            # 5. 将解密后的数据写入新文件
            with open(save_path, 'wb') as f_out:
                f_out.write(decrypted_data)
            
            print(f"文件成功解密并保存到: {save_path}")
            return True, file_name
            
        except requests.exceptions.RequestException as e:
            error_msg = f"图片下载失败 : {str(e)}"
            print(error_msg)
            return False, error_msg
            
        except ValueError as e:
            error_msg = f"参数错误 : {str(e)}"
            print(error_msg)
            return False, error_msg
            
        except Exception as e:
            error_msg = f"图片处理异常 : {str(e)}"
            print(error_msg)
            return False, error_msg