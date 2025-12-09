from datetime import datetime, timedelta, date, time
from telegram import User
import json
import html

from tools import createPostgresSQLConnection, dbEvents, dbMembers

# dbMembers {
#   chatId_0: {'nickname': nickname, 'rank': rank},
#   chatId_1: {'nickname': nickname, 'rank': rank},
# }

# dbEvents {
#   eventId: {
#       'place': str,
#       'start': obj,
#       'end': obj,
#       'online': obj,
#       'cutoff': obj,
#       'players': int,
#       'price': float,
#       'status': 'NEW|ONLINE|CUTOFF|PLAYED|DONE',
#       'list': {
#               chatId_0: {'emoji': value, 'status': 'ON_LIST|REMOVED', 'orderDatetime': obj},
#               chatId_1: {'emoji': value, 'status': 'ON_LIST|REMOVED', 'orderDatetime': obj},
#               },
#       },
#       'bkp': {
#               chatId_0: {
#                   bkpNickname_0: {'emoji': value, 'status': 'ON_LIST|REMOVED', 'orderDatetime': obj},
#                   bkpNickname_1: {'emoji': value, 'status': 'ON_LIST|REMOVED', 'orderDatetime': obj},
#               },
#               chatId_1: {
#                   bkpNickname_0: {'emoji': value, 'status': 'ON_LIST|REMOVED', 'orderDatetime': obj},
#                   bkpNickname_1: {'emoji': value, 'status': 'ON_LIST|REMOVED', 'orderDatetime': obj},
#               },
#       },
#   }

def checkEventStatus():

    sql = '''   UPDATE events
                SET status = CASE
                                WHEN status in ('NEW', 'ONLINE', 'CUTOFF', 'PLAYED') AND to_timestamp((startDatetime::DATE+1)::text||' 10:00:00', 'YYYY-MM-DD HH24:mi:ss') <= %(now)s THEN 'DONE'
                                WHEN status in ('NEW', 'ONLINE', 'CUTOFF') AND (startDatetime - interval '2 hours') <= %(now)s THEN 'PLAYED'
                                WHEN status in ('NEW', 'ONLINE') AND cutoffDatetime <= %(now)s THEN 'CUTOFF'
                                WHEN status = 'NEW' AND onlineDatetime <= %(now)s THEN 'ONLINE'
                                ELSE status
                            END,
                    lastUpdateDatetime = %(now)s
                WHERE (
                        (status = 'NEW' AND onlineDatetime <= %(now)s)
                        OR
                        (status in ('NEW', 'ONLINE') AND cutoffDatetime <= %(now)s)
                        OR
                        (status in ('NEW', 'ONLINE', 'CUTOFF') AND (startDatetime - interval '2 hours') <= %(now)s)
                        OR
                        (status in ('NEW', 'ONLINE', 'CUTOFF', 'PLAYED') AND to_timestamp((startDatetime::DATE+1)::text||' 10:00:00', 'YYYY-MM-DD HH24:mi:ss') <= %(now)s)
                    ) '''
    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {'now': datetime.now()})

def syncDbLocally():

    dbMembers.clear()
    dbEvents.clear()

    with createPostgresSQLConnection() as conn:
        # ---------------------------------- Members --------------------------------- #
        sql = ''' SELECT chatId, nickname, rank FROM members WHERE rank != 'Banned' '''
        with conn.cursor() as cur:
            cur.execute(sql)
            for r in cur.fetchall():
                dbMembers[r[0]] = {'nickname': r[1], 'rank': r[2]}

        # ---------------------------------- Events ---------------------------------- #
        sql = ''' SELECT id, place, startDatetime, endDatetime, onlineDatetime, cutoffDatetime, players, price, status FROM events WHERE status IN ('NEW', 'ONLINE', 'CUTOFF', 'PLAYED') '''
        with conn.cursor() as cur:
            cur.execute(sql)
            for r in cur.fetchall():
                dbEvents[r[0]] = {'place': r[1], 'start': r[2], 'end': r[3], 'online': r[4], 'cutoff': r[5], 'players': r[6], 'price': r[7], 'status': r[8], 'list': dict(), 'bkp': dict()}

        # ----------------------------------- Lists ---------------------------------- #
        if dbEvents:
            sql = ''' SELECT idEvents, idMembers, bkpNickname, emoji, orderDatetime, status FROM lists WHERE idEvents = ANY(%(idEvents)s) ORDER BY orderDatetime ASC '''
            with conn.cursor() as cur:
                cur.execute(sql, {'idEvents': list(dbEvents.keys())})
                for r in cur.fetchall():
                    if r[2] is None:
                        # goes into list
                        dbEvents[r[0]]['list'][r[1]] = {'emoji': r[3], 'status': r[5], 'orderDatetime': r[4]}
                    else:
                        # gose into bkp
                        if r[1] not in dbEvents[r[0]]['bkp']:
                            dbEvents[r[0]]['bkp'][r[1]] = dict()
                        dbEvents[r[0]]['bkp'][r[1]][r[2]] = {'emoji': r[3], 'status': r[5], 'orderDatetime': r[4]}

def updateEventStatus(eventId:int, newStatus:str):

    sql = '''   UPDATE Events
                SET status = %(newStatus)s,
                    lastUpdateDatetime = %(now)s
                WHERE id = %(eventId)s '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {  'eventId': eventId,
                                'newStatus': newStatus,
                                'now': datetime.now()})
        conn.commit()

    # local
    dbEvents[eventId]['status'] = newStatus

def cutoffEvent(eventId):

    sql = '''   WITH t AS (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (ORDER BY case
                                                WHEN bkpNickname IS NULL AND status = 'ON_LIST' AND emoji IS NOT NULL THEN 0        -- member + confirmed
                                                WHEN bkpNickname IS NOT NULL AND status = 'ON_LIST' AND emoji IS NOT NULL THEN 1    -- bkp + confirmed
                                                WHEN bkpNickname IS NULL AND status = 'ON_LIST' AND emoji IS NULL THEN 2		    -- member + onList
                                                WHEN bkpNickname IS NOT NULL AND status = 'ON_LIST' AND emoji IS NULL THEN 3	    -- bkp + onList
                                                WHEN bkpNickname IS NULL AND status = 'REMOVED' THEN 4								-- member + removed
                                                WHEN bkpNickname IS NOT NULL AND status = 'REMOVED' THEN 5							-- member + removed
                                                ELSE 6                                                                              -- else ?
                                            END ASC, orderDatetime ASC) AS rn
                    FROM lists
                    WHERE idEvents = %(eventId)s
                )
                UPDATE lists l
                SET orderDatetime = %(now)s + make_interval(secs=>t.rn::FLOAT/200)
                FROM t
                WHERE l.id = t.id '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {  'eventId': eventId,
                                'now': datetime.now()})
        conn.commit()

# ---------------------------------------------------------------------------- #
#                                    Members                                   #
# ---------------------------------------------------------------------------- #
def addOrUpdateUser(user: User):

    sql = '''   INSERT INTO members (chatId, nickname, rank, createDatetime, lastUpdateDatetime)
                VALUES (%(chatId)s, %(nickname)s, 'Member', %(now)s, %(now)s) ON CONFLICT (chatId) DO UPDATE SET rank = 'Member', lastUpdateDatetime = %(now)s '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {  'chatId': user.id,
                                'nickname': user.first_name,
                                'now': datetime.now()})
        conn.commit()

    # local
    # If the user was banned, the record would not be locally, the nickname would be unsync until the next syncDB call
    dbMembers[user.id] = {'nickname': user.first_name, 'rank': 'Member'}

def changeMemberRank(user: User, rank):

    sql = '''   UPDATE members
                SET rank = %(rank)s,
                    lastUpdateDatetime = %(now)s
                WHERE chatId = %(chatId)s '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {'now': datetime.now(), 'chatId': user.id, 'rank': rank})

        conn.commit()

    # local
    if rank == 'Banned':
        # user was banned
        dbMembers.pop(user.id, None)
    else:
        dbMembers[user.id]['rank'] = rank

def changeMemberNickname(msgTime:datetime, chatId:int, newNickname:str):

    sql = '''   UPDATE members
                SET nickname = %(newNickname)s,
                    lastupdatedatetime = %(now)s
                WHERE chatId = %(chatId)s '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {  'newNickname': newNickname,
                                'chatId': chatId,
                                'now': msgTime})
        conn.commit()

    # local
    dbMembers[chatId]['nickname'] = newNickname

# ---------------------------------------------------------------------------- #
#                                     Lists                                    #
# ---------------------------------------------------------------------------- #
def addMemberToList(msgTime:datetime, eventId:int, chatId:int, bkpNickname:str=None):

    sql = '''   INSERT INTO lists (idEvents, idMembers, bkpNickname, createDatetime, orderDatetime, lastUpdateDatetime, status)
                VALUES (%(eventId)s, %(chatId)s, %(bkpNickname)s, %(msgTime)s, %(msgTime)s, %(msgTime)s, 'ON_LIST')
                ON CONFLICT (idEvents, idMembers, bkpNickname) DO UPDATE SET status = 'ON_LIST', lastUpdateDatetime = %(msgTime)s, orderDatetime = %(msgTime)s '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {  'eventId': eventId,
                                'chatId': chatId,
                                'bkpNickname': bkpNickname,
                                'msgTime': msgTime})
        conn.commit()

    # local
    if bkpNickname is None:
        # request is for a member of the group -> to LIST
        # If the player was removed from the list, do not update the emoji
        if chatId in dbEvents[eventId]['list']:
            # The user was REMOVED from the list
            dbEvents[eventId]['list'][chatId]['status'] = 'ON_LIST'
            dbEvents[eventId]['list'][chatId]['orderDatetime'] = msgTime
        else:
            # The user was not on the list
            dbEvents[eventId]['list'][chatId] = {'emoji': None, 'status': 'ON_LIST', 'orderDatetime': msgTime}
    else:
        # request is for a bkp -> to BKP
        # If the player was removed from the list, do not update the emoji
        if dbEvents[eventId]['bkp'].get(chatId, {}).get(bkpNickname):
            # The bkp was REMOVED from the list
            dbEvents[eventId]['bkp'][chatId][bkpNickname]['status'] = 'ON_LIST'
            dbEvents[eventId]['bkp'][chatId][bkpNickname]['orderDatetime'] = msgTime
        else:
            # The bkp was not on the list

            # Add user to the bkp dict if not present
            if chatId not in dbEvents[eventId]['bkp']:
                dbEvents[eventId]['bkp'][chatId] = dict()

            dbEvents[eventId]['bkp'][chatId][bkpNickname] = {'emoji': None, 'status': 'ON_LIST', 'orderDatetime': msgTime}

def confirmMember(msgTime:datetime, eventId:int, chatId:int, emojiTxt:str, cutoff:bool, bkpNickname:str=None):

    sql = '''   UPDATE lists
                SET emoji = %(emojiTxt)s,
                    orderDatetime = CASE WHEN %(cutoff)s THEN %(now)s ELSE orderDatetime END,
                    lastUpdateDatetime = %(now)s
                WHERE idEvents = %(eventId)s
                AND idMembers = %(chatId)s
                AND (
                    bkpNickname IS NULL AND %(bkpNickname)s::TEXT IS NULL
                    OR
                    bkpNickname = %(bkpNickname)s
                ) '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {  'eventId': eventId,
                                'chatId': chatId,
                                'emojiTxt': emojiTxt,
                                'bkpNickname': bkpNickname,
                                'cutoff': cutoff,
                                'now': msgTime})
        conn.commit()

    # local
    if bkpNickname is None:
        # request is for a member of the group -> LIST
        dbEvents[eventId]['list'][chatId]['emoji'] = emojiTxt

        # if the event is in status CUTOFF, the orderDatetime is also updated !
        if cutoff:
            dbEvents[eventId]['list'][chatId]['orderDatetime'] = msgTime
    else:
        # request is for a bkp -> BKP
        dbEvents[eventId]['bkp'][chatId][bkpNickname]['emoji'] = emojiTxt

        # if the event is in status CUTOFF, the orderDatetime is also updated !
        if cutoff:
            dbEvents[eventId]['bkp'][chatId][bkpNickname]['orderDatetime'] = msgTime


def removeMemberFromList(msgTime:datetime, eventId:int, chatId:int, bkpNickname:str=None):

    sql = '''   UPDATE lists
                SET status = 'REMOVED',
                    lastUpdateDatetime = %(msgTime)s
                WHERE idEvents = %(eventId)s
                AND idMembers = %(chatId)s
                AND (
                    bkpNickname IS NULL AND %(bkpNickname)s::TEXT IS NULL
                    OR
                    bkpNickname = %(bkpNickname)s
                ) '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {  'eventId': eventId,
                                'chatId': chatId,
                                'bkpNickname': bkpNickname,
                                'msgTime': msgTime})
        conn.commit()

    # local
    if bkpNickname is None:
        # remove from list
        dbEvents[eventId]['list'][chatId]['status'] = 'REMOVED'

    else:
        # remove from bkp
        dbEvents[eventId]['bkp'][chatId][bkpNickname]['status'] = 'REMOVED'

def generateMemberStats(user: User):

    sql = '''   SELECT
                    (SELECT createDatetime FROM members WHERE chatId = %(chatId)s) AS createDatetime,
                    count(1) FILTER (WHERE bkpNickname IS NULL) AS noPlayed,
                    count(1) FILTER (WHERE bkpNickname IS NOT NULL) AS noBkpPlayed,
                    max(e.endDatetime) AS datetimeLastGame,
                    (SELECT count(1) FROM lists WHERE idMembers = %(chatId)s AND status = 'REMOVED' AND bkpNickname IS NOT NULL AND emoji IS NOT NULL) AS removedWithEmoji
                FROM lists l
                JOIN events e ON (e.id = l.idEvents AND e.endDatetime < %(now)s)
                WHERE l.idMembers = %(chatId)s
                AND l.status = 'ON_LIST'
                AND l.emoji IS NOT null '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {'chatId': user.id, 'now': datetime.now()})
            statResults = cur.fetchone()

    statText = '<pre>'
    statText += f'Stats for {dbMembers[user.id]['nickname']}\n'
    statText += f'  times played:      {statResults[1]}\n'
    statText += f'  bkps invited:      {statResults[2]}\n'
    statText += f'  confirm backdown:  {statResults[4]}\n'
    statText += f'  member since:      {statResults[0].strftime("%Y-%m-%d")}\n'
    statText += f'  last game:         {f'{(datetime.now() - statResults[3]).days} days ago' if statResults[3] else 'NA'}'
    statText += '</pre>'

    return statText

def addCommandLogs(msgTime: datetime, chatId:int, command:str):

    sql = ''' INSERT INTO commandLogs (chatId, command, createDatetime) VALUES (%(chatId)s, %(command)s, %(msgTime)s) '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {'chatId': chatId, 'command': command, 'msgTime': msgTime})
        conn.commit()

def addNewEvent(startDate:date):

    sql = ''' INSERT INTO EVENTS (
                place,
                startDatetime,
                endDatetime,
                onlineDatetime,
                cutoffDatetime,
                players,
                price,
                createdatetime,
                lastupdatedatetime,
                status
            ) VALUES (
                'Crespi',
                %(startDatetime)s,
                %(endDatetime)s,
                %(onlineDatetime)s,
                %(cutoffDatetime)s,
                24,
                202.5,
                %(now)s,
                %(now)s,
                'NEW'
            )
            RETURNING id '''

    with createPostgresSQLConnection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, {
                'startDatetime': datetime.combine(startDate, time(11, 30, 0)),
                'endDatetime': datetime.combine(startDate, time(13, 00, 0)),
                'onlineDatetime': datetime.combine(startDate - timedelta(days=5), time(19, 00, 0)),
                'cutoffDatetime': datetime.combine(startDate - timedelta(days=2), time(20, 00, 0)),
                'now': datetime.now()})
            eId = cur.fetchone()[0]
        conn.commit()

    # local
    dbEvents[eId] = {
        'place': 'Crespi',
        'start': datetime.combine(startDate, time(11, 30, 0)),
        'end': datetime.combine(startDate, time(13, 00, 0)),
        'online': datetime.combine(startDate - timedelta(days=5), time(19, 00, 0)),
        'cutoff': datetime.combine(startDate - timedelta(days=2), time(20, 00, 0)),
        'players': 24,
        'price': 202.5,
        'status': 'NEW',
        'list': dict(),
        'bkp': dict(),
    }
