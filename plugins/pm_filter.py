import asyncio
import re
import ast
import math
from pyrogram.errors.exceptions.bad_request_400 import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from Script import script
import pyrogram
from database.connections_mdb import active_connection, all_connections, delete_connection, if_active, make_active, \
    make_inactive
from info import *
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid
from utils import get_size, is_subscribed, get_poster, search_gagala, temp, get_settings, save_group_settings
from database.users_chats_db import db
from database.ia_filterdb import Media, get_file_details, get_search_results
from database.filters_mdb import (
    del_all,
    find_filter,
    get_filters,
)
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

BUTTONS = {}
SPELL_CHECK = {}
FILTER_MODE = {}

@Client.on_message(filters.command('autofilter'))
async def set_autofilter_mode(client, message): 
    mode_on = ["yes", "on", "true"]
    mode_off = ["no", "off", "false"]

    try: 
        args = message.text.split(None, 1)[1].lower() 
    except IndexError: 
        return await message.reply("**Invalid command format. Usage: /autofilter on OR /autofilter off**")
    
    m = await message.reply("**Setting up.../**")

    if args in mode_on:
        FILTER_MODE[str(message.chat.id)] = "True" 
        await m.edit("**Autofilter enabled**")
    
    elif args in mode_off:
        FILTER_MODE[str(message.chat.id)] = "False"
        await m.edit("**Autofilter disabled**")
    
    else:
        await m.edit("USE: /autofilter on OR /autofilter off")


@Client.on_message((filters.group | filters.private) & filters.text & filters.incoming)
async def handle_filter(client, message):
    is_manual_filter = await manual_filters(client, message)
    if not is_manual_filter:
        await auto_filter(client, message)


@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    ident, user_id, key, offset = query.data.split("_")
    
    try:
        user_id, offset = int(user_id), int(offset)
    except ValueError:
        user_id, offset = 0, 0

    if user_id not in [query.from_user.id, 0]:
        return await query.answer("Invalid user ID", show_alert=True)

    search = BUTTONS.get(key)
    if not search:
        await query.answer("You are using one of my old messages, please send the request again.", show_alert=True)
        return

    files, n_offset, total = await get_search_results(search, offset=offset, filter=True)
    
    try:
        n_offset = int(n_offset)
    except ValueError:
        n_offset = 0

    if not files:
        return

    settings = await get_settings(query.message.chat.id)
    
    btn = []
    for file in files:
        if settings['button']:
            btn.append([
                InlineKeyboardButton(
                    text=f"[{get_size(file.file_size)}]-💠-{file.file_name}", callback_data=f'files#{file.file_id}'
                ),
            ])
        else:
            btn.append([
                InlineKeyboardButton(
                    text=f"{file.file_name}", callback_data=f'files#{file.file_id}'
                ),
                InlineKeyboardButton(
                    text=f"{get_size(file.file_size)}",
                    callback_data=f'files_#{file.file_id}',
                ),
            ])

    off_set = None if offset == 0 else max(0, offset - 10)
    
    btn.append([
        InlineKeyboardButton("⏪ Back", callback_data=f"next_{user_id}_{key}_{off_set}"),
        InlineKeyboardButton(f"📃 Pages {math.ceil(int(offset) / 10) + 1} / {math.ceil(total / 10)}",
                             callback_data="pages")
    ]) if n_offset == 0 else btn.append([
        InlineKeyboardButton(f"🗓 {math.ceil(int(offset) / 10) + 1} / {math.ceil(total / 10)}", callback_data="pages"),
        InlineKeyboardButton("Next ➡️", callback_data=f"next_{user_id}_{key}_{n_offset}")
    ]) if off_set is None else btn.append([
        InlineKeyboardButton("⏪ Back", callback_data=f"next_{user_id}_{key}_{off_set}"),
        InlineKeyboardButton(f"🗓 {math.ceil(int(offset) / 10) + 1} / {math.ceil(total / 10)}", callback_data="pages"),
        InlineKeyboardButton("Next ➡️", callback_data=f"next_{user_id}_{key}_{n_offset}")
    ])

    try:
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(btn))
    except MessageNotModified:
        pass

    await query.answer()


@Client.on_callback_query(filters.regex(r"^spolling"))
async def advantage_spoll_choker(bot, query):
    _, user_id, movie_id = query.data.split('#')

    try:
        user_id, movie_id = int(user_id), int(movie_id)
    except ValueError:
        user_id, movie_id = 0, 0

    if user_id != 0 and query.from_user.id != user_id:
        return await query.answer("😁 Hey Friend, Please Search Yourself.", show_alert=True)

    if movie_id == "close_spellcheck":
        return await query.message.delete()

    movies = SPELL_CHECK.get(query.message.reply_to_message.id)
    if not movies:
        return await query.answer("Linked Expired Kindly Please Search Again 🙂.", show_alert=True)

    movie = movies.get(movie_id)
    if not movie:
        return await query.answer("Invalid Movie Selection.", show_alert=True)

    await query.answer('Checking File On Database...//')
    k = await manual_filters(bot, query.message, text=movie)

    if not k:
        files, offset, total_results = await get_search_results(movie, offset=0, filter=True)

        if files:
            k = (movie, files, offset, total_results)
            await auto_filter(bot, query, k)
        else:
            k = await query.message.edit('This Movie is Not Yet Released or Added to Databases 💌')
            await asyncio.sleep(10)
            await k.delete()


@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    if query.data == CLOSE_DATA_ACTION:
        await query.message.delete()
    elif query.data == DELETE_ALL_CONFIRM_ACTION:
        await handle_delete_all_confirm(client, query)
    elif query.data == DELETE_ALL_CANCEL_ACTION:
        await handle_delete_all_cancel(query)

async def handle_delete_all_confirm(client, query):
    userid = query.from_user.id
    chat_type = query.message.chat.type

    if chat_type == enums.ChatType.PRIVATE:
        grp_id = await active_connection(str(userid))
        if grp_id is not None:
            grp_id, title = await get_group_info(client, grp_id)
        else:
            await query.message.edit_text(
                "I'm not connected to any groups!\nCheck /connections or connect to any groups",
                quote=True
            )
            return await query.answer('𝙿𝙻𝙴𝙰𝚂𝙴 𝚂𝙷𝙰𝚁𝙴 𝙰𝙽𝙳 𝚂𝚄𝙿𝙿𝙾𝚁𝚃')

    elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
        grp_id = query.message.chat.id
        title = query.message.chat.title

    else:
        return await query.answer('Piracy Is Crime')

    st = await get_chat_member_status(client, grp_id, userid)
    if st in [enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMIN] or str(userid) in ADMINS:
        await del_all(query.message, grp_id, title)
    else:
        await query.answer("You need to be Group Owner or an Auth User to do that!", show_alert=True)

async def handle_delete_all_cancel(query):
    userid = query.from_user.id
    chat_type = query.message.chat.type

    if chat_type == enums.ChatType.PRIVATE:
        await query.message.reply_to_message.delete()
        await query.message.delete()
                try:
                    await query.message.reply_to_message.delete()
                except:
                    pass
            else:
                await query.answer("Buddy Don't Touch Others Property 😁", show_alert=True)
    elif "groupcb" in query.data:
        await query.answer()

        group_id = query.data.split(":")[1]

        act = query.data.split(":")[2]
        hr = await client.get_chat(int(group_id))
        title = hr.title
        user_id = query.from_user.id

        if act == "":
            stat = "𝙲𝙾𝙽𝙽𝙴𝙲𝚃"
            cb = "connectcb"
        else:
            stat = "𝙳𝙸𝚂𝙲𝙾𝙽𝙽𝙴𝙲𝚃"
            cb = "disconnect"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{stat}", callback_data=f"{cb}:{group_id}"),
             InlineKeyboardButton("𝙳𝙴𝙻𝙴𝚃𝙴", callback_data=f"deletecb:{group_id}")],
            [InlineKeyboardButton("𝙱𝙰𝙲𝙺", callback_data="backcb")]
        ])

        await query.message.edit_text(
            f"𝙶𝚁𝙾𝚄𝙿 𝙽𝙰𝙼𝙴 :- **{title}**\n𝙶𝚁𝙾𝚄𝙿 𝙸𝙳 :- `{group_id}`",
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return await query.answer('Piracy Is Crime')
    elif "connectcb" in query.data:
        await query.answer()

        group_id = query.data.split(":")[1]

        hr = await client.get_chat(int(group_id))

        title = hr.title

        user_id = query.from_user.id

        mkact = await make_active(str(user_id), str(group_id))

        if mkact:
            await query.message.edit_text(
                f"𝙲𝙾𝙽𝙽𝙴𝙲𝚃𝙴𝙳 𝚃𝙾 **{title}**",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:
            await query.message.edit_text('Some error occurred!!', parse_mode=enums.ParseMode.MARKDOWN)
        return await query.answer('𝙿𝙻𝙴𝙰𝚂𝙴 𝚂𝙷𝙰𝚁𝙴 𝙰𝙽𝙳 𝚂𝚄𝙿𝙿𝙾𝚁𝚃')
    elif "disconnect" in query.data:
        await query.answer()

        group_id = query.data.split(":")[1]

        hr = await client.get_chat(int(group_id))

        title = hr.title
        user_id = query.from_user.id

        mkinact = await make_inactive(str(user_id))

        if mkinact:
            await query.message.edit_text(
                f"𝙳𝙸𝚂𝙲𝙾𝙽𝙽𝙴𝙲𝚃 FROM **{title}**",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:
            await query.message.edit_text(
                f"Some error occurred!!",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        return await query.answer('𝙿𝙻𝙴𝙰𝚂𝙴 𝚂𝙷𝙰𝚁𝙴 𝙰𝙽𝙳 𝚂𝚄𝙿𝙿𝙾𝚁𝚃')
    elif "deletecb" in query.data:
        await query.answer()

        user_id = query.from_user.id
        group_id = query.data.split(":")[1]

        delcon = await delete_connection(str(user_id), str(group_id))

        if delcon:
            await query.message.edit_text(
                "Successfully deleted connection"
            )
        else:
            await query.message.edit_text(
                f"Some error occurred!!",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        return await query.answer('𝙿𝙻𝙴𝙰𝚂𝙴 𝚂𝙷𝙰𝚁𝙴 𝙰𝙽𝙳 𝚂𝚄𝙿𝙿𝙾𝚁𝚃')
    elif query.data == "backcb":
        await query.answer()

        userid = query.from_user.id

        groupids = await all_connections(str(userid))
        if groupids is None:
            await query.message.edit_text(
                "There are no active connections!! Connect to some groups first.",
            )
            return await query.answer('𝙿𝙻𝙴𝙰𝚂𝙴 𝚂𝙷𝙰𝚁𝙴 𝙰𝙽𝙳 𝚂𝚄𝙿𝙿𝙾𝚁𝚃')
        buttons = []
        for groupid in groupids:
            try:
                ttl = await client.get_chat(int(groupid))
                title = ttl.title
                active = await if_active(str(userid), str(groupid))
                act = " - ACTIVE" if active else ""
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"{title}{act}", callback_data=f"groupcb:{groupid}:{act}"
                        )
                    ]
                )
            except:
                pass
        if buttons:
            await query.message.edit_text(
                "Your connected group details ;\n\n",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
    elif "alertmessage" in query.data:
        grp_id = query.message.chat.id
        i = query.data.split(":")[1]
        keyword = query.data.split(":")[2]
        reply_text, btn, alerts, fileid = await find_filter(grp_id, keyword)
        if alerts is not None:
            alerts = ast.literal_eval(alerts)
            alert = alerts[int(i)]
            alert = alert.replace("\\n", "\n").replace("\\t", "\t")
            await query.answer(alert, show_alert=True)
    if query.data.startswith("file"):
        ident, file_id = query.data.split("#")
        files_ = await get_file_details(file_id)
        if not files_:
            return await query.answer('No such file exist.')
        files = files_[0]
        title = files.file_name
        size = get_size(files.file_size)
        f_caption = files.caption
        settings = await get_settings(query.message.chat.id)
        if CUSTOM_FILE_CAPTION:
            try:
                f_caption = CUSTOM_FILE_CAPTION.format(file_name='' if title is None else title,
                                                       file_size='' if size is None else size,
                                                       file_caption='' if f_caption is None else f_caption)
            except Exception as e:
                logger.exception(e)
            f_caption = f_caption
        if f_caption is None:
            f_caption = f"{files.file_name}"

        try:
            if AUTH_CHANNEL and not await is_subscribed(client, query):
                await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
                return
            elif settings['botpm']:
                await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
                return
            else:
                await client.send_cached_media(
                    chat_id=query.from_user.id,
                    file_id=file_id,
                    caption=f_caption,
                    protect_content=True if ident == "filep" else False 
                )
                await query.answer('Check PM, I have sent files in pm', show_alert=True)
        except UserIsBlocked:
            await query.answer('You Are Blocked to use me !', show_alert=True)
        except PeerIdInvalid:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
        except Exception as e:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
    elif query.data.startswith("checksub"):
        if AUTH_CHANNEL and not await is_subscribed(client, query):
            await query.answer("I Like Your Smartness, But Don't Be Oversmart Okay 😒", show_alert=True)
            return
        ident, file_id = query.data.split("#")
        files_ = await get_file_details(file_id)
        if not files_:
            return await query.answer('No such file exist.')
        files = files_[0]
        title = files.file_name
        size = get_size(files.file_size)
        f_caption = files.caption
        if CUSTOM_FILE_CAPTION:
            try:
                f_caption = CUSTOM_FILE_CAPTION.format(file_name='' if title is None else title,
                                                       file_size='' if size is None else size,
                                                       file_caption='' if f_caption is None else f_caption)
            except Exception as e:
                logger.exception(e)
                f_caption = f_caption
        if f_caption is None:
            f_caption = f"{title}"
        await query.answer()
        await client.send_cached_media(
            chat_id=query.from_user.id,
            file_id=file_id,
            caption=f_caption,
            protect_content=True if ident == 'checksubp' else False
      )
  elif query.data == "pages":
    await query.answer()

elif query.data == "start":
    buttons = [
        [
            InlineKeyboardButton('⚚ ΛᎠᎠ MΞ ϮԾ YԾUᏒ GᏒԾUᎮ ⚚', url=f'http://t.me/{temp.U_NAME}?startgroup=true'),
        ],
        [
            InlineKeyboardButton('⚡ SUBSCᏒIBΞ ⚡', url='https://youtube.com/c/GreyMattersBot'),
            InlineKeyboardButton('🤖 UᎮDΛTΞS 🤖', url=script.HOME_BUTTONURL_UPDATES)  # Fix the placeholder here
        ],
        [
            InlineKeyboardButton('♻️ HΞLᎮ ♻️', callback_data='help'),
            InlineKeyboardButton('♻️ ΛBOUT ♻️', callback_data='about')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.START_TXT.format(query.from_user.mention, temp.U_NAME, temp.B_NAME),
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )
    await query.answer('𝙿𝙻𝙴𝙰𝚂𝙴 𝚂𝙷𝙰𝚁𝙴 𝙰𝙽𝙳 𝚂𝚄𝙿𝙿𝙾𝚁𝚃')

elif query.data == "help":
    buttons = [
        [
            InlineKeyboardButton('𝙼𝙰𝙽𝚄𝙴𝙻 𝙵𝙸𝙻𝚃𝙴𝚁', callback_data='manuelfilter'),
            InlineKeyboardButton('𝙰𝚄𝚃𝙾 𝙵𝙸𝙻𝚃𝙴𝚁', callback_data='autofilter')
        ],
        [
            InlineKeyboardButton('𝙲𝙾𝙽𝙽𝙴𝙲𝚃𝙸𝙾𝙽𝚂', callback_data='coct'),
            InlineKeyboardButton('𝙴𝚇𝚃𝚁𝙰 𝙼𝙾D𝚂', callback_data='extra')
        ],
        [
            InlineKeyboardButton('🏠 H𝙾𝙼𝙴 🏠', callback_data='start'),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.HELP_TXT.format(query.from_user.mention),
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )
   elif query.data == "about":
    buttons = [
        [InlineKeyboardButton('🏠 H𝙾𝙼𝙴 🏠', callback_data='start')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.ABOUT_TXT.format(temp.B_NAME),
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )

elif query.data == "source":
    buttons = [
        [InlineKeyboardButton('👩‍🦯 𝙱𝙰𝙲𝙺', callback_data='about')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.SOURCE_TXT,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )

elif query.data == "manuelfilter":
    buttons = [
        [InlineKeyboardButton('👩‍🦯 𝙱𝙰𝙲𝙺', callback_data='help')],
        [InlineKeyboardButton('⏹️ 𝙱𝚄𝚃𝚃𝙾𝙽𝚂', callback_data='button')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.MANUELFILTER_TXT,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )
   elif query.data == "button":
    buttons = [
        [InlineKeyboardButton('⏹️ 𝙱𝚄𝚃𝚃𝙾𝙽𝚂', callback_data='button')],
        [InlineKeyboardButton('👩‍🦯 𝙱𝙰𝙲𝙺', callback_data='manuelfilter')]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.BUTTON_TXT,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )

elif query.data == "autofilter":
    buttons = [
        [InlineKeyboardButton('👩‍🦯 𝙱𝙰𝙲𝙺', callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.AUTOFILTER_TXT,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )

elif query.data == "coct":
    buttons = [
        [InlineKeyboardButton('👩‍🦯 𝙱𝙰𝙲𝙺', callback_data='help')]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.CONNECTION_TXT,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )
    elif query.data == "extra":
    buttons = [
        [InlineKeyboardButton('👮‍♂️ 𝙰𝙳𝙼𝙸𝙽', callback_data='admin')],
        [InlineKeyboardButton('👩‍🦯 𝙱𝙰𝙲𝙺', callback_data='help')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.EXTRAMOD_TXT,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )

elif query.data == "admin":
    buttons = [
        [InlineKeyboardButton('👩‍🦯 𝙱𝙰𝙲𝙺', callback_data='extra')],
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_text(
        text=script.ADMIN_TXT,
        reply_markup=reply_markup,
        parse_mode=enums.ParseMode.HTML
    )

elif query.data == "stats" or query.data == "rfrsh":
    await query.answer("Fetching MongoDB DataBase")
    try:
        total = await Media.count_documents()
        users = await db.total_users_count()
        chats = await db.total_chat_count()
        monsize = await db.get_db_size()
        free = 536870912 - monsize
        monsize = get_size(monsize)
        free = get_size(free)
        buttons = [
            [InlineKeyboardButton('♻️ 𝚁𝙴𝙵𝚁𝙴𝚂𝙷', callback_data='rfrsh')],
            [InlineKeyboardButton('👩‍🦯 𝙱𝙰𝙲𝙺', callback_data='help')],
        ]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.STATUS_TXT.format(total, users, chats, monsize, free),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    except Exception as e:
        # Handle the exception (e.g., log the error, provide a user-friendly message)
        print(f"Error fetching MongoDB data: {e}")
        await query.answer("An error occurred while fetching data. Please try again.")
  elif query.data.startswith("setgs"):
    # Extracting information from callback data
    ident, set_type, status, grp_id = query.data.split("#")

    # Check if the group ID matches the active connection
    grpid = await active_connection(str(query.from_user.id))
    if str(grp_id) != str(grpid):
        # Inform the user about the active connection change
        await query.message.edit("Your Active Connection Has Been Changed. Go To /settings.")
        return await query.answer('𝙿𝙻𝙴𝙰𝚂𝙴 𝚂𝙷𝙰𝚁𝙴 𝙰𝙽𝙳 𝚂𝚄𝙿𝙿𝙾𝚁𝚃')

    # Update group settings based on callback data
    if status == "True":
        await save_group_settings(grpid, set_type, False)
    else:
        await save_group_settings(grpid, set_type, True)

    # Fetch the updated settings
    settings = await get_settings(grpid)

        if settings is not None:
    buttons = [
        [
            InlineKeyboardButton('𝐅𝐈𝐋𝐓𝐄𝐑 𝐁𝐔𝐓𝐓𝐎𝐍',
                                 callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}'),
            InlineKeyboardButton('𝐒𝐈𝐍𝐆𝐋𝐄' if settings["button"] else '𝐃𝐎𝐔𝐁𝐋𝐄',
                                 callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}')
        ],
        [
            InlineKeyboardButton('𝐁𝐎𝐓 𝐏𝐌', callback_data=f'setgs#botpm#{settings["botpm"]}#{str(grp_id)}'),
            InlineKeyboardButton('✅ 𝐘𝐄𝐒' if settings["botpm"] else '❌ 𝐍𝐎',
                                 callback_data=f'setgs#botpm#{settings["botpm"]}#{str(grp_id)}')
        ],
        [
            InlineKeyboardButton('𝐅𝐈𝐋𝐄 𝐒𝐄𝐂𝐔𝐑𝐄',
                                 callback_data=f'setgs#file_secure#{settings["file_secure"]}#{str(grp_id)}'),
            InlineKeyboardButton('✅ 𝐘𝐄𝐒' if settings["file_secure"] else '❌ 𝐍𝐎',
                                 callback_data=f'setgs#file_secure#{settings["file_secure"]}#{str(grp_id)}')
        ],
        [
            InlineKeyboardButton('𝐈𝐌𝐃𝐁', callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}'),
            InlineKeyboardButton('✅ 𝐘𝐄𝐒' if settings["imdb"] else '❌ 𝐍𝐎',
                                 callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}')
        ],
        [
            InlineKeyboardButton('𝐒𝐏𝐄𝐋𝐋 𝐂𝐇𝐄𝐂𝐊',
                                 callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}'),
            InlineKeyboardButton('✅ 𝐘𝐄𝐒' if settings["spell_check"] else '❌ 𝐍𝐎',
                                 callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}')
        ],
        [
            InlineKeyboardButton('𝐖𝐄𝐋𝐂𝐎𝐌𝐄', callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}'),
            InlineKeyboardButton('✅ 𝐘𝐄𝐒' if settings["welcome"] else '❌ 𝐍𝐎',
                                 callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    await query.message.edit_reply_markup(reply_markup)
await query.answer('𝙿𝙻𝙴𝙰𝚂𝙴 𝚂𝙷𝙰𝚁𝙴 𝙰𝙽𝙳 𝚂𝚄𝙿𝙿𝙾𝚁𝚃')


async def auto_filter(client, msg, spoll=False):
    if not spoll:
        message = msg
        settings = await get_settings(message.chat.id)

        # Ignore commands
        if message.text.startswith("/"):
            return

        # Ignore messages starting with specific characters (commands, emojis, etc.)
        if re.findall("((^\/|^,|^!|^\.|^[\U0001F600-\U000E007F]).*)", message.text):
            return

        # Process messages with a length between 2 and 100 characters
        if 2 < len(message.text) < 100:
            search = message.text
            files, offset, total_results = await get_search_results(search.lower(), offset=0, filter=True)

            # If no files are found and spell checking is enabled, invoke advantage_spell_chok
            if not files:
                if settings["spell_check"]:
                    return await advantage_spell_chok(msg)
                else:
                    return
        else:
            return
    else:
    settings = await get_settings(msg.message.chat.id)
    message = msg.message.reply_to_message  # msg will be callback query
    search, files, offset, total_results = spoll

pre = 'filep' if settings['file_secure'] else 'file'
if settings["button"]:
    btn = [
        [
            InlineKeyboardButton(
                text=f"[{get_size(file.file_size)}]-💠-{file.file_name}", callback_data=f'{pre}#{file.file_id}'
            ),
        ]
        for file in files
    ]
else:
    btn = [
        [
            InlineKeyboardButton(
                text=f"{file.file_name}",
                callback_data=f'{pre}#{file.file_id}',
            ),
            InlineKeyboardButton(
                text=f"{get_size(file.file_size)}",
                callback_data=f'{pre}#{file.file_id}',
             ),
         ]
         for file in files
       ]
    
    if offset != "":
    key = f"{message.chat.id}-{message.id}"
    BUTTONS[key] = search
    req = message.from_user.id if message.from_user else 0
    btn.append(
        [InlineKeyboardButton(text=f"🗓 1/{math.ceil(int(total_results) / 10)}", callback_data="pages"),
         InlineKeyboardButton(text="𝗡𝗲𝘅𝘁 ⏩", callback_data=f"next_{req}_{key}_{offset}")]
    )
else:
    btn.append(
        [InlineKeyboardButton(text="🗓 1/1", callback_data="pages")]
    )
    imdb = await get_poster(search, file=(files[0]).file_name) if settings["imdb"] else None
TEMPLATE = settings['template']
if imdb:
    cap = TEMPLATE.format(
        query=search,
        title=imdb['title'],
        votes=imdb['votes'],
        aka=imdb["aka"],
        seasons=imdb["seasons"],
        box_office=imdb['box_office'],
        localized_title=imdb['localized_title'],
        kind=imdb['kind'],
        imdb_id=imdb["imdb_id"],
        cast=imdb["cast"],
        runtime=imdb["runtime"],
        countries=imdb["countries"],
        certificates=imdb["certificates"],
        languages=imdb["languages"],
        director=imdb["director"],
        writer=imdb["writer"],
        producer=imdb["producer"],
        composer=imdb["composer"],
        cinematographer=imdb["cinematographer"],
        music_team=imdb["music_team"],
        distributors=imdb["distributors"],
        release_date=imdb['release_date'],
        year=imdb['year'],
        genres=imdb['genres'],
        poster=imdb['poster'],
        plot=imdb['plot'],
        rating=imdb['rating'],
        url=imdb['url'],
        **locals()
    )
    else:
    cap = f"Rᴇǫᴜᴇsᴛᴇᴅ ᴍᴏᴠɪᴇ ɴᴀᴍᴇ : <code>{search}</code>\n\n\n😌 ɪꜰ ᴛʜᴇ ᴍᴏᴠɪᴇ ʏᴏᴜ ᴀʀᴇ ʟᴏᴏᴋɪɴɢ ꜰᴏʀ ɪs ɴᴏᴛ ᴀᴠᴀɪʟᴀʙʟᴇ ᴛʜᴇɴ ʟᴇᴀᴠᴇ ᴀ ᴍᴇssᴀɢᴇ ʙᴇʟᴏᴡ 😌 \n\nᴇxᴀᴍᴘʟᴇ : \n\nᴇɴᴛᴇʀ ʏᴏᴜʀ ᴍᴏᴠɪᴇ ɴᴀᴍᴇ (ʏᴇᴀʀ) ᴛᴀɢ @admin"
if imdb and imdb.get('poster'):
    try:
        hehe = await message.reply_photo(photo=imdb.get('poster'), caption=cap[:1024],
                                         reply_markup=InlineKeyboardMarkup(btn))
        if SELF_DELETE:
            await asyncio.sleep(SELF_DELETE_SECONDS)
            await hehe.delete()
    except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
        pic = imdb.get('poster')
        poster = pic.replace('.jpg', "._V1_UX360.jpg")
        hmm = await message.reply_photo(photo=poster, caption=cap[:1024], reply_markup=InlineKeyboardMarkup(btn))
        if SELF_DELETE:
            await asyncio.sleep(SELF_DELETE_SECONDS)
            await hmm.delete()
    except Exception as e:
        logger.exception(e)
        fek = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
        if SELF_DELETE:
            await asyncio.sleep(SELF_DELETE_SECONDS)
            await fek.delete()
else:
    fuk = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
    if SELF_DELETE:
        await asyncio.sleep(SELF_DELETE_SECONDS)
        await fuk.delete()

async def advantage_spell_chok(msg):
    # Removing certain common words and adding "movie" to the query
    query = re.sub(
        r"\b(pl(i|e)*?(s|z+|ease|se|ese|(e+)s(e)?)|((send|snd|giv(e)?|gib)(\sme)?)|movie(s)?|new|latest|br((o|u)h?)*|^h(e|a)?(l)*(o)*|mal(ayalam)?|t(h)?amil|file|that|find|und(o)*|kit(t(i|y)?)?o(w)?|thar(u)?(o)*w?|kittum(o)*|aya(k)*(um(o)*)?|full\smovie|any(one)|with\ssubtitle(s)?)",
        "", msg.text, flags=re.IGNORECASE)  # Remove certain common words
    query = query.strip() + " movie"

    # Searching using the modified query and original message text
    g_s = await search_gagala(query)
    g_s += await search_gagala(msg.text)
    gs_parsed = []

    # If no results are found, notify the user and return
    if not g_s:
        k = await msg.reply("I couldn't find any movie in that name.")
        await asyncio.sleep(8)
        await k.delete()
        return

    # Look for IMDb or Wikipedia results in the search
    regex = re.compile(r".*(imdb|wikipedia).*", re.IGNORECASE)
    gs = list(filter(regex.match, g_s))
    gs_parsed = [re.sub(
        r'\b(\-([a-zA-Z-\s])\-\simdb|(\-\s)?imdb|(\-\s)?wikipedia|\(|\)|\-|reviews|full|all|episode(s)?|film|movie|series)',
        '', i, flags=re.IGNORECASE) for i in gs]

    # If no IMDb or Wikipedia results are found, check for "watch" patterns
    if not gs_parsed:
        reg = re.compile(r"watch(\s[a-zA-Z0-9_\s\-\(\)]*)*\|.*", re.IGNORECASE)
        for mv in g_s:
            match = reg.match(mv)
            if match:
                gs_parsed.append(match.group(1))

    # Get the user ID or use 0 if not available
    user = msg.from_user.id if msg.from_user else 0

    # Parse the search results and filter out duplicates
    gs_parsed = list(dict.fromkeys(gs_parsed))
    
    # Limit the number of parsed results to 3
    if len(gs_parsed) > 3:
        gs_parsed = gs_parsed[:3]

    # If there are parsed results, search IMDb for each keyword
    if gs_parsed:
        for mov in gs_parsed:
            imdb_s = await get_poster(mov.strip(), bulk=True)
            if imdb_s:
                movielist += [movie.get('title') for movie in imdb_s]

    # Further clean up movie names and filter out duplicates
    movielist += [(re.sub(r'(\-|\(|\)|_)', '', i, flags=re.IGNORECASE)).strip() for i in gs_parsed]
    movielist = list(dict.fromkeys(movielist))

    # If no final movie names are found, notify the user and return
    if not movielist:
        k = await msg.reply("I couldn't find anything related to that. Check your spelling")
        await asyncio.sleep(8)
        await k.delete()
        return

    # Store the spell-checked movie list in the global SPELL_CHECK dictionary
    SPELL_CHECK[msg.id] = movielist

    # Create inline keyboard buttons for each movie name
    btn = [[
        InlineKeyboardButton(
            text=movie.strip(),
            callback_data=f"spolling#{user}#{k}",
        )
    ] for k, movie in enumerate(movielist)]
    
    # Add a "Close" button to the inline keyboard
    btn.append([InlineKeyboardButton(text="Close", callback_data=f'spolling#{user}#close_spellcheck')])

    # Send a message to the user with the spell-checked movie suggestions
    await msg.reply("I couldn't find anything related to that\nDid you mean any one of these?",
                    reply_markup=InlineKeyboardMarkup(btn))


async def manual_filters(client, message, text=False):
    # Extract relevant information from the message
    group_id = message.chat.id
    name = text or message.text
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id

    # Retrieve the list of filters for the group
    keywords = await get_filters(group_id)

    # Iterate through filters, checking for matches
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        
        # Check if the keyword is present in the message
        if re.search(pattern, name, flags=re.IGNORECASE):
            # Retrieve information associated with the matched filter
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)

            # Process and send the reply
            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            # Send text or media message with optional buttons
            if btn is not None:
                try:
                    if fileid == "None":
                        if btn == "[]":
                            await client.send_message(
                                group_id, 
                                reply_text, 
                                disable_web_page_preview=True,
                                reply_to_message_id=reply_id
                            )
                        else:
                            button = eval(btn)
                            await client.send_message(
                                group_id,
                                reply_text,
                                disable_web_page_preview=True,
                                reply_markup=InlineKeyboardMarkup(button),
                                reply_to_message_id=reply_id
                            )
                    elif btn == "[]":
                        await client.send_cached_media(
                            group_id,
                            fileid,
                            caption=reply_text or "",
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        await message.reply_cached_media(
                            fileid,
                            caption=reply_text or "",
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                except Exception as e:
                    logger.exception(e)
                break
    else:
        return False
