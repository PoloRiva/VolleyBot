from telegram.ext import Application, CallbackContext, ContextTypes, ChatMemberHandler, MessageHandler, filters
from telegram.constants import ParseMode
from datetime import datetime, timedelta
from telegram import Update, ChatMember
import traceback
import argparse
import asyncio
import emoji
import shlex
import json

import dbTools, phrases
from tools import TELEGRAM_TOKEN, TELEGRAM_BEACH_GROUP_ID, TELEGRAM_LIST_TOPIC_ID, TELEGRAM_PAYEE_CHAT_IDS, TELEGRAM_API_OWNER, COMMANDS_MAP
from tools import CommandNotValid, ParserError, getEventId, generateListText, generateBotHelp, generateAdminBotHelp, sendBotMsg, clearTelegramApplicationJobQueue, generateCutOffAlert, getUserHTMLTag, appendMessageToLogFile
from tools import volleyBotParser, volleyBotAdminParser, dbMembers, dbEvents, indianTakeawayMenuOptions

async def errorHandler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print(f'Error {type(context.error).__name__}')

    # Use traceback.format_exception to get the full traceback as a list of strings
    # The 'error' object is the exception instance, which contains its own traceback.
    trace_list = traceback.format_exception(type(context.error), context.error, context.error.__traceback__)

    # Join the list into a single string
    trace_stack = "".join(trace_list)

    # Append the exception error trace to the file
    appendMessageToLogFile('MAIN_EXCEPTION', f'traceStack:\n{trace_stack}', newLineSeparator=f'\n{'o':{'.^'}{80}}\n')

    # Lastly, send a Telegram msg to the owner
    await sendBotMsg(context.application.bot, f'Error {type(context.error).__name__}\ncheck log files', chatId=TELEGRAM_API_OWNER, messageThreadId=None)

def reloadTelegramBotServer(application: Application):

    # Clear JobQueue | Update any events on the db | sync the db locally
    clearTelegramApplicationJobQueue(application)
    dbTools.checkEventStatus()
    dbTools.syncDbLocally()

