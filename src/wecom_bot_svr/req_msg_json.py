# https://developer.work.weixin.qq.com/document/path/99399#%E8%A7%A3%E5%AF%86%E5%90%8E%E7%9A%84%E6%B6%88%E6%81%AF%E7%BB%93%E6%9E%84%E4%BD%93
class UserInfo(object):
    def __init__(self, en_name, cn_name, user_id):
        self.en_name = en_name
        self.cn_name = cn_name
        self.user_id = user_id

    def __str__(self):
        return f"en_name: {self.en_name}, cn_name: {self.cn_name}, user_id: {self.user_id}"


class ReqMsg(object):
    def __init__(self, json_object):
        user = json_object.get('from')
        self.from_user = UserInfo(user.get('alias'), user.get('name'), user.get('userid'))
        self.msg_type = json_object.get('msgtype')
        self.chat_type = json_object.get('chattype')
        self.chat_id = json_object.get('chatid')
        self.webhook_url = json_object.get('webhookurl')
        self.msg_id = json_object.get('msgid')
        self.aibot_id = json_object.get('aibotid')
        # GetChatInfoUrl

    @staticmethod
    def create_msg(json_object):
        msg_type = json_object.get('msgtype')
        if msg_type == 'text':
            return TextReqMsg(json_object)
        elif msg_type == 'event':
            return EventReqMsg(json_object)
        elif msg_type == 'image':
            return ImageReqMsg(json_object)
        elif msg_type == 'attachment':
            return AttachmentReqMsg(json_object)
        elif msg_type == 'mixed':
            return MixedMessageReqMsg(json_object)
        elif msg_type == 'stream':
            return StreamReqMsg(json_object)
        else:
            return None


class TextReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'text'
        self.content = json_object.get('text').get('content')


class EventReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'event'
        self.event_type = json_object.get('event').get('eventtype')
        # self.event_key = None


class ImageReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'image'
        self.image_url = json_object.get('image').get('imageurl')


class AttachmentAction(object):
    def __init__(self, name, value, type_):
        self.name = name
        self.value = value
        self.type = type_


class AttachmentReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'attachment'
        self.callback_id = json_object.get('attachment').get('callbackid')
        self.actions = []
        e = json_object.get('attachment').get('actions')
        self.actions.append(AttachmentAction(e.get('name'), e.get('value'), e.get('type')))


class SimpleTextMsg(object):
    def __init__(self, json_object):
        self.msg_type = 'text'
        self.content = json_object.get('text').get('content')


class SimpleImageMsg(object):
    def __init__(self, json_object):
        self.msg_type = 'image'
        self.image_url = json_object.get('image').get('imageurl')


class MixedMessageReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'mixed'
        self.msg_items = []
        for e in json_object.get('mixedmessage'):
            if e.get('msgtype') == 'text':
                self.msg_items.append(SimpleTextMsg(e))
            elif e.get('msgtype') == 'image':
                self.msg_items.append(SimpleImageMsg(e))
            else:
                raise Exception("unknown msg type")

class StreamReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'stream'
        self.stream_id = json_object.get('stream').get('id')