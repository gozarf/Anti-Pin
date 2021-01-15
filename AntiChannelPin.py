import json
import asyncio
import logging
import traceback
import functools
import yaml
from telethon import TelegramClient, events
from telethon.errors.rpcerrorlist import MessageIdInvalidError, ChatNotModifiedError

with open('config.yaml') as file:
    config_data = yaml.safe_load(file)

api_id = config_data['1538577663:AAHnBKUAbLqU5pW1YUKVL0KXbvR6VaeAPRY']
api_hash = config_data['https://my.telegram.org']
bot_token = config_data.get('https://t.me/BotFather')

bot_admins = config_data['- Gozarff']
storage_chat = config_data.get('1231511116')
storage_msg_id = config_data.get('1366)')

logging.basicConfig(level=logging.INFO)
def is_true(string):
    string = string.lower()
    if string in ('true', 'yes', 'on', 'enable'):
        return True
    if string in ('false', 'no', 'off', 'disable'):
        return False
    raise Exception(f'Invalid boolean string: {string}')

async def main():
    client = await TelegramClient('acpbot', api_id, api_hash).start(bot_token=bot_token)
    client.parse_mode = 'html'

    try:
        if storage_chat and storage_msg_id:
            await (await client.get_messages(storage_chat, ids=storage_msg_id)).download_media('acpbot.json')
        with open('acpbot.json') as file:
            d = json.load(file)
    except Exception:
        traceback.print_exc()
        d = {'version': 0, 'chats': dict()}
        # chats dict value: {'enabled': bool, 'lastpinned': int, 'deleteservice': bool, 'deletechannel': bool}

    uploading_lock = asyncio.Lock()
    processing_lock = asyncio.Lock()
    chatinit_lock = asyncio.Lock()
    processing_chats = dict()
    async def write_d():
        with open('acpbot.json', 'w') as file:
            json.dump(d, file)
        if storage_chat and storage_msg_id and client.is_connected():
            async with uploading_lock:
                await client.edit_message(storage_chat, storage_msg_id, file='acpbot.json')

    def get_chat_data(chat_id):
        chat_id = str(chat_id)
        if chat_id not in d['chats']:
            d['chats'][chat_id] = {'enabled': False, 'lastpinned': 0, 'deleteservice': False, 'deletechannel': False}
        return d['chats'][chat_id]

    def error_dec(func):
        @functools.wraps(func)
        async def awrapper(e):
            try:
                await func(e)
            except Exception:
                to_send = traceback.format_exc()
                try:
                    await e.reply(to_send, parse_mode=None)
                except Exception:
                    logging.exception('Got an exception while sending an exception to %s', e.chat_id)
                    to_send = traceback.format_exc()
                for admin_id in bot_admins:
                    try:
                        await e.client.send_message(admin_id, to_send, parse_mode=None)
                    except Exception:
                        logging.exception('Got an exception while sending an exception to %s', admin_id)
                raise
        return awrapper

    @error_dec
    @client.on(events.NewMessage(bot_admins, pattern='/(?:start|help)'))
    async def start_or_help(e):
        await e.reply('Prepend "/acp " to your message to use Anti-Channel Pin')

    @error_dec
    @client.on(events.NewMessage(from_users=bot_admins, pattern='/acp(?:$| (?:start|help))'))
    async def acp_start_or_help(e):
        await e.reply(('/acp start - /acp help\n'
                       '/acp help - /acp start\n'
                       '/acp enable - Enables current chat\n'
                       '/acp disable - Disables current chat\n'
                       '/acp service on/off - Enable/Disable deleting service messages\n'
                       '/acp channel on/off - Enable/Disable deleting channel messages\n'))

    @error_dec
    @client.on(events.NewMessage(from_users=bot_admins, pattern=r'/acp (service|channel) ([Tt]rue|[Oo](?:n|ff)|[Yy]es|[Nn]o|(?:[Ee]n|[Dd]is)able)'))
    async def toggle_sc_setting(e):
        turn_on = is_true(e.pattern_match.group(2))
        setting = 'delete' + e.pattern_match.group(1)
        get_chat_data(e.chat_id)[setting] = turn_on
        await e.reply('Setting modified!')
        await write_d()

    @error_dec
    @client.on(events.NewMessage(from_users=bot_admins, pattern=r'/acp ([Tt]rue|[Oo](?:n|ff)|[Yy]es|[Nn]o|(?:[Ee]n|[Dd]is)able)'))
    async def toggle_enabled(e):
        enable = is_true(e.pattern_match.group(1))
        get_chat_data(e.chat_id)['enabled'] = enable
        await e.reply('Setting modified!')
        await write_d()

    @error_dec
    @client.on(events.NewMessage)
    async def handle_new_channel_message(e):
        if not (
            (e.sender_id in (1087968824, 136817688) and e.fwd_from) or
            not e.sender_id or
            e.sender_id < 0
        ):
            return
        chat_data = get_chat_data(e.chat_id)
        if not chat_data['enabled']:
            return
        async with chatinit_lock:
            if e.chat_id not in processing_chats:
                processing_chats[e.chat_id] = [asyncio.Lock(), set(), True]
        write_lock, to_delete, _ = processing_chats[e.chat_id]
        processing_chats[e.chat_id][2] = True
        to_write = False
        async with write_lock:
            if chat_data['deletechannel']:
                to_delete.add(e.id)
        await asyncio.sleep(1)
        async with write_lock, processing_lock:
            if chat_data['lastpinned'] and processing_chats[e.chat_id][2]:
                try:
                    service = await e.client.pin_message(e.chat_id, chat_data['lastpinned'])
                    if chat_data['deleteservice']:
                        to_delete.add(service.id)
                except MessageIdInvalidError:
                    chat_data['lastpinned'] = 0
                    to_write = True
                except (ChatNotModifiedError, AttributeError):
                    pass
                processing_chats[e.chat_id][2] = False
            if to_delete:
                await e.client.delete_messages(e.chat_id, list(to_delete))
                to_delete.clear()
        if to_write:
            await write_d()

    @error_dec
    @client.on(events.ChatAction)
    async def handle_new_pin_message(e):
        if not (e.new_pin or e.unpin):
            return
        get_chat_data(e.chat_id)['lastpinned'] = getattr(e.action_message, 'reply_to_msg_id', 0)
        await write_d()

    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
