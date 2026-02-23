from telegram.constants import ParseMode
from telegram.ext import Application
from telegram import Update, Bot
from datetime import datetime
import argparse
import psycopg
import json
import html

import phrases

CREDS_JSON = json.load(open('creds.json'))
TELEGRAM_TOKEN = CREDS_JSON['telegram']['bot_token']
TELEGRAM_BEACH_GROUP_ID = CREDS_JSON['telegram']['group_id']
TELEGRAM_LIST_TOPIC_ID = CREDS_JSON['telegram']['thread_id']
TELEGRAM_PAYEE_CHAT_IDS = CREDS_JSON['telegram']['payees']
TELEGRAM_API_OWNER = CREDS_JSON['telegram']['owner']

# Local db
dbMembers = dict()
dbEvents = dict()

class CommandNotValid(Exception):

    def __init__(self, response):
        self.response = response

class ParserError(Exception):

    def __init__(self, response):
        self.response = response

# ---------------------------------------------------------------------------- #
#                                    PARSERS                                   #
# ---------------------------------------------------------------------------- #
class CustomArgumentParser(argparse.ArgumentParser):
    ''' This custom class overwrites the error behaviour of ArgumentParser by raising CommandNotValid '''
    def error(self, message):
        raise ParserError(message)

volleyBotParser = CustomArgumentParser(description='Main parser for the VolleyBot commands')
subparsers = volleyBotParser.add_subparsers(title='Available commands', dest='command')

# ---------------------------------- player ---------------------------------- #
add_parser = subparsers.add_parser('/add', help='Adds another player to the list')
add_parser.add_argument('mention', nargs='?', default=None, help='Mention of the other player to be added')
add_parser.add_argument('-l', '--list', dest='eventId', type=int, help='Specifies which list (opt)')
#add_parser.add_argument('-p', '--payee', type=int, help='Specifies how many fields the user can ends up paying (opt)')

confirm_parser = subparsers.add_parser('/confirm', help='Confirms the player will play')
confirm_parser.add_argument('emoji', nargs='?', default=None, help='Emoji used for the confirmation')
confirm_parser.add_argument('-l', '--list', dest='eventId', type=int, help='Specifies which list (opt)')

remove_parser = subparsers.add_parser('/remove', help='Removes the player from the list')
remove_parser.add_argument('-l', '--list', dest='eventId', type=int, help='Specifies which list (opt)')

changenickname_parser = subparsers.add_parser('/changenickname', help='Changes you nickName')
changenickname_parser.add_argument('nickname', nargs='?', default=None, help='''New player's nickname''')

# ------------------------------------ bkp ----------------------------------- #
addbkp_parser = subparsers.add_parser('/addbkp', help='Adds a bkp to the list')
addbkp_parser.add_argument('name', nargs='?', default=None, help='Name of the bkp player')
addbkp_parser.add_argument('-l', '--list', dest='eventId', type=int, help='Specifies which list (opt)')

confirmbkp_parser = subparsers.add_parser('/confirmbkp', help='Confirms the bkp will play')
confirmbkp_parser.add_argument('name', nargs='?', default=None, help='Name of the bkp player')
confirmbkp_parser.add_argument('emoji', nargs='?', default=None, help='Emoji used for the bkp confirmation')
confirmbkp_parser.add_argument('-l', '--list', dest='eventId', type=int, help='Specifies which list (opt)')

removebkp_parser = subparsers.add_parser('/removebkp', help='Removes bkp from the list')
removebkp_parser.add_argument('name', nargs='?', default=None, help='Name of the bkp player')
removebkp_parser.add_argument('-l', '--list', dest='eventId', type=int, help='Specifies which list (opt)')

# ---------------------------------- extras ---------------------------------- #
stats_parser = subparsers.add_parser('/stats', help='Send the member stats')

complaint_parser = subparsers.add_parser('/complaint', help='Send a complaint')
complaint_parser.add_argument('text', nargs='?', default=None, help='Compaint text')

indianpoll_parser = subparsers.add_parser('/indianpoll', help='Send a the indian menu poll')

help_parser = subparsers.add_parser('/help', help='Shows the bot commands')

COMMANDS_MAP = {
    '/add':                         'Adds the player to the list',
    '/add <@mention>':              'Adds another player to the list',
    '/confirm <emoji>':             'Confirms the player assistance & payment',
    '/remove':                      'Removes the player from the list',
    '/addbkp <name>':               'Adds a bkp to the list',
    '/confirmbkp <name> <emoji>':   'Confirms the bkp assistance & payment',
    '/removebkp <name>':            'Removes the bkp from the list',
    '/changenickname <nickname>':   'Changes the user nickname',
    '/stats':                       'Shows the user stats',
    '/complaint <text>':            'Sends a formal complaint to the admins',
    '/indianpoll':                  'Sends the indian menu poll',
    '/help':                        'Prints this lists of commands',
}

ADMIN_COMMANDS_MAP = {
    '/sendlist':                'Sends the list to the groupchat',
    '/localdb':                 'Shows the local db in this chat',
    '/sendmsg "<msg>"':         'Sends a custom message to the groupchat',
    '/addevent <yyyy-mm-dd>':   'Add a new event with the default values',
    '/reload':                  'Reloads the bot server',
    '/help':                    'Prints this lists of commands',
}

# ---------------------------------- admins ---------------------------------- #
volleyBotAdminParser = CustomArgumentParser(description='Main parser for the admins VolleyBot commands')
adminSubparsers = volleyBotAdminParser.add_subparsers(title='Available admins commands', dest='command')

sendlist_parser = adminSubparsers.add_parser('/sendlist', help='Send the list (admin)')
sendlist_parser.add_argument('-l', '--list', dest='eventId', type=int, help='Specifies which list (opt)')
sendlist_parser.add_argument('-s', '--sync', dest='sync', action='store_true', help='Syncs the db states before sending the list (opt)')

localdb_parser = adminSubparsers.add_parser('/localdb', help='Send the local db (admin)')

sendmsg_parser = adminSubparsers.add_parser('/sendmsg', help='Sends a msg to a chatId')
sendmsg_parser.add_argument('msg', nargs='?', default=None, help='Message text')

addevent_parser = adminSubparsers.add_parser('/addevent', help='Add new events (admin)')
addevent_parser.add_argument('date', nargs='?', default=None, help='Date of the new event')

adminhelpevent_parser = adminSubparsers.add_parser('/help', help='Sends the list of commands (admin)')

reload_parser = adminSubparsers.add_parser('/reload', help='Add new events (admin)')

# ----------------------- Indian Takeaway Menu options ----------------------- #
indianTakeawayMenuOptions = [
    'Pollo Kurma 🍗🥥🫚',
    'Pollo Tikka Massala Piccante 🍗🥛🌶️',
    'Pollo Tikka Massala Dolce 🍗🥛🥥',
    'Pollo Makhoni 🍗🥭',
    'Pollo al Curry 🍗🍛',
    'Pollo Madras 🍗🌶️🍋',
    'Riso bianco 🍚',
    'Riso con limone 🍚🍋',
    'Plain naan 🫓',
    'Naan al formaggio 🫓🧀',
    'Naan all\'aglio 🫓🧄',
    'Other (write below)',
]

# ---------------------------------------------------------------------------- #
#                                   FUNCTIONS                                  #
# ---------------------------------------------------------------------------- #
def generateBotHelp(command=None):

    if command is None:
        helpText = 'List of available commands:'

        for c in COMMANDS_MAP:
            helpText += f'\n<code>{html.escape(c):{'<'}{30}}</code>\n    {html.escape(COMMANDS_MAP[c])}'

        helpText += '\n\n<i>any text containing spaces should be wrapped on double quotes, example:</i>\n<code>/addbkp "Volley Bot"</code>'

    else:
        helpText = f'<code>{html.escape(command):{'<'}{30}}</code>\n    {html.escape(COMMANDS_MAP[command])}'

    return helpText

def generateAdminBotHelp(command=None):

    if command is None:
        helpText = 'List of available commands:'

        for c in ADMIN_COMMANDS_MAP:
            helpText += f'\n<code>{html.escape(c):{'<'}{30}}</code>\n    {html.escape(ADMIN_COMMANDS_MAP[c])}'

    else:
        helpText = f'<code>{html.escape(command):{'<'}{30}}</code>\n    {html.escape(ADMIN_COMMANDS_MAP[command])}'

    return helpText

def createPostgresSQLConnection():
    return psycopg.connect(conninfo=CREDS_JSON['postgresql']['conninfo'])

def getEventId(update:Update, eventId:int=None):

    activeEventsId = [eId for eId in dbEvents if dbEvents[eId]['status'] in ('ONLINE', 'CUTOFF')]

    if len(activeEventsId) == 0:
        # raise CommandNotValid('There are no active lists at this time')
        raise CommandNotValid(phrases.noGamesAvailable(dbMembers[update.effective_user.id]['nickname']))

    elif eventId:
        if eventId not in activeEventsId:
            raise CommandNotValid(f'There is no list [{eventId}] valid at the moment')
        return eventId

    else:
        if len(activeEventsId) == 1:
            return activeEventsId[0]

        else:
            raise CommandNotValid('Multiple lists are active, use the flag --list <listValue> to specify which are you refering to')

def generateListText(eventId:int):

    # HEAD
    txt = f'''[{eventId}] {dbEvents[eventId]['place']} - {dbEvents[eventId]['start'].strftime('%a %d %b %H:%M')} ({round((dbEvents[eventId]['end']-dbEvents[eventId]['start']).total_seconds()/60)} mins, €{round(dbEvents[eventId]['price']/dbEvents[eventId]['players'],4)}/ea, {dbEvents[eventId]['players']}p) '''
    i = 1

    # ------------------------------- status ONLINE ------------------------------ #
    if dbEvents[eventId]['status'] == 'ONLINE':
        # LIST
        for chatId in sorted(dbEvents[eventId]['list'], key=lambda chatId: (dbEvents[eventId]['list'][chatId]['status'] == 'ON_LIST', dbEvents[eventId]['list'][chatId]['orderDatetime'])):
            wsStyle = ('', '')
            if dbEvents[eventId]['list'][chatId]['status'] == 'REMOVED':
                if dbEvents[eventId]['list'][chatId]['emoji']:
                    wsStyle = ('<s>', '</s>')
                else:
                    continue
            txt += f'''\n{i}. {wsStyle[0]}{dbMembers[chatId]['nickname']}{f' {dbEvents[eventId]['list'][chatId]['emoji']}' if dbEvents[eventId]['list'][chatId]['emoji'] else ''}{wsStyle[1]}'''
            i += 1

        bkpIndex = i

        # BKP
        flatBkp = list()
        for chatId in dbEvents[eventId]['bkp']:
            for bkpNickname in [bkpNickname for bkpNickname in dbEvents[eventId]['bkp'][chatId] if dbEvents[eventId]['bkp'][chatId][bkpNickname]['status'] == 'ON_LIST']:
                flatBkp.append({
                    'chatId': chatId,
                    'backupNickname': bkpNickname,
                    'orderDatetime':  dbEvents[eventId]['bkp'][chatId][bkpNickname]['orderDatetime'],
                    'emoji': dbEvents[eventId]['bkp'][chatId][bkpNickname]['emoji'],
                    'status': dbEvents[eventId]['bkp'][chatId][bkpNickname]['status']
                })

        for bkp in sorted(flatBkp, key=lambda item: item['orderDatetime']):

            # Skip REMOVED without emoji and add strikethrough to emoji ones
            wsStyle = ('', '')
            if bkp['status'] == 'REMOVED':
                if bkp['emoji']:
                    wsStyle = ('<s>', '</s>')
                else:
                    continue

            if i == bkpIndex:
                # Bkp Head
                txt += f'''\n\nBkp:'''
            txt += f'''\n{i}. {bkp['backupNickname']} ({dbMembers[bkp['chatId']]['nickname']}){f' {bkp['emoji']}' if bkp['emoji'] else ''}'''
            i += 1

    # ------------------------------- status CUTOFF ------------------------------ #
    elif dbEvents[eventId]['status'] == 'CUTOFF':
        flatList = list()
        lineDivider = False
        # LIST
        for chatId in dbEvents[eventId]['list']:
            flatList.append({
                'chatId': chatId,
                'status': dbEvents[eventId]['list'][chatId]['status'],
                'bkpNickname': None,
                'emoji': dbEvents[eventId]['list'][chatId]['emoji'],
                'orderDatetime': dbEvents[eventId]['list'][chatId]['orderDatetime']
            })

        # BKP
        for chatId in dbEvents[eventId]['bkp']:
            for bkpNickname in dbEvents[eventId]['bkp'][chatId]:
                flatList.append({
                    'chatId': chatId,
                    'status': dbEvents[eventId]['bkp'][chatId][bkpNickname]['status'],
                    'bkpNickname': bkpNickname,
                    'emoji': dbEvents[eventId]['bkp'][chatId][bkpNickname]['emoji'],
                    'orderDatetime': dbEvents[eventId]['bkp'][chatId][bkpNickname]['orderDatetime']
                })

        # TEXT
        # sorted() orders Falsy before Truthy !!
        for l in sorted(flatList, key=lambda item: (item['emoji'] is None, item['status'] == 'REMOVED', item['orderDatetime'])):

            # Skip REMOVED without emoji and add strikethrough to emoji ones
            wsStyle = ('', '')
            if l['status'] == 'REMOVED':
                if l['emoji']:
                    wsStyle = ('<s>', '</s>')
                else:
                    continue

            # Add line divider ?
            if lineDivider is False:
                #  Reached number of players            No more confirmations
                if i == dbEvents[eventId]['players'] or l['emoji'] is None:
                    txt += '\n✄┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈'
                    lineDivider = True

            # next line on the list
            if l['bkpNickname'] is None:
                # Not a bkp
                txt += f'''\n{i}. {wsStyle[0]}{dbMembers[l['chatId']]['nickname']}{f' {l['emoji']}' if l['emoji'] else ''}{wsStyle[1]}'''
            else:
                # A bkp
                txt += f'''\n{i}. {wsStyle[0]}{l['bkpNickname']} ({dbMembers[l['chatId']]['nickname']}){f' {l['emoji']}' if l['emoji'] else ''}{wsStyle[1]}'''
            i += 1

    return txt

