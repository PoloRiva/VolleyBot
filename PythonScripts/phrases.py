import random

WELCOME_PHRASES = (
    '''Hi {userName}\nwelcome to the group''',
)

GOODBYE_PHRASES = (
    '''Fly high {userName} 🕊️''',
    '''Hasta la vista {userName} 🤖👍''',
)

HAVE_FUN = (
    '''Have fun !''',
    '''Enjoy the game !''',
)

REMEMBER_TO_PAY = (
    '''This is your ✨friendly✨ reminder to pay for yesterday's game''',
    '''Don't forget 🔫🔫🔫''',
)

CUTOFF_IN_2HRS = (
    'Confirm while you can',
    'Confiiiirm',
    'Confirm people ! 🗣️📢',
)

NO_GAMES = (
    '''Sorry {userName}, there are no games available right now 🙁''',
)

CHANGE_NICKNAME = (
    '''Ok, now I'll call you {newNickname}''',
    '''✨{newNickname}✨\n\n            ...I like it 😏''',
    '''<s>{oldNickname}</s>   ➡️   <b>{newNickname}</b>👌''',
)

COMPLAINT = (
    '''Sorry you had that experience''',
    '''HAHAHA, that happends all the time''',
    '''That's actually Leo's fault 🙄''',
)

ONLY_ADMINS = (
    '''🔴 I'm sorry Dave, I'm afraid I can't do that''',
)

UNKNOWN_COMMAND = (
    "Sorry, I don't know what you mean by that",
    "I don't recognize that command",
    "Excuse me, were you talking to me ? Because I don't know that command",
)

def welcome(userName):
    return f'{random.choice(WELCOME_PHRASES).format(userName=userName)}\n\nCheck the <a href="https://poloriva.github.io/VolleyBot/">Website</a> for the rules, FAQs and all the info you need to get started'

def goodbye(userName):
    return random.choice(GOODBYE_PHRASES).format(userName=userName)

def haveFun(hours_mins):
    return f'Remember the game starts at {hours_mins} ☝️\n{random.choice(HAVE_FUN)}'

def rememberToPay():
    return random.choice(REMEMBER_TO_PAY)

def cutoffIn2Hrs():
    return f'Cutoff in 2 hrs, {random.choice(CUTOFF_IN_2HRS)}'

def noGamesAvailable(userName):
    return random.choice(NO_GAMES).format(userName=userName)

def changeNickname(oldNickname, newNickname):
    return random.choice(CHANGE_NICKNAME).format(oldNickname=oldNickname, newNickname=newNickname)

def complaint():
    return f'{random.choice(COMPLAINT)}\nplease accept this refund'

def onlyAdmins():
    return f'{random.choice(ONLY_ADMINS)}'

def unknownCommand():
    return f'{random.choice(UNKNOWN_COMMAND).format()}\nUse /help for a list of available commands.'
