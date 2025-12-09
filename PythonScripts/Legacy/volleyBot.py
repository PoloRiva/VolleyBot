from telegram.ext import Application, CallbackContext, CommandHandler, ContextTypes, ChatMemberHandler, ConversationHandler, MessageHandler, filters
from telegram import Update, ChatMember, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.constants import ParseMode
from datetime import datetime, timedelta
from collections import deque
import emoji
import json
import time
import os

import phrases
import dbTools

CREDS_JSON = json.load(open(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'creds.json'),))
TOKEN = CREDS_JSON['telegram']['bot_token']
BEACH_GROUP_ID = CREDS_JSON['telegram']['group_id']
LIST_TOPIC_ID = CREDS_JSON['telegram']['thread_id']

#                 Polo    Lau
TELEGRAM_PAYEE_CHAT_IDS = (258936, 1157261407)

# A dictionary to store the list of participants for each group/topic
dbMembers = dict()
dbEvents = dict()
dbEventMapping = dict()

ASK_ACTION, CHOOSE_ACTION, ADD_BKP_TOLIST, CONFIRM_MEMBER, ASK_CONFIRM_BKP_EMOJI, CONFIRM_BKP, REMOVE_BKP_FROM_LIST, CHANGE_MEMBER_NICKNAME = range(8)

# ---------------------------------------------------------------------------- #
#                                     Tools                                    #
# ---------------------------------------------------------------------------- #
async def getChatId(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f'\nupdate: {update}')
    print(f'\nupdate.effective_chat: {update.effective_chat}')

def prepareListText(eventId):

    # HEAD
    txt = f'''{dbEvents[eventId]['place']} - {dbEvents[eventId]['start'].strftime('%a %d %b %H:%M')} ({round((dbEvents[eventId]['end']-dbEvents[eventId]['start']).total_seconds()/60)} mins, €{round(dbEvents[eventId]['price']/dbEvents[eventId]['players'],4)}/ea, {dbEvents[eventId]['players']}p) '''
    i = 1

    if dbEvents[eventId]['status'] == 'ONLINE':
        # ON_LIST/CONFIRMED
        for chatId in [cId for cId in dbEvents[eventId]['list'] if dbEvents[eventId]['list'][cId]['status'] in ('ON_LIST', 'CONFIRMED')]:
            txt += f'''\n{i}.\t{dbMembers[chatId]['nickname']}{f' {dbEvents[eventId]['list'][chatId]['confirmationEmoji']}' if dbEvents[eventId]['list'][chatId]['confirmationEmoji'] else ''}'''
            i += 1

        bkpIndex = i

        # BKP
        flatBkp = list()
        for chatId in dbEvents[eventId]['bkp']:
            for backupNickname in [bkpNick for bkpNick in dbEvents[eventId]['bkp'][chatId] if dbEvents[eventId]['bkp'][chatId][bkpNick]['status'] in ('ON_LIST', 'CONFIRMED')]:
                flatBkp.append({'chatId': chatId, 'backupNickname': backupNickname, 'orderDatetime':  dbEvents[eventId]['bkp'][chatId][backupNickname]['orderDatetime'], 'confirmationEmoji': dbEvents[eventId]['bkp'][chatId][backupNickname]['confirmationEmoji']})

        for bkp in sorted(flatBkp, key=lambda item: item['orderDatetime']):
            if i == bkpIndex:
                # Bkp Head
                txt += f'''\n\nBkp:'''
            txt += f'''\n{i}.\t{bkp['backupNickname']} ({dbMembers[bkp['chatId']]['nickname']}){f' {bkp['confirmationEmoji']}' if bkp['confirmationEmoji'] else ''}'''
            i += 1

        # TODO: REMOVED_CONFIRMED

    elif dbEvents[eventId]['status'] == 'CUTOFF':
        flatList = list()
        lineDivider = False
        # LIST
        for chatId in [cId for cId in dbEvents[eventId]['list'] if dbEvents[eventId]['list'][cId]['status'] in ('ON_LIST', 'CONFIRMED')]:
            flatList.append({'chatId': chatId, 'status': dbEvents[eventId]['list'][chatId]['status'], 'backupNickname': None, 'confirmationEmoji': dbEvents[eventId]['list'][chatId]['confirmationEmoji'], 'orderDatetime': dbEvents[eventId]['list'][chatId]['orderDatetime']})

        # BKP
        for chatId in dbEvents[eventId]['bkp']:
            for backupNickname in [bkpNick for bkpNick in dbEvents[eventId]['bkp'][chatId] if dbEvents[eventId]['bkp'][chatId][bkpNick]['status'] in ('ON_LIST', 'CONFIRMED')]:
                flatList.append({'chatId': chatId, 'status': dbEvents[eventId]['bkp'][chatId][backupNickname]['status'], 'backupNickname': backupNickname, 'confirmationEmoji': dbEvents[eventId]['bkp'][chatId][backupNickname]['confirmationEmoji'], 'orderDatetime':  dbEvents[eventId]['bkp'][chatId][backupNickname]['orderDatetime']})

        # LIST TEXT
        for l in sorted(flatList, key=lambda item: (item['confirmationEmoji'] is None, item['orderDatetime'])):

            # Add line divider ?
            if lineDivider == False:
                if i == dbEvents[eventId]['players']:   # Reached number of players
                    txt += '\n'
                    lineDivider = True
                elif l['confirmationEmoji'] is None or l['status'] == 'REMOVED_CONFIRMED':  # no more confirmations
                    txt += '\n'
                    lineDivider = True

            # next line on the list
            if l['backupNickname'] is None:
                # Not a bkp
                txt += f'''\n{i}.\t{dbMembers[l['chatId']]['nickname']}{f' {l['confirmationEmoji']}' if l['confirmationEmoji'] else ''}'''
            else:
                # A bkp
                txt += f'''\n{i}.\t{l['backupNickname']} ({dbMembers[l['chatId']]['nickname']}){f' {l['confirmationEmoji']}' if l['confirmationEmoji'] else ''}'''
            i += 1

    return txt