def generateCutOffAlert(eventId:int):

    membersToTag = dict()    # {chatId: [bkpNickname_0, bkpNickname_0]}

    # get user from LIST with status ON_LIST that haven't confirmed yet
    for m in dbEvents[eventId]['list']:
        if dbEvents[eventId]['list'][m]['status'] == 'ON_LIST' and dbEvents[eventId]['list'][m]['emoji'] is None:
            membersToTag[m] = list()

    # get user from LIST with status ON_LIST that haven't confirmed yet
    for m in dbEvents[eventId]['bkp']:
        for bkp in dbEvents[eventId]['bkp'][m]:
            if dbEvents[eventId]['bkp'][m][bkp]['status'] == 'ON_LIST' and dbEvents[eventId]['bkp'][m][bkp]['emoji'] is None:
                if m not in membersToTag:
                    membersToTag[m] = list()
                membersToTag[m].append(bkp)

    # Format cutoff msg
    cutoffMsg = phrases.cutoffIn2Hrs()

    for m in membersToTag:
        cutoffMsg += f'\n{getUserHTMLTag(m)}'
        if membersToTag[m]:
            cutoffMsg += f' ({', '.join(membersToTag[m])})'

    return cutoffMsg

async def sendBotMsg(bot:Bot, text:str, chatId:int=TELEGRAM_BEACH_GROUP_ID, messageThreadId:int=TELEGRAM_LIST_TOPIC_ID):

    await bot.send_message(chat_id=chatId, message_thread_id=messageThreadId, text=text, parse_mode=ParseMode.HTML)

def getUserHTMLTag(userId:int):

    return f'<a href="tg://user?id={userId}">{dbMembers[str(userId)]['nickname']}</a>'

def clearTelegramApplicationJobQueue(application: Application):

    for job in application.job_queue.jobs():
        job.schedule_removal()

def appendMessageToLogFile(fileName, msg, newLineSeparator='\n'):

    with open(f'logs/{fileName}_{datetime.now().strftime('%Y%m%d')}.txt', "a") as f:
        f.write(f'{datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")} {msg}{newLineSeparator}')
