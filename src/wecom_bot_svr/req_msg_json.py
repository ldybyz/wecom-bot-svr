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
        user = json_object.get('From')
        self.from_user = UserInfo(user.get('Alias'), user.get('Name'), user.get('UserId'))
        self.msg_type = json_object.get('MsgType')
        self.chat_type = json_object.get('ChatType')
        self.chat_id = json_object.get('ChatId')
        self.webhook_url = json_object.get('WebhookUrl')
        self.msg_id = json_object.get('MsgId')
        # GetChatInfoUrl

    @staticmethod
    def create_msg(json_object):
        msg_type = json_object.get('MsgType')
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
        else:
            return None


class TextReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'text'
        self.content = json_object.get('Text').get('Content')


class EventReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'event'
        self.event_type = json_object.get('Event').get('EventType')
        # self.event_key = None


class ImageReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'image'
        self.image_url = json_object.get('Image').get('ImageUrl')


class AttachmentAction(object):
    def __init__(self, name, value, type_):
        self.name = name
        self.value = value
        self.type = type_


class AttachmentReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'attachment'
        self.callback_id = json_object.get('Attachment').get('CallbackId')
        self.actions = []
        e = json_object.get('Attachment').get('Actions')
        self.actions.append(AttachmentAction(e.get('Name'), e.get('Value'), e.get('Type')))


class SimpleTextMsg(object):
    def __init__(self, json_object):
        self.msg_type = 'text'
        self.content = json_object.get('Text').get('Content')


class SimpleImageMsg(object):
    def __init__(self, json_object):
        self.msg_type = 'image'
        self.image_url = json_object.get('Image').get('ImageUrl')


class MixedMessageReqMsg(ReqMsg):
    def __init__(self, json_object):
        super().__init__(json_object)
        self.msg_type = 'mixed'
        self.msg_items = []
        for e in json_object.get('MixedMessage'):
            if e.get('MsgType') == 'text':
                self.msg_items.append(SimpleTextMsg(e))
            elif e.get('MsgType') == 'image':
                self.msg_items.append(SimpleImageMsg(e))
            else:
                raise Exception("unknown msg type")