# ---------------------------------------------------------------------------- #
#                                   JobQueue                                   #
# ---------------------------------------------------------------------------- #
async def taskEventEvolution(context: CallbackContext):
    global dbMembers, dbEvents, dbEventMapping

    action = context.job.data['action']

    # ---------------------------------- SYNC_DB --------------------------------- #
    if action == 'syncDb':

        if context.job.data['run']:
            dbMembers, dbEvents, dbEventMapping = dbTools.syncDbLocally()
        # schedule next syncDb
        now = datetime.now()
        context.application.job_queue.run_once(taskEventEvolution, when=((now.replace(hour=2, minute=0, second=0, microsecond=0) + timedelta(days=1)) - now), data={'action': 'syncDb', 'run': True})

    # --------------------------------- SEND_MSG --------------------------------- #
    elif action == 'sendMsg':

        msgType = context.job.data['msgType']

        if msgType == 'CUTOFF_IN_2HRS':
            await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=phrases.cutoffIn2Hrs(), parse_mode=ParseMode.HTML)

    # ----------------------------- NEW_EVENT_STATUS ----------------------------- #
    elif action == 'newEventStatus':

        eventId = context.job.data['eventId']
        newStatus = context.job.data['newStatus']

        # Update the status of the event
        dbTools.eventEvolution(eventId, newStatus)
        dbEvents[eventId]['status'] = newStatus

        if newStatus == 'ONLINE':
            # First add payee on the list
            for pChatId in TELEGRAM_PAYEE_CHAT_IDS:
                if pChatId in dbMembers:
                    if pChatId not in dbEvents[eventId]['list']:
                        dbTools.addMemberToList(eventId, pChatId)
                        dbEvents[eventId]['list'][pChatId] = {'confirmationEmoji': None, 'status': 'ON_LIST', 'orderDatetime': datetime.now()}

            await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=prepareListText(eventId), parse_mode=ParseMode.HTML)
            # next schedule is being CUTOFF
            context.application.job_queue.run_once(taskEventEvolution, when=(dbEvents[eventId]['cutoff']-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'CUTOFF', 'eventId': eventId})

        elif newStatus == 'CUTOFF':
            dbTools.cutoffEvent(eventId)
            dbMembers, dbEvents, dbEventMapping = dbTools.syncDbLocally()
            await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=prepareListText(eventId), parse_mode=ParseMode.HTML)
            # next schedule is being PLAYED, 2 hours before starting the game
            context.application.job_queue.run_once(taskEventEvolution, when=((dbEvents[eventId]['start'] - timedelta(hours=2))-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'PLAYED', 'eventId': eventId})

        elif newStatus == 'PLAYED':
            await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=phrases.haveFun(hours_mins=dbEvents[eventId]['start'].strftime('%H:%M')), parse_mode=ParseMode.HTML)
            # next schedule is being DONE, at 10 AM the morning of the day after the start of the game
            context.application.job_queue.run_once(taskEventEvolution, when=((dbEvents[eventId]['start'] + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'DONE', 'eventId': eventId})

        elif newStatus == 'DONE':
            await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=phrases.rememberToPay(), parse_mode=ParseMode.HTML)

def prepareEventTasks(application: Application):
    global dbMembers, dbEvents, dbEventMapping

    # schedule next SyncDB
    application.job_queue.run_once(taskEventEvolution, when=timedelta(seconds=5), data={'action': 'syncDb', 'run': False})

    for eventId in dbEvents:
        if dbEvents[eventId]['status'] == 'NEW':
            # Event next step is to be ONLINE
            application.job_queue.run_once(taskEventEvolution, when=(dbEvents[eventId]['online']-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'ONLINE', 'eventId': eventId})

        elif dbEvents[eventId]['status'] == 'ONLINE':
            # Event next step is to be CUTOFF
            application.job_queue.run_once(taskEventEvolution, when=(dbEvents[eventId]['cutoff']-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'CUTOFF', 'eventId': eventId})
            # Remember everyone CUTOFF 2 hrs before
            application.job_queue.run_once(taskEventEvolution, when=((dbEvents[eventId]['cutoff'] - timedelta(hours=2))-datetime.now()), data={'action': 'sendMsg', 'msgType': 'CUTOFF_IN_2HRS', 'eventId': eventId})

        elif dbEvents[eventId]['status'] == 'CUTOFF':
            # Run CUTOFF just in case now
            dbTools.cutoffEvent(eventId)
            dbMembers, dbEvents, dbEventMapping = dbTools.syncDbLocally()
            # Event next step is to be PLAYED
            application.job_queue.run_once(taskEventEvolution, when=((dbEvents[eventId]['start'] - timedelta(hours=2))-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'PLAYED', 'eventId': eventId})

        elif dbEvents[eventId]['status'] == 'PLAYED':
            # Event next step is to be DONE, at 10 AM the morning after the start of the game
            application.job_queue.run_once(taskEventEvolution, when=((dbEvents[eventId]['start'] + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'PLAYED', 'eventId': eventId})

# ---------------------------------------------------------------------------- #
#                                    Members                                   #
# ---------------------------------------------------------------------------- #
async def manageMemberUpdate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # First check that this is the Beach Volley group
    if update.chat_member.chat.id == BEACH_GROUP_ID:
        member = update.chat_member.new_chat_member.user

        if update.chat_member.new_chat_member.status == ChatMember.MEMBER:
            # User added to the group
            dbMembers[member.id] = {'nickname': member.first_name, 'rank': 'Member'}
            dbTools.addOrUpdateUser(update.chat_member.new_chat_member)
            await update.effective_chat.send_message(phrases.welcome(userName=member.mention_html(member.first_name)), parse_mode=ParseMode.HTML)

        elif update.chat_member.new_chat_member.status == ChatMember.ADMINISTRATOR:
            # User promoted to admin
            dbMembers[member.id] = {'nickname': member.first_name, 'rank': 'Admin'}
            dbTools.changeMemberRank(chatId=member.id, rank='Admin')

        elif update.chat_member.new_chat_member.status == ChatMember.BANNED:
            # User removed from the group
            memberNickname = dbMembers[member.id]['nickname']
            dbMembers.pop(member.id, None)
            dbTools.removeUser(chatId=member.id)
            await update.effective_chat.send_message(phrases.goodbye(userName=member.mention_html(memberNickname)), parse_mode=ParseMode.HTML)

# ---------------------------------------------------------------------------- #
#                                     Lists                                    #
# ---------------------------------------------------------------------------- #
async def askEvent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    # Check if the user is a member
    chatId = update.message.chat_id

    if chatId not in dbMembers:
        return ConversationHandler.END

    if chatId == BEACH_GROUP_ID:
        return ConversationHandler.END
        # TODO: message received from the beach group, the member should talk directly to the bot

    # Check if more than one event is currently available
    activeEventsIds = [ae for ae in dbEvents if dbEvents[ae]['status'] in ('ONLINE', 'CUTOFF')]
    if len(activeEventsIds) == 1:
        # There is only one event currently active -> CHOOSE_ACTION
        context.user_data['eventId'] = activeEventsIds[0]
        await update.message.reply_text(f'Choosing for {dbEvents[activeEventsIds[0]]['place']}@{dbEvents[activeEventsIds[0]]['start'].strftime('%a %d %b %H:%M')}')
        return await askAction(update, context)

    elif len(activeEventsIds) > 0:
        # Ask for the event
        activeEventsString = [f'{dbEventMapping[eaId]}' for eaId in activeEventsIds]
        keyBoardArray = [activeEventsString[i:i + 2] for i in range(0, len(activeEventsString), 2)]
        await update.message.reply_text('Select one game', reply_markup=ReplyKeyboardMarkup(keyBoardArray))
        return ASK_ACTION

    else:
        await update.message.reply_text(phrases.noGamesAvailable(dbMembers[chatId]['nickname']), reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

async def askAction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    if 'eventId' in context.user_data:
        # Only one event was active
        eventId = context.user_data['eventId']
    else:
        # More than one event was active
        eventString = update.message.text
        if eventString not in dbEventMapping:
            # The event string not found, probably didn't use btns, cancel conversation
            await update.message.reply_text('''sorry, I can't find that game''', reply_markup=ReplyKeyboardRemove())
            return await cleanUserDataAndEndConversation(update, context)

        eventId = dbEventMapping[eventString]

    context.user_data['eventId'] = eventId

    chatId = update.message.chat_id
    keyBoardArray = list()

    keyBoardArray.append(['ADD me to the list 📋', 'ADD a bkp to the list 📋'])
    keyBoardArray.append(['CONFIRM me', 'CONFIRM bkp'])
    keyBoardArray.append(['REMOVE me from the list 😔', 'REMOVE bkp from the list 🙄'])
    keyBoardArray.append(['Change my nickname 🔤'])

    # Send the list
    if dbMembers[chatId]['rank'] == 'Owner':
        keyBoardArray[-1].append('Send the list')
        keyBoardArray[-1].append('SyncDb locally')

    await update.message.reply_text('What do you want to do', reply_markup=ReplyKeyboardMarkup(keyBoardArray))

    return CHOOSE_ACTION

async def addMemberToTheList(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    eventId = context.user_data['eventId']
    chatId = update.message.chat.id

    if dbEvents[eventId]['status'] not in ('ONLINE', 'CUTOFF'):
        await update.message.reply_text('There is no game available yet!', reply_markup=ReplyKeyboardRemove())

    elif dbEvents[eventId]['list'].get(chatId, {'status': -1})['status'] in ('ON_LIST', 'CONFIRMED'):
        await update.message.reply_text('You are already on the list!', reply_markup=ReplyKeyboardRemove())

    else:
        dbTools.addMemberToList(eventId, chatId)
        if dbEvents[eventId]['list'].get(chatId, {}).get('status', {}) == 'REMOVED_CONFIRMED':
            dbEvents[eventId]['list'][chatId]['status'] = 'CONFIRMED'
            dbEvents[eventId]['list'][chatId]['orderDatetime'] = datetime.now()
        else:
            dbEvents[eventId]['list'][chatId] = {'confirmationEmoji': None, 'status': 'ON_LIST', 'orderDatetime': datetime.now()}

        await update.message.reply_text('You have been added to the list!', reply_markup=ReplyKeyboardRemove())
        await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=prepareListText(eventId), parse_mode=ParseMode.HTML)

    return await cleanUserDataAndEndConversation(update, context)

async def askBkpNickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    eventId = context.user_data['eventId']

    if dbEvents[eventId]['status'] in ('NEW', 'PLAYED', 'DONE'):
        await update.message.reply_text('There is no game available yet!', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    context.user_data['eventId'] = eventId
    await update.message.reply_text('Alright, send me you bkp nickname', reply_markup=ReplyKeyboardRemove())

    return ADD_BKP_TOLIST

async def addBkpToTheList(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    chatId = update.message.chat.id
    eventId = context.user_data['eventId']
    bkpNickname = update.message.text[:15]

    if dbEvents[eventId]['bkp'].get(chatId, {}).get(bkpNickname, {'status': -1})['status'] in ('ON_LIST', 'CONFIRMED'):
        await update.message.reply_text('Your bkp is already on the list!')

    else:
        dbTools.addMemberToList(eventId, chatId, bkpNickname)
        if chatId not in dbEvents[eventId]['bkp']:
            dbEvents[eventId]['bkp'][chatId] = dict()
        dbEvents[eventId]['bkp'][chatId][bkpNickname] = {'confirmationEmoji': None, 'status': 'ON_LIST', 'orderDatetime': datetime.now()}
        await update.message.reply_text('Your bkp has been added to the list!')
        await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=prepareListText(eventId), parse_mode=ParseMode.HTML)

    return await cleanUserDataAndEndConversation(update, context)

async def askConfirmEmoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    eventId = context.user_data['eventId']
    chatId = update.message.chat.id

    if chatId not in dbEvents[eventId]['list']:
        await update.message.reply_text('You are not even on the list!')
        return await cleanUserDataAndEndConversation(update, context)

    if dbEvents[eventId]['list'][chatId]['confirmationEmoji']:
        await update.message.reply_text('You are already confirmed!')
        return await cleanUserDataAndEndConversation(update, context)

    await update.message.reply_text('Alright, send me the emoji', reply_markup=ReplyKeyboardRemove())
    return CONFIRM_MEMBER

async def confirmMember(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    emojiTxt = ''.join(e for e in update.message.text if emoji.is_emoji(e))

    if len(emojiTxt) == 0:
        await update.message.reply_text('Send me at least one emoji', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    elif len(emojiTxt) > 3:
        await update.message.reply_text('Send at most 3 emojis', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    eventId = context.user_data['eventId']
    chatId = update.message.chat.id

    # Confirming member
    dbTools.confirmMember(eventId, chatId, emojiTxt, cutoff=(True if dbEvents[eventId]['status'] == 'CUTOFF' else False))
    dbEvents[eventId]['list'][chatId]['confirmationEmoji'] = emojiTxt
    dbEvents[eventId]['list'][chatId]['status'] = 'CONFIRMED'
    if dbEvents[eventId]['status'] == 'CUTOFF':
        dbEvents[eventId]['list'][chatId]['status']['orderDatetime'] = datetime.now()
    await update.message.reply_text('''You've been confirmed''', reply_markup=ReplyKeyboardRemove())
    await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=prepareListText(eventId), parse_mode=ParseMode.HTML)
    return await cleanUserDataAndEndConversation(update, context)

async def askConfirmBkpKeyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    chatId = update.message.chat.id
    eventId = context.user_data['eventId']

    # Do you have at least one bkp ?
    if chatId not in dbEvents[eventId]['bkp']:
        await update.message.reply_text('''You don't have any bkps''', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    bkpNicknamesOptions = [bkpNick for bkpNick in dbEvents[eventId]['bkp'][chatId] if dbEvents[eventId]['bkp'][chatId][bkpNick]['status'] in ('ON_LIST')]

    if len(bkpNicknamesOptions) == 0:
        await update.message.reply_text('''You don't have any bkps that needs confirmation''', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    elif len(bkpNicknamesOptions) == 1:
        context.user_data['bkpNickname'] = bkpNicknamesOptions[0]
        return await askConfirmBkpEmoji(update, context)

    else:
        context.user_data['bkpNickname'] = None
        keyBoardArray = [bkpNicknamesOptions[i:i + 2] for i in range(0, len(bkpNicknamesOptions), 2)]
        await update.message.reply_text('Select you bkp', reply_markup=ReplyKeyboardMarkup(keyBoardArray))

    return ASK_CONFIRM_BKP_EMOJI

async def askConfirmBkpEmoji(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    if context.user_data['bkpNickname'] is None:
        context.user_data['bkpNickname'] = update.message.text
    await update.message.reply_text('Alright, send me the emoji', reply_markup=ReplyKeyboardRemove())
    return CONFIRM_BKP

async def confirmBkp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    emojiTxt = ''.join(e for e in update.message.text if emoji.is_emoji(e))

    if len(emojiTxt) == 0:
        await update.message.reply_text('Send me at least one emoji', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    elif len(emojiTxt) > 3:
        await update.message.reply_text('Send at most 3 emojis', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    chatId = update.message.chat.id
    eventId = context.user_data['eventId']
    bkpNickname = context.user_data['bkpNickname']

    if chatId not in dbEvents[eventId]['bkp']:
        await update.message.reply_text('You dont have any bkps!', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    if bkpNickname not in dbEvents[eventId]['bkp'][chatId]:
        await update.message.reply_text(f'"{bkpNickname}" not found as your bkp!', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    if dbEvents[eventId]['bkp'][chatId][bkpNickname]['status'] == 'ON_LIST':
        dbTools.confirmMember(eventId, chatId, emojiTxt, bkpNickname)
        dbEvents[eventId]['bkp'][chatId][bkpNickname]['confirmationEmoji'] = emojiTxt
        dbEvents[eventId]['bkp'][chatId][bkpNickname]['status'] = 'CONFIRMED'
        if dbEvents[eventId]['status'] == 'CUTOFF':
            dbEvents[eventId]['bkp'][chatId][bkpNickname]['orderDatetime'] = datetime.now()
        await update.message.reply_text('Bkp confirmed!', reply_markup=ReplyKeyboardRemove())
        await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=prepareListText(eventId), parse_mode=ParseMode.HTML)

    return await cleanUserDataAndEndConversation(update, context)

async def askRemoveBkpKeyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    chatId = update.message.chat.id
    eventId = context.user_data['eventId']

    # Do you have at least one bkp ?
    if chatId not in dbEvents[eventId]['bkp']:
        await update.message.reply_text('''You don't have any bkps''', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    bkpNicknamesOptions = [bkpNick for bkpNick in dbEvents[eventId]['bkp'][chatId] if dbEvents[eventId]['bkp'][chatId][bkpNick]['status'] in ('ON_LIST', 'CONFIRMED')]

    if len(bkpNicknamesOptions) == 0:
        await update.message.reply_text('''You don't have any bkps''', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    elif len(bkpNicknamesOptions) == 1:
        context.user_data['bkpNickname'] = bkpNicknamesOptions[0]
        await removeBkpFromList(update, context)

    else:

        keyBoardArray = [bkpNicknamesOptions[i:i + 2] for i in range(0, len(bkpNicknamesOptions), 2)]
        await update.message.reply_text("Select you bkp", reply_markup=ReplyKeyboardMarkup(keyBoardArray))

    return REMOVE_BKP_FROM_LIST

async def removeMemberFromTheList(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    chatId = update.message.chat.id
    eventId = context.user_data['eventId']

    if chatId in dbEvents[eventId]['list'] and dbEvents[eventId]['list'][chatId]['status'] in ('ON_LIST', 'CONFIRMED'):
        dbTools.removeMemberFromList(eventId, chatId)
        memberEmoji = dbEvents[eventId]['list'][chatId]['confirmationEmoji']
        memberNewStatus = 'REMOVED_CONFIRMED' if dbEvents[eventId]['list'][chatId]['status'] == 'CONFIRMED' else 'REMOVED'
        dbEvents[eventId]['list'].pop(chatId, None)
        dbEvents[eventId]['list'][chatId] = {'confirmationEmoji': memberEmoji, 'status': memberNewStatus, 'orderDatetime': datetime.now()}
        await update.message.reply_text('You have been removed from the list!', reply_markup=ReplyKeyboardRemove())
        await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=prepareListText(eventId), parse_mode=ParseMode.HTML)

    else:
        await update.message.reply_text('You are not even on the list!', reply_markup=ReplyKeyboardRemove())

    return await cleanUserDataAndEndConversation(update, context)

async def removeBkpFromList(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    chatId = update.message.chat_id
    eventId = context.user_data['eventId']
    bkpNickname = context.user_data.get('bkpNickname', update.message.text)

    if bkpNickname not in dbEvents[eventId]['bkp'][chatId]:
        await update.message.reply_text(f'''You don't have {bkpNickname} as bkp!''', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    dbTools.removeMemberFromList(eventId, chatId, bkpNickname)
    dbEvents[eventId]['bkp'][chatId][bkpNickname]['status'] = 'REMOVED_CONFIRMED' if dbEvents[eventId]['bkp'][chatId][bkpNickname]['status'] == 'CONFIRMED' else 'REMOVED'
    dbEvents[eventId]['bkp'][chatId][bkpNickname]['orderDatetime'] = datetime.now()
    await update.message.reply_text('Your bkp has been removed from the list!', reply_markup=ReplyKeyboardRemove())
    await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=prepareListText(eventId), parse_mode=ParseMode.HTML)

    return await cleanUserDataAndEndConversation(update, context)

async def askNewNickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    await update.message.reply_text('Alright, send me your new nickname')

    return CHANGE_MEMBER_NICKNAME

async def changeMemberNickname(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    newNickname = update.message.text[:15]
    chatId = update.message.chat.id

    dbTools.changeMemberNickname(chatId, newNickname)
    oldNickname = dbMembers[chatId]['nickname']
    dbMembers[chatId]['nickname'] = newNickname

    await update.message.reply_text(phrases.changeNickname(oldNickname, newNickname))

    return await cleanUserDataAndEndConversation(update, context)

async def sendTheList(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:

    eventId = context.user_data['eventId']

    if dbEvents[eventId]['status'] not in ('ONLINE', 'CUTOFF'):
        await update.message.reply_text('The event status is neither ONLINE nor CUTOFF', reply_markup=ReplyKeyboardRemove())
        return await cleanUserDataAndEndConversation(update, context)

    await context.application.bot.send_message(chat_id=BEACH_GROUP_ID, message_thread_id=LIST_TOPIC_ID, text=prepareListText(eventId), parse_mode=ParseMode.HTML)
    return await cleanUserDataAndEndConversation(update, context)

async def syncDbLocally(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    global dbMembers, dbEvents, dbEventMapping

    dbMembers, dbEvents, dbEventMapping = dbTools.syncDbLocally()

    await update.message.reply_text('Sync completed', reply_markup=ReplyKeyboardRemove())
    return await cleanUserDataAndEndConversation(update, context)

async def cleanUserDataAndEndConversation(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data.pop('eventId', None)
    context.user_data.pop('bkpNickname', None)
    await update.message.reply_text(text='DONE\nsend "/start" or click the btn below to start again',
                                    reply_markup=ReplyKeyboardMarkup(   [['/start']],
                                                                        resize_keyboard=True,
                                                                        one_time_keyboard=True
                                                                    ))
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('sorry, command not recognized 🤖💥', reply_markup=ReplyKeyboardRemove())
    return await cleanUserDataAndEndConversation(update, context)

def main():
    global dbMembers, dbEvents, dbEventMapping

    # Starting Server
    dbTools.checkEventStatus()
    dbMembers, dbEvents, dbEventMapping = dbTools.syncDbLocally()

    # Create the application
    application = Application.builder().token(TOKEN).build()

    # Prepare Event tasks
    prepareEventTasks(application)

    # Debug
    application.add_handler(CommandHandler("getChatId", getChatId))


    # manage new/removal of members in the group chat
    application.add_handler(ChatMemberHandler(manageMemberUpdate, ChatMemberHandler.CHAT_MEMBER))

    # Add command and callback handlers
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", askEvent)],
        states={
            ASK_ACTION: [
                MessageHandler(filters.TEXT & ~(filters.COMMAND | filters.Regex("^Done$")), askAction),
            ],
            CHOOSE_ACTION: [
                MessageHandler(filters.Regex("^ADD me to the list 📋$"), addMemberToTheList),
                MessageHandler(filters.Regex("^ADD a bkp to the list 📋$"), askBkpNickname),
                MessageHandler(filters.Regex("^CONFIRM me$"), askConfirmEmoji),
                MessageHandler(filters.Regex("^CONFIRM bkp$"), askConfirmBkpKeyboard),
                MessageHandler(filters.Regex("^REMOVE me from the list 😔$"), removeMemberFromTheList),
                MessageHandler(filters.Regex("^REMOVE bkp from the list 🙄$"), askRemoveBkpKeyboard),
                MessageHandler(filters.Regex("^Change my nickname 🔤$"), askNewNickname),
                MessageHandler(filters.Regex("^Send the list$"), sendTheList),
                MessageHandler(filters.Regex("^SyncDb locally$"), syncDbLocally),
            ],
            ADD_BKP_TOLIST: [
                MessageHandler(filters.TEXT & ~(filters.COMMAND | filters.Regex("^Done$")), addBkpToTheList),
            ],
            CONFIRM_MEMBER: [
                MessageHandler(filters.TEXT & ~(filters.COMMAND | filters.Regex("^Done$")), confirmMember),
            ],
            ASK_CONFIRM_BKP_EMOJI: [
                MessageHandler(filters.TEXT & ~(filters.COMMAND | filters.Regex("^Done$")), askConfirmBkpEmoji),
            ],
            CONFIRM_BKP: [
                MessageHandler(filters.TEXT & ~(filters.COMMAND | filters.Regex("^Done$")), confirmBkp),
            ],
            REMOVE_BKP_FROM_LIST: [
                MessageHandler(filters.TEXT & ~(filters.COMMAND | filters.Regex("^Done$")), removeBkpFromList),
            ],
            CHANGE_MEMBER_NICKNAME: [
                MessageHandler(filters.TEXT & ~(filters.COMMAND | filters.Regex("^Done$")), changeMemberNickname),
            ],
        },
        fallbacks=[MessageHandler(filters.Regex(r"^(?!\/start$).+"), cancel)],
        conversation_timeout=300,
    )

    # Add a handler for the buttons
    application.add_handler(conv_handler)

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