async def taskEventEvolution(context: CallbackContext):

    action = context.job.data['action']

    # ---------------------------------- SYNC_DB --------------------------------- #
    if action == 'reSchedule':

        if context.job.data['run']:
            reScheduleFutureEvents(context.application)
        # Recursion call to schedule next syncDb
        now = datetime.now()
        context.application.job_queue.run_once(taskEventEvolution, when=((now.replace(hour=2, minute=0, second=0, microsecond=0) + timedelta(days=1)) - now), data={'action': 'reSchedule', 'run': True})

    # --------------------------------- SEND_MSG --------------------------------- #
    elif action == 'sendMsg':

        msgType = context.job.data['msgType']

        if msgType == 'CUTOFF_IN_2HRS':
            await sendBotMsg(context.application.bot, generateCutOffAlert(context.job.data['eventId']))

    # ----------------------------- NEW_EVENT_STATUS ----------------------------- #
    elif action == 'newEventStatus':

        eventId = context.job.data['eventId']
        newStatus = context.job.data['newStatus']

        # Update the status of the event
        dbTools.updateEventStatus(eventId, newStatus)

        if newStatus == 'ONLINE':
            # First add payee on the list
            for pChatId in TELEGRAM_PAYEE_CHAT_IDS:
                if pChatId in dbMembers:
                    if pChatId not in dbEvents[eventId]['list']:
                        dbTools.addMemberToList(datetime.now(), eventId, pChatId)

            await sendBotMsg(context.application.bot, generateListText(eventId))
            # next schedule is being CUTOFF
            context.application.job_queue.run_once(taskEventEvolution, when=(dbEvents[eventId]['cutoff']-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'CUTOFF', 'eventId': eventId})

        elif newStatus == 'CUTOFF':
            dbTools.cutoffEvent(eventId)
            dbTools.syncDbLocally()
            await sendBotMsg(context.application.bot, generateListText(eventId))
            # next schedule is being PLAYED, 2 hours before starting the game
            context.application.job_queue.run_once(taskEventEvolution, when=((dbEvents[eventId]['start'] - timedelta(hours=2))-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'PLAYED', 'eventId': eventId})

        elif newStatus == 'PLAYED':
            await sendBotMsg(context.application.bot, phrases.haveFun(hours_mins=dbEvents[eventId]['start'].strftime('%H:%M')))
            # next schedule is being DONE, at 10 AM the morning of the day after the start of the game
            context.application.job_queue.run_once(taskEventEvolution, when=((dbEvents[eventId]['start'] + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'DONE', 'eventId': eventId})

        elif newStatus == 'DONE':
            await sendBotMsg(context.application.bot, phrases.rememberToPay())

def reScheduleFutureEvents(application: Application):

    reloadTelegramBotServer(application)

    # schedule next SyncDB
    application.job_queue.run_once(taskEventEvolution, when=timedelta(seconds=5), data={'action': 'reSchedule', 'run': False})

    # Schedule next events status change
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
            dbTools.syncDbLocally()
            # Event next step is to be PLAYED
            application.job_queue.run_once(taskEventEvolution, when=((dbEvents[eventId]['start'] - timedelta(hours=2))-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'PLAYED', 'eventId': eventId})

        elif dbEvents[eventId]['status'] == 'PLAYED':
            # Event next step is to be DONE, at 10 AM the morning after the start of the game
            application.job_queue.run_once(taskEventEvolution, when=((dbEvents[eventId]['start'] + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)-datetime.now()), data={'action': 'newEventStatus', 'newStatus': 'DONE', 'eventId': eventId})

async def handlerMembersUpdate(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # First check that this is the Beach Volley group
    if update.chat_member.chat.id == TELEGRAM_BEACH_GROUP_ID:
        user = update.chat_member.new_chat_member.user

        if update.chat_member.new_chat_member.status == ChatMember.MEMBER:
            # User added to the group
            dbTools.addOrUpdateUser(user=update.chat_member.new_chat_member.user)
            await update.effective_chat.send_message(phrases.welcome(userName=getUserHTMLTag(user.id)), parse_mode=ParseMode.HTML)

        elif update.chat_member.new_chat_member.status == ChatMember.ADMINISTRATOR:
            # User promoted to admin
            dbTools.changeMemberRank(user=user, rank='Admin')

        elif update.chat_member.new_chat_member.status == ChatMember.BANNED:
            # User removed from the group
            memberNickname = dbMembers[user.id]['nickname']
            dbTools.changeMemberRank(user=user, rank='Banned')
            await update.effective_chat.send_message(phrases.goodbye(userName=getUserHTMLTag(user.id)), parse_mode=ParseMode.HTML)

async def botCommand_sendlist(update: Update, context: ContextTypes.DEFAULT_TYPE, args):

    eventId = getEventId(update, args.eventId)

    if args.sync:
        dbTools.syncDbLocally()

    await sendBotMsg(context.application.bot, generateListText(eventId))

async def botCommand_localdb(update: Update, context: ContextTypes.DEFAULT_TYPE, args):

    localdb = f'dbMembers: {json.dumps(dbMembers, indent=1, default=str)}\n'
    localdb += f'dbEvents: {json.dumps(dbEvents, indent=1, default=str)}'
    MAX_LENGTH = 3950

    chunks = [localdb[i:i + MAX_LENGTH] for i in range(0, len(localdb), MAX_LENGTH)]
    for c in chunks:
        await sendBotMsg(context.application.bot, f'<code>{c}</code>', chatId=TELEGRAM_API_OWNER, messageThreadId=None)

async def botCommand_sendmsg(update: Update, context: ContextTypes.DEFAULT_TYPE, args):

    await sendBotMsg(context.application.bot, args.msg)

async def botCommand_addevent(update: Update, context: ContextTypes.DEFAULT_TYPE, args):

    try:
        startDate = datetime.strptime(args.date, '%Y-%m-%d').date()
    except ValueError:
        # The string doesn't match the format
        raise CommandNotValid('The date needs to follow the format yyyy-mm-dd')

    dbTools.addNewEvent(startDate)
    await sendBotMsg(context.application.bot, 'new event added', chatId=TELEGRAM_API_OWNER, messageThreadId=None)

async def botCommand_reload(update: Update, context: ContextTypes.DEFAULT_TYPE, args):

    reScheduleFutureEvents(context.application)
    await sendBotMsg(context.application.bot, 'Reload executed', chatId=TELEGRAM_API_OWNER, messageThreadId=None)

async def handlerAdminsBeachVolleyCommands(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Check if the chatId is from the API owner
    chatId = update.effective_user.id
    if chatId != TELEGRAM_API_OWNER:
        return

    messageText = update.effective_message.text

    # Split the command string into a list of arguments
    args_list = shlex.split(messageText)

    try:
        # Parse the list of arguments
        args = volleyBotAdminParser.parse_args(args_list)

        if args.command == '/sendlist':
            await botCommand_sendlist(update, context, args)

        elif args.command == '/localdb':
            await botCommand_localdb(update, context, args)

        elif args.command == '/sendmsg':
            await botCommand_sendmsg(update, context, args)

        elif args.command == '/addevent':
            await botCommand_addevent(update, context, args)

        elif args.command == '/reload':
            await botCommand_reload(update, context, args)

        elif args.command == '/help':
            await sendBotMsg(context.application.bot, generateAdminBotHelp(), chatId=TELEGRAM_API_OWNER, messageThreadId=None)

        else:
            await sendBotMsg(context.application.bot, 'Unknown command. Use /help for a list of available commands.', chatId=TELEGRAM_API_OWNER, messageThreadId=None)

    except CommandNotValid as e:
        await sendBotMsg(context.application.bot, e.response, chatId=TELEGRAM_API_OWNER, messageThreadId=None)

    except ParserError as e:
        await sendBotMsg(context.application.bot, 'Your command format is wrong', chatId=TELEGRAM_API_OWNER, messageThreadId=None)

async def botCommand_addme(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime:datetime, chatId:int, args:argparse.Namespace):

    eventId = getEventId(update, args.eventId)

    # Check if the player is already in the list as ON_LIST
    if dbEvents[eventId]['list'].get(chatId, {}).get('status', '-1') == 'ON_LIST':
        raise CommandNotValid('You are already on the list !')

    dbTools.addMemberToList(msgTime, eventId, chatId)
    await sendBotMsg(context.application.bot, generateListText(eventId))

async def botCommand_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime: datetime, chatId:int, args:argparse.Namespace):

    eventId = getEventId(update, args.eventId)

    # Checks if the player is present on the list, if present it should not be status 'REMOVED'
    if not dbEvents[eventId]['list'].get(chatId, {}).get('status', '-1') == 'ON_LIST':
        raise CommandNotValid('You are not even on the list !')

    # Check emoji
    if args.emoji is None:
        raise CommandNotValid('You forgot to send me the emoji')

    if emoji.is_emoji(args.emoji) is False:
        raise CommandNotValid(f'{args.emoji} is not an emoji !')

    dbTools.confirmMember(msgTime, eventId, chatId, args.emoji, dbEvents[eventId]['status'] == 'CUTOFF')
    await sendBotMsg(context.application.bot, generateListText(eventId))

async def botCommand_remove(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime: datetime, chatId:int, args:argparse.Namespace):

    eventId = getEventId(update, args.eventId)

    # Checks if the player is even present on the list
    if not dbEvents[eventId]['list'].get(chatId, {}).get('status', '-1') == 'ON_LIST':
        raise CommandNotValid('You are not even on the list !')

    dbTools.removeMemberFromList(msgTime, eventId, chatId)
    await sendBotMsg(context.application.bot, generateListText(eventId))

async def botCommand_addbkp(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime:datetime, chatId:int, args:argparse.Namespace):

    eventId = getEventId(update, args.eventId)

    if args.name is None:
        raise CommandNotValid('You forgot to send the bkp name')

    bkpStatus = dbEvents[eventId]['bkp'].get(chatId, {}).get(args.name, {}).get('status', '-1')

    if bkpStatus == 'ON_LIST':
        raise CommandNotValid(f'Your bkp "{args.name}" is already on the list !')

    dbTools.addMemberToList(msgTime, eventId, chatId, bkpNickname=args.name)
    await sendBotMsg(context.application.bot, generateListText(eventId))

async def botCommand_confirmbkp(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime:datetime, chatId:int, args:argparse.Namespace):

    eventId = getEventId(update, args.eventId)

    if args.name is None:
        raise CommandNotValid('You forgot to send the bkp name')

    if args.emoji is None:
        raise CommandNotValid('You forgot to send me the emoji')

    if emoji.is_emoji(args.emoji) is False:
        raise CommandNotValid(f'{args.emoji} is not an emoji !')

    if args.name not in dbEvents[eventId]['bkp'].get(chatId, {}):
        raise CommandNotValid('''You don't have this bkp on the list''')

    dbTools.confirmMember(msgTime, eventId, chatId, args.emoji, dbEvents[eventId]['status'] == 'CUTOFF', args.name)
    await sendBotMsg(context.application.bot, generateListText(eventId))

async def botCommand_removebkp(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime:datetime, chatId:int, args:argparse.Namespace):

    eventId = getEventId(update, args.eventId)

    if args.name is None:
        raise CommandNotValid('You forgot to send the bkp name')

    if dbEvents[eventId]['bkp'].get(chatId, {}).get(args.name, {}).get('status', 'REMOVED') == 'REMOVED':
        raise CommandNotValid(f'''You don't have any "{args.name}" as bkp on the list''')

    dbTools.removeMemberFromList(msgTime, eventId, chatId, args.name)
    await sendBotMsg(context.application.bot, generateListText(eventId))

async def botCommand_changenickname(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime:datetime, chatId:int, args):

    if args.nickname is None:
        raise CommandNotValid('You forgot to send your new nickname')

    if len(args.nickname) > 50:
        raise CommandNotValid('Your nickname is too long!')

    oldNickname = dbMembers[chatId]['nickname']
    dbTools.changeMemberNickname(msgTime, chatId, args.nickname)

    await sendBotMsg(context.application.bot, phrases.changeNickname(oldNickname, args.nickname))

async def botCommand_stats(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime:datetime, chatId:int, args):

    stats = dbTools.generateMemberStats(update.effective_user)

    await sendBotMsg(context.application.bot, stats)

async def botCommand_complaint(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime:datetime, chatId:int, args):

    if args.text is None:
        raise CommandNotValid('You forgot to send the complaint text')

    await sendBotMsg(context.application.bot, phrases.complaint())

    with open('art/refund_512.png', 'rb') as photoFile:
        await context.application.bot.send_photo(chat_id=TELEGRAM_BEACH_GROUP_ID, message_thread_id=TELEGRAM_LIST_TOPIC_ID, photo=photoFile, parse_mode=ParseMode.HTML)

async def botCommand_indianpoll(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime:datetime, chatId:int, args):

    await context.bot.send_poll(
        chat_id=TELEGRAM_BEACH_GROUP_ID,
        question='Indian Takeaway Menu Poll',
        options=indianTakeawayMenuOptions,
        is_anonymous=False, # Optional: defaults to True
        allows_multiple_answers=True, # Optional: defaults to False
        disable_notification=True,
        open_period=600,
    )

async def parseBotCommand(update: Update, context: ContextTypes.DEFAULT_TYPE, msgTime: datetime, chatId:int, commandString:str):

    # Split the command string into a list of arguments
    args_list = shlex.split(commandString)

    try:
        # Parse the list of arguments
        args = volleyBotParser.parse_args(args_list)

        # Handle the commands
        if args.command == '/addme':
            await botCommand_addme(update, context, msgTime, chatId, args)

        elif args.command == '/confirm':
            await botCommand_confirm(update, context, msgTime, chatId, args)

        elif args.command == '/remove':
            await botCommand_remove(update, context, msgTime, chatId, args)

        elif args.command == '/addbkp':
            await botCommand_addbkp(update, context, msgTime, chatId, args)

        elif args.command == '/confirmbkp':
            await botCommand_confirmbkp(update, context, msgTime, chatId, args)

        elif args.command == '/removebkp':
            await botCommand_removebkp(update, context, msgTime, chatId, args)

        elif args.command == '/changenickname':
            await botCommand_changenickname(update, context, msgTime, chatId, args)

        elif args.command == '/stats':
            await botCommand_stats(update, context, msgTime, chatId, args)

        elif args.command == '/indianpoll':
            await botCommand_indianpoll(update, context, msgTime, chatId, args)

        elif args.command == '/complaint':
            await botCommand_complaint(update, context, msgTime, chatId, args)

        elif args.command == '/help':
            await sendBotMsg(context.application.bot, generateBotHelp())

        else:
            await sendBotMsg(context.application.bot, 'Unknown command. Use /help for a list of available commands.')

    except CommandNotValid as e:
        await sendBotMsg(context.application.bot, e.response)

    except ParserError as e:
        if args_list[0] in COMMANDS_MAP:
            await sendBotMsg(context.application.bot, f'Your command format is wrong\n{generateBotHelp(args_list[0])}')
        else:
            await sendBotMsg(context.application.bot, 'Unknown command. Use /help for a list of available commands.')

async def handlerBeachVolleyCommands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ''' This function will be called for every text message in the specified topic '''

    # set msgTime in case an async code runs between now and the orderDatetime
    msgTime = datetime.now()

    # Filtering topic to only consider THE LIST commands
    # topicId = update.effective_message.message_thread_id
    # if topicId != TELEGRAM_LIST_TOPIC_ID:
    #     # This is not comming from THE LIST topic, ignore
    #     return

    # Getting the userId, if not present the user should be added (db and locally)
    chatId = update.effective_user.id
    if chatId not in dbMembers:
        dbTools.addOrUpdateUser(update.effective_user)

    messageText = update.effective_message.text.replace(f'@{context.bot.username}', '')
    dbTools.addCommandLogs(msgTime, chatId, messageText)

    #print(f'[{msgTime}] Received message in topic {topicId} from {chatId}: {messageText}')
    await parseBotCommand(update, context, msgTime, chatId, messageText)

def main():

    # Create the application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Prepare Event tasks
    reScheduleFutureEvents(application)

    # manage new/removal of members in the group chat
    application.add_handler(ChatMemberHandler(handlerMembersUpdate, ChatMemberHandler.CHAT_MEMBER))

    # handler for admins commands
    application.add_handler(MessageHandler(filters.COMMAND & filters.Chat(TELEGRAM_API_OWNER), handlerAdminsBeachVolleyCommands))

    # manage command send to the beachvolley group chat, the topic can be filtered inside the handler
    application.add_handler(MessageHandler(filters.COMMAND & filters.Chat(TELEGRAM_BEACH_GROUP_ID), handlerBeachVolleyCommands))

    # add error handler
    application.add_error_handler(errorHandler) 

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('Server shut down.')