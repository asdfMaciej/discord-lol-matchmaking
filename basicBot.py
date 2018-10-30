# Created by maciej01, 2018.
import discord
import asyncio
import re
import random
import sqlite3
import shelve
from pprint import pprint
from discord.ext.commands import Bot
from discord.ext import commands
import platform


def chunks(l, n):
    for i in range(0, len(l), n):
        yield l[i:i + n]


def validate_team_count(position_dict):
    for pos, players in position_dict.items():
        if len(players) != 2:
            return False
    return True


def search_and_remove(player, position_dict, current_pos):
    for position, players in position_dict.items():
        for n in range(len(players)):
            p = players[n]
            if player[0] == p[0] and player[2] == p[2]:
                if position == current_pos:
                    continue
                position_dict[position].pop(n)
                return position_dict


def rank_to_skill(rank, position):
    modifier = 1
    modifiers = {
        'adc': 0.9,
        'top': 0.9,
        'jungle': 1,
        'mid': 1,
        'support': 0.95
    }

    if 'substitute' in rank:
        rank = rank.split('substitute')[0]
        modifier = 0.89
    if 'sub' in rank:
        rank = rank.split('sub')[0]
        modifier = 0.92

    base_skill = 1.7
    if rank == 'challenger':
        return base_skill**5, 2
    elif rank == 'master':
        return base_skill**5

    skill_dict = {
        'b': 0, 's': 1, 'g': 2.6, 'p': 3.2, 'd': 4.1
    }
    skill_exp = skill_dict[rank[0]]
    skill_exp += float(abs(5 - float(rank[1])) * 0.15)

    return float((base_skill**skill_exp)**modifiers[position])


def team_to_skill(t):
    t_sum_skill = 0
    for position, player in t.items():
        t_sum_skill += rank_to_skill(player[1], position)
    return t_sum_skill


def swap_position(team1, team2, position):  # better to be sure about pointers
    t1 = team1.copy()
    t2 = team2.copy()
    pos_t1 = t1[position].copy()
    t1[position] = t2[position].copy()
    t2[position] = pos_t1
    return t1, t2


def get_skill_differences(team1, team2):
    diffs = {'jungle': 0, 'mid': 0, 'support': 0, 'adc': 0, 'top': 0}
    for pos in diffs.keys():
        diffs[pos] = rank_to_skill(
            team1[pos][1], pos) - rank_to_skill(team2[pos][1], pos)
    return diffs


def team_to_text(team1, team2):
    positions = ('top', 'mid', 'jungle', 'adc', 'support')
    emojis = {
        'top': ':top:',
        'mid': ':heavy_minus_sign:',
        'jungle': ':evergreen_tree:',
        'adc': ':gun:',
        'support': ':syringe:'}
    t1s = team_to_skill(team1)
    t2s = team_to_skill(team2)
    team_diff = (t1s - t2s)
    prct_team_diff = abs(abs(t1s - t2s) / max(t1s, t2s)) * 100
    diffs = get_skill_differences(team1, team2)
    diffs_abs = {}
    for key, val in diffs.items():
        diffs_abs[key] = abs(val)
    template = "({}) {} `[{:<7}]` > **`{:.>16}`**  **<==>** **`{:.<16}`** {} ({})"
    emotes = {True: ":white_check_mark:", False: ":x:"}
    winners = {
        True: ":one:   Przewagę skilla ma drużyna pierwsza.   :one:",
        False: ":two:   Przewagę skilla ma drużyna druga.   :two:"}
    txt_end = "---------------------------------------------------------------------------------------\n"
    txt_end += ":one:        PIERWSZA  DRUŻYNA                  VS            DRUGA  DRUŻYNA   :two:\n\n"
    txt_end += "---------------------------------------------------------------------------------------\n"
    for pos in positions:
        dif = diffs[pos]
        txt = template.format(team1[pos][1].split('sub')[0].upper(), emotes[dif >= 0], pos.upper(),
                              # emojis[pos],
                              team1[pos][0], team2[pos][0], emotes[dif < 0], team2[pos][1].split('sub')[0].upper())
        txt_end += txt + "\n\n"
    txt_end += "---------------------------------------------------------------------------------------\n\n"
    txt_end += winners[team_diff >= 0] + "\n"
    txt_end += "Jest to przewaga wynosząca {:.2f}% - team 1 ma rating {:.3f}, team 2 ma rating {:.3f}.\n".format(
        round(prct_team_diff, 2), t1s, t2s)
    txt_end += "Najmniejszą różnicę ma {}, a największą ma {}.\n".format(
        min(diffs_abs, key=diffs_abs.get), max(diffs_abs, key=diffs_abs.get))
    txt_end += "---------------------------------------------------------------------------------------\n\n"
    txt_end += "Powodzenia! :fire: :beers:"
    return txt_end


class Matchmaking:
    def __init__(self, phandler):
        self.phandler = phandler

    async def matchmake(self, players):
        new_format = []
        for p in players:
            new_format.append([p[1], p[2], p[3]])
        team1, team2 = self._matchmake(new_format)
        txt = team_to_text(team1, team2)
        for t in (team1, team2):
            arr = []
            for p in t.values():  # really unefficient but im dumb and this routine happens rarely
                for pl in players:
                    print(pl)
                    print(p)
                    if pl[1] == p[0]:
                        arr.append(str(pl[0]))  # id
            self.phandler.current_lobby.append(arr)
        pprint(self.phandler.current_lobby)
        await self.phandler.say(txt)

    def _matchmake(self, players):
        positions = ('adc', 'support', 'mid', 'jungle', 'top')

        position_dict = {}
        fill_players = []

        for position in positions:
            position_dict[position] = []

        for player in players:
            position_dict[player[2][0]].append(player)
            if player[2][0] == 'fill':
                fill_players.append(player)

        while fill_players:
            for position, players in position_dict.items():
                if not fill_players:
                    break
                if len(players) < 2:
                    players.append(fill_players[0])
                    fill_players.pop(0)

        established_roles = []
        while not validate_team_count(position_dict):
            needed_pos = ""
            subs = []
            for position, players in position_dict.items():
                if len(players) < 2:
                    needed_pos = position
            iteration_pos = True
            fill_level = 1
            while iteration_pos:
                if not subs:
                    if fill_level in (1, 2):
                        break_out = False
                        for position, players in sorted(
                            position_dict.items(), key=lambda item: len(
                                item[1]), reverse=True):
                            if position == needed_pos or position in established_roles:
                                continue
                            for player in players:
                                if player[2][fill_level -
                                             1] == needed_pos and 'sub' not in player[1]:
                                    player[1] += 'sub'
                                    subs.append(player)
                                    break_out = True
                                if break_out:
                                    break
                            if break_out:
                                break
                    elif fill_level == 3:
                        break_out = False
                        for position, players in sorted(
                            position_dict.items(), key=lambda item: len(
                                item[1]), reverse=True):
                            if position == needed_pos:
                                continue
                            for player in players:
                                if player[2][1] == 'fill' or player[2][0] == 'fill':
                                    subs.append(player)
                                    break_out = True
                                if break_out:
                                    break
                            if break_out:
                                break
                    elif fill_level == 4:
                        for position, players in position_dict.items():
                            if len(players) > 2:
                                for player in players:
                                    player[1] += 'substitute'
                                    subs.append(player)

                for sub_n in range(len(subs)):
                    sub = subs[sub_n]
                    position_dict[needed_pos].append(sub)
                    position_dict = search_and_remove(
                        sub, position_dict, needed_pos)
                    subs.pop(sub_n)
                    if len(position_dict[needed_pos]) == 2:
                        for sub in subs:
                            if 'substitute' in sub[1]:
                                sub[1] = sub[1].split('substitute')[0]
                        subs = []
                        iteration_pos = False
                        break

                if not subs:
                    fill_level += 1
            established_roles.append(needed_pos)

        team_1 = {}
        team_2 = {}

        for position in positions:
            team_1[position] = []
            team_2[position] = []

        for position, players in position_dict.items():
            first = True
            for p in players:
                if first:
                    team_1[position] = p
                else:
                    team_2[position] = p
                first = False

        while True:
            team_diff = (team_to_skill(team_1) -
                         team_to_skill(team_2)) / 2  # needed for swaps
            difs = get_skill_differences(team_1, team_2)

            break_loop = True
            for dif in difs.values():
                if abs(team_diff - dif) < abs(team_diff):
                    break_loop = False
            if break_loop:
                break

            for position, dif in difs.items():
                if abs(team_diff - dif) < abs(team_diff):
                    team_1, team_2 = swap_position(team_1, team_2, position)
                    break
        return team_1, team_2


class DBHandler:
    def __init__(self, dbname, shelfname, phandler):
        self.dbname = dbname
        self.shelfname = shelfname  # I guess pickle is insecure and shelve is using it
        self.phandler = phandler
        self.init_db()

    def init_db(self):
        self.db = sqlite3.connect(self.dbname)
        self.shelf = shelve.open(self.shelfname)

    def write_setting(self, key, value):
        self.shelf[key] = value
        self.shelf.sync()

    def read_setting(self, key):
        return self.shelf[key]

    def list_to_format(self, l):
        aaa = []
        for n in l:
            aaa.append([n[1], n[2], n[3], (n[4], n[5])])
        return aaa

    async def add_player(self, handle, nick, rank, preferred_pos, secondary_pos):
        # validate
        # add to db [or maybe edit as well, that function is redudant]

        ids = self.check_by_handle_or_nick(handle, nick)
        cur = self.db.cursor()
        if not ids:
            numeric_rank = self.phandler.rank_to_numeric(rank)
            cur.execute(
                'INSERT into players(handle, nick, rank, preferred_pos, secondary_pos, numeric_rank) values (?, ?, ?, ?, ?, ?)',
                (handle,
                 nick,
                 rank,
                 preferred_pos,
                 secondary_pos,
                 numeric_rank))
            self.db.commit()
            self.phandler.set_players(self.list_to_format(self.get_players()))
            await self.phandler.msg(
                "Dodano {} ({}) o randze {} - {}/{}.".format(
                    "<@" + handle + ">", nick, rank, preferred_pos, secondary_pos
                )
            )
        else:
            await self.phandler.error("Podana osoba istnieje już w bazie z takim nickiem lub kontem na Discordzie! Aktualizowanie...")
            numeric_rank = self.phandler.rank_to_numeric(rank)
            count = 0
            for n_id in ids:
                cur.execute(
                    'UPDATE players SET handle=?, nick=?, rank=?, preferred_pos=?, secondary_pos=?, numeric_rank=? WHERE id=?',
                    (handle,
                     nick,
                     rank,
                     preferred_pos,
                     secondary_pos,
                     int(numeric_rank),
                        n_id[0]))
                count += 1
            self.db.commit()
            self.phandler.set_players(self.list_to_format(self.get_players()))
            await self.phandler.msg(
                "Zaktualizowano {} graczy, aby posiadali dane {} ({}) o randze {} - {}/{}.".format(
                    str(count), "<@" + handle + ">", nick, rank, preferred_pos, secondary_pos
                )
            )

    def delete(self, _id, key):
        cur = self.db.cursor()
        if key == 'handle':
            cur.execute("DELETE FROM players WHERE handle=?", (_id,))
        else:
            cur.execute("DELETE FROM players WHERE nick=?", (_id,))
        pprint((key, _id))
        n = int(cur.rowcount)
        self.db.commit()
        return n

    def get_players(self, order=None):
        orders = {
            None: 'nick', 'nick': 'nick', 'rank': 'numeric_rank',
            'pos': 'preferred_pos', 'position': 'preferred_pos'
        }
        txt = "SELECT * FROM players ORDER BY " + \
            orders[order] + " asc;"  # using ? doesn't work, what the hell
        cur = self.db.cursor()
        cur.execute(txt)
        playas = cur.fetchall()
        return playas

    def check_by_handle_or_nick(self, handle, nick):
        cur = self.db.cursor()
        cur.execute(
            "SELECT id from players WHERE handle=? OR nick=?", (handle, nick))
        results = cur.fetchall()
        return results

    def custom_query(self, txt, args):
        cur = self.db.cursor()
        cur.execute(txt, args)
        results = cur.fetchall()
        return results

    async def init_tables(self):
        kurs = self.db.cursor()
        try:
            # if True:
            kurs.execute('''CREATE TABLE players
						(id integer primary key, handle integer, nick text, rank text,
						preferred_pos text, secondary_pos text, numeric_rank integer)''')
            kurs.execute('''CREATE TABLE matches
						(id integer primary key, date_time text, team1 text, team2 text,
						winner text)''')  # przechowuje glosy
            await self.phandler.msg("Stworzono tabele dla bazy " + self.dbname + ".")
        except BaseException:
            await self.phandler.error("Błąd przy tworzeniu tabeli - prawdopodobnie są już stworzone.")
        self.db.commit()

    def update_player(self, handle, nick, rank, preferred_pos, secondary_pos):
        pass

    def delete_player(self, handle, nick):
        pass

    def finish(self):
        self.db.commit()
        self.db.close()


class PeopleHandler:
    def __init__(self, client):
        self.db = DBHandler('bazabota.db', 'settings.pkl', self)
        self.mm = Matchmaking(self)
        self.client = client
        self.positions = ('adc', 'support', 'mid', 'jungle', 'top')
        self.slang = {
            'adc': 'adc',
            'support': 'support',
            'mid': 'mid',
            'jungle': 'jungle',
            'top': 'top',
            'middle': 'mid',
            'bot': 'adc',
            'sup': 'support',
            'jgl': 'jungle',
            'jg': 'jungle',
            'supp': 'support',
            'fill': 'fill'}
        self.ranks_ordered = (
            'challenger', 'master', 'd1', 'd2', 'd3', 'd4', 'd5',
            'p1', 'p2', 'p3', 'p4', 'p5', 'g1', 'g2', 'g3', 'g4', 'g5',
            's1', 's2', 's3', 's4', 's5', 'b1', 'b2', 'b3', 'b4', 'b5'
        )
        self.players = []  # useless variable created on design stage. to-do - get rid of it
        self.current_lobby = []
        self.match_in_progress = False

    async def _add(self, handle, nick, rank, preferred_pos, secondary_pos):
        if preferred_pos == secondary_pos and preferred_pos != 'fill':
            await self.error('Pierwszorzędna i drugorzędna pozycja muszą się różnić!')
            return
        if rank not in self.ranks_ordered:
            await self.error('Wprowadź poprawną rangę - np. b1, d3, g4, p5, challenger!')
            return
        if preferred_pos not in self.slang.keys():
            await self.error('Wprowadź poprawną pierwszorzędną pozycję!')
            return
        if secondary_pos not in self.slang.keys():
            await self.error('Wprowadź poprawną drugorzędną pozycję!')
            return

        preferred_pos = self.slang[preferred_pos]
        secondary_pos = self.slang[secondary_pos]
        await self.db.add_player(handle, nick, rank, preferred_pos, secondary_pos)

    def get_players(self):
        return self.players

    def set_players(self, players):
        self.players = players

    def update_player(self, handle, nick, rank, preferred_pos, secondary_pos):
        pass

    def delete_player(self, handle, nick):
        pass

    def rank_to_numeric(self, rank):
        return self.ranks_ordered.index(rank)

    async def error(self, msg):
        await self.client.say(":warning: " + msg)

    async def msg(self, m):
        await self.client.say(":ballot_box_with_check: " + m)

    async def say(self, m):
        await self.client.say(m)

    @commands.command(pass_context=True)
    async def add(self, ctx, *args):
        # $gracz @handle "nick" [pos1/pos2]|fill <[b/s/g/p/d]<1-5>/master/challenger>
        # <@handle> te handle to id uzytkownika
        if len(args) != 4:
            await self.error("Niewłaściwa ilość argumentów!")
            if len(args) > 4:
                await self.error("Pamiętaj, aby nick umieścić w cudzysłowie, a rangi oddzielić / bez spacji [lub wybrać samo fill]")
            await self.error("$add channel/(@handle \"nick\" [pos1/pos2]|fill <[b/s/g/p/d]<1-5>/master/challenger>)")
            return
        if not re.match(
            r"<@[!]?[0-9]*>",
                args[0]):  # the first regex i've ever wrote x D
            await self.error("Należy faktycznie oznaczyć jakąś osobę jako pierwszy argument! np. $add @maciej01#9791 [...]")
            print(args[0])
            return
        if '/' not in args[2] and 'fill' != args[2]:
            await self.error("Zaznacz poprawne pozycje! np. adc/mid, jungle/fill lub same fill")
            return

        handle = args[0].split('<@')[1].split(
            '>')[0] if '!' not in args[0] else args[0].split('!')[1].split('>')[0]
        nick = args[1]
        if 'fill' == args[2]:
            pos1 = 'fill'
            pos2 = 'fill'
        else:
            pos1 = args[2].split('/')[0]
            pos2 = args[2].split('/')[1]
        rank = args[3]
        await self._add(handle, nick, rank, pos1, pos2)

    @commands.command(pass_context=True)
    async def set(self, ctx, *args):
        # $set lobby/t1/t2
        if len(args) != 1:
            await self.error("Niewłaściwa ilość argumentów!")
            await self.error("$set lobby/t1/t2 oraz należy znajdować się na kanale głosowym")
            return
        if args[0] not in ('lobby', 't1', 't2'):
            await self.error("Błędny pierwszy argument!")
            await self.error("$set lobby/t1/t2 oraz należy znajdować się na kanale głosowym")
            return
        user = ctx.message.author
        channel = user.voice.voice_channel
        if not channel:
            await self.error("Należy być połączonym z kanałem głosowym!")
            return
        self.db.write_setting(args[0], channel)
        await self.msg("Ustawiono kanał " + channel.name + " jako " + str(args[0]) + ".")

    @commands.command(pass_context=True)
    async def channels(self, ctx, *args):
        keys = ('lobby', 't1', 't2')
        for k in keys:
            await self.client.say(':speaker: Kanał dla [{}] to :loudspeaker: :notes: {}'.format(k, self.db.read_setting(k).name))

    @commands.command(pass_context=True)
    async def lobby(self, ctx, *args):
        # $lobby @gr1 @gr2 ... @gr10
        ids = []
        try:
            if len(args) == 1:
                if args[0] in ('chan', 'channel', 'kanał'):
                    ids = self.channel_members(ctx)
                    print(ids)
                    raise Exception()
            print(args)
            if len(args) != 10:
                await self.error("Niewłaściwa ilość graczy - @gr1 @gr2 ... @gr10. Zamiast 10 jest " + str(len(args)) + ".")
                return
            for arg in args:
                if not re.match(r"<@[!]?[0-9]*>", arg):
                    await self.error("Argument \"" + str(arg) + "\" nie oznacza osoby na Discordzie.")
                    return
                else:
                    ids.append(arg.split('<@')[1].split('>')[
                               0] if '!' not in arg else arg.split('!')[1].split('>')[0])
            if len(ids) != len(set(ids)):
                await self.error("Gracze powtarzają się!")
                return
        except BaseException:
            pass  # goto for poor people
        if len(ids) != 10:
            await self.error("Niewłaściwa ilość graczy - @gr1 @gr2 ... @gr10. Zamiast 10 jest " + str(len(ids)) + ".")
            return
        hehe = self.db.custom_query(
            "SELECT * from players where handle=?" +
            " OR handle=?" *
            9,
            ids)
        if len(hehe) != 10:
            await self.error("Niektórych graczy nie ma w bazie! Dodaj ich używając $add")
            return
        await self.msg("Rozpoczynanie dobierania... :thinking:")
        print("coozak")
        await self.mm.matchmake(self.db.list_to_format(hehe))

    @commands.command(pass_context=True)
    async def list(self, ctx, *args):
        # aaa.append([n[1], n[2], n[3], (n[4], n[5])])
        template = ":dagger: {} ({}) - {}, ranga {}\n"
        playas = self.db.get_players(order="rank")
        form = self.db.list_to_format(playas)
        for gr in chunks(form, 5):
            txt = ""
            for player in gr:
                if player[3][0] == 'fill':
                    r = 'fill'
                else:
                    r = "{}/{}".format(player[3][0], player[3][1])
                txt += template.format(str(player[1]),
                                       "<@" + str(player[0]) + ">",
                                       r,
                                       str(player[2]))
            await self.client.say(txt)

    @commands.command(pass_context=True)
    async def delete(self, ctx, *args):
        if len(args) != 1:
            await self.error("Niewłaściwa ilość argumentów! $delete @handle/\"nick\" - to lub to")
            return
        if re.match(r"<@[!]?[0-9]*>", args[0]):
            key = "handle"
            asdf = args[0].split('<@')[1].split(
                '>')[0] if '!' not in args[0] else args[0].split('!')[1].split('>')[0]
        else:
            key = "nick"
            asdf = args[0]
        n = self.db.delete(asdf, key)
        template = ":8ball: Usunięto {} graczy z bazy danych."
        await self.client.say(template.format(str(n)))

    @commands.command(pass_context=True)
    async def initdb(self, ctx, *args):
        await self.db.init_tables()

    async def move(self, users, channel, server):
        for u in users:
            try:
                d_user = server.get_member(u)
                await self.client.move_member(d_user, channel)
            except BaseException:
                print('User fail przeniesienie ' + str(u))

    @commands.command(pass_context=True)
    async def finish(self, ctx, *args):
        if not self.match_in_progress:
            await self.error("Nie trwa obecnie żaden mecz!")
            return
        lobby = self.db.read_setting('lobby')
        server = ctx.message.server
        await self.move(self.current_lobby[0], lobby, server)
        await self.move(self.current_lobby[1], lobby, server)
        await self.assign_teams(self.current_lobby[0], True, server, lobby=True)
        await self.assign_teams(self.current_lobby[1], False, server, lobby=True)
        self.match_in_progress = False
        self.current_lobby = []
        await self.client.say(":medal: Gratulacje dla zwycięzców! :medal:")

    @commands.command(pass_context=True)
    async def start(self, ctx, *args):
        if self.match_in_progress:
            await self.error("Obecnie trwa mecz!")
            return
        if not self.current_lobby:
            await self.error("Nie wybrano żadnych zawodników! $lobby <gracz1 gracz2 ...>")
            return
        await self.msg("Przenoszenie graczy w toku...")
        channel_t1 = self.db.read_setting('t1')
        channel_t2 = self.db.read_setting('t2')
        server = ctx.message.server
        await self.move(self.current_lobby[0], channel_t1, server)
        await self.move(self.current_lobby[1], channel_t2, server)
        await self.assign_teams(self.current_lobby[0], True, server)
        await self.assign_teams(self.current_lobby[1], False, server)
        await self.client.say(":medal: Powodzenia! :medal:")
        self.match_in_progress = True

    @commands.command(pass_context=True)
    async def cancel(self, ctx, *args):
        if self.match_in_progress:
            await self.error("Obecnie trwa mecz! Użyj $finish.")
            return
        if not self.current_lobby:
            await self.error("Nie wybrano żadnych zawodników, aby móc przerwać.")
            return
        self.current_lobby = []
        await self.client.say(":satellite: Anulowano mecz.")

    @commands.command(pass_context=True)
    async def commands(self, ctx, *args):
        help_1 = """
		:8ball: $commands - wyświetla listę komend.
Zastosowanie: $commands

:8ball: $lobby - dobiera mecz oraz tworzy lobby.
Zastosowanie: $lobby channel/<@gr1 @gr2 ... @gr10>

:8ball: $add - dodaje osobę do bazy danych.
Zastosowanie: $add @handle "nick" [pos1/pos2]|fill <[b/s/g/p/d]<1-5>/master/challenger>

:8ball: $list - wypisuje listę graczy obecnych w bazie danych.
Zastosowanie: $list

:8ball: $delete - usuwa gracza z bazy danych.
Zastosowanie: $delete @handle/"nick"

:8ball: $start - zaczyna mecz, nadaje role oraz przerzuca na kanały.
Zastosowanie: $start

:8ball: $cancel - anuluje dobrane lobby.
Zastosowanie: $cancel

:8ball: $finish - kończy mecz, zabiera role oraz przerzuca na wspólny kanał.
Zastosowanie: $finish

--- konfiguracja bota, nieużyteczne: ---
initdb, set lobby/t1/t2
"""
        help_2 = """
		:white_check_mark: INSTRUKCJA :white_check_mark:

1. Dodaj graczy do bazy danych - należy zrobić to tylko raz, np. $add @Botian-haxx#5938 "hide on bush" mid/fill challenger
2. Zbierz grupę 10 osób na kanale oraz użyj komendy $lobby channel, lub dodaj ich po kolei - $lobby @Pancake#3691 @Botian-haxx#5938 ... itd
3. Wpisz $start oraz rozpocznij rozgrywkę lub $cancel aby anulować.
4. Po zakończeniu meczu użyj komendy $finish.
		"""
        await self.client.say(help_1)
        await self.client.say(help_2)

    def channel_members(self, ctx):
        user = ctx.message.author
        voice = user.voice.voice_channel
        members = voice.voice_members
        ids = []
        for m in members:
            ids.append(str(m.id))
        return ids

    async def assign_teams(self, ids, team1, server, lobby=False):
        name1 = "LoL 5v5 - Team #1"
        name2 = "LoL 5v5 - Team #2"
        t1 = discord.utils.get(server.roles, name=name1)
        t2 = discord.utils.get(server.roles, name=name2)
        team = t1 if team1 else t2
        for user in ids:
            if not lobby:
                await self.assign_role(user, team, server)
            else:
                await self.assign_role(user, t1, server, inverse=True)
                await self.assign_role(user, t2, server, inverse=True)

    async def assign_role(self, userid, role, server, inverse=False):
        user = server.get_member(str(userid))
        if not inverse:
            await self.client.add_roles(user, role)
        else:
            await self.client.remove_roles(user, role)


client = Bot(
    description="Zajebisty bot#1665",
    command_prefix="$",
    pm_help=True)
client.add_cog(PeopleHandler(client))


@client.event
async def on_ready():
    print('Logged in as ' +
          client.user.name +
          ' (ID:' +
          client.user.id +
          ') | Connected to ' +
          str(len(client.servers)) +
          ' servers | Connected to ' +
          str(len(set(client.get_all_members()))) +
          ' users')
    print('Current Discord.py Version: {} | Current Python Version: {}'.format(
        discord.__version__, platform.python_version()))
    print('https://discordapp.com/oauth2/authorize?client_id={}&scope=bot&permissions=8'.format(client.user.id))
    print('Created by maciej01')

client.run('key')
