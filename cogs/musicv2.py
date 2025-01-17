import discord
import wavelink
import datetime
from typing import cast
from discord.ext import commands
from utils.FormatTime import format_time
from utils.EmbedGenerator import music_embed_generator
from utils.NowPlaying import now_playing
from utils.VoiceChecker import check_voice_channel
from utils.VoiceChecker import check_voice_channel_v2
from utils.GetLyrics import get_lyrics
from views.MusicView import MusicView
from views.PlaylistView import PlaylistView
from settings import MUSIC_PASS as lavalink_password

class Music(commands.Cog):
    players: dict = {}
    bigben: bool = False
    session_id = None
    
    def __init__(self, bot):
        self.bot = bot

    async def setup_hook(self) -> None:
        nodes = [wavelink.Node(uri='http://localhost:2333', password=lavalink_password)]
        await wavelink.Pool.connect(nodes=nodes, client=self.bot, cache_capacity=100)

    async def reset_player(self, id) -> None:
        if not self.players.get(str(id)): 
            print(f'[+] Player with id: {id} does not exist')
            return
        
        print(f'[+] Player with id: {id} has been reset')
        self.players.pop(str(id))

    async def export_players(self, id):
        if not self.players.get(str(id)): 
            print(f'[+] Player with id: {id} does not exist')
            return
        
        return self.players.get(str(id))
    
    async def bigben_toggle(self):
        self.bigben = not self.bigben
        print(f'epale {self.bigben}')

    ###############################
    # - - - - E V E N T S - - - - #
    ############################### 
    @commands.Cog.listener()
    async def on_wavelink_node_ready(self, payload: wavelink.NodeReadyEventPayload) -> None:
        print(f'\nNode {payload.node.identifier} is ready!')
        self.session_id = payload.session_id

    @commands.Cog.listener()
    async def on_wavelink_track_start(self, payload: wavelink.TrackStartEventPayload) -> None:
        if self.bigben: return

        track = payload.track

        guild_id = str(payload.player.guild.id)
        lyrics = get_lyrics(self.session_id, guild_id, lavalink_password)

        vc = self.players[guild_id]['vc']
        music_channel = self.players[guild_id]['music_channel']
        user_list = self.players[guild_id]['user_list']
        embed = now_playing(track, user=user_list[0] if user_list else None)
        
        if vc.queue.mode is not wavelink.QueueMode.loop:
            user_list.pop(0)

        view_timeout = track.length / 1000 if not track.is_stream else None
        view = MusicView(timeout=view_timeout)

        view_message = await music_channel.send(embed=embed, view=view)
        view.vc = vc
        view.music_channel = music_channel
        view.user_list = user_list
        view.lyrics = lyrics
        
        self.players[guild_id]['view_message'] = view_message
        self.players[guild_id]['view'] = view
        self.players[guild_id]['lyrics'] = lyrics
        
        print(f'\n[+] Track started: {track.title}')

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload: wavelink.TrackStartEventPayload) -> None:
        if self.bigben:
            if not str(payload.player.guild.id) in self.players:
                await payload.player.disconnect(force=True)
                return
            return
        
        print(f'\n[+] Track ended: {payload.track.title}\n[!] reason: {payload.reason}\n')

        guild_id = str(payload.player.guild.id)
        vc = self.players[guild_id]['vc']
        music_channel = self.players[guild_id]['music_channel']
        view = self.players[guild_id]['view']
        view_message = self.players[guild_id]['view_message']
        
        view.clear_items()
        await view_message.edit(view=view)

        if payload.reason == 'loadFailed':
            if vc.queue.is_empty:
                await payload.player.disconnect(force=True)
                
            await music_channel.send(embed=music_embed_generator(f'⚠️ Ha ocurrido un error al cargar la pista `{payload.track.title}`.'))
            await self.reset_player(guild_id)
            return

        if payload.reason == 'stopped':
            await vc.disconnect(force=True)
            await music_channel.send(embed=music_embed_generator('🛑 La reproducción ha sido detenida.'))
            await self.reset_player(guild_id)
            return

        if vc.queue.is_empty and not vc.playing:
            await music_channel.send(embed=music_embed_generator(f'🎶 La playlist ha terminado.'))


    @commands.Cog.listener()
    async def on_wavelink_inactive_player(self, player: wavelink.Player) -> None:
        print(f'[+] Player in guild: {player.guild.name} is inactive.')
        print(f'[+] Player disconnected from: {player.channel}\n')
        await player.disconnect(force=True)
        await self.reset_player(player.guild.id)
        

    @commands.Cog.listener('on_voice_state_update')
    async def on_voice_state_update(self, member, before, after):
        guild_id = str(member.guild.id)
        if self.players.get(guild_id) is None:
            return
        
        if self.players[guild_id].get('vc') is None:
            return
        
        vc_channel = self.players[guild_id]["vc"].channel

        print(f'[+] vc: {vc_channel} ({len(vc_channel.members)})')

        if len(vc_channel.members) == 1:
            print(f'[+] Player is alone in the voice channel')
            print(f'[+] Player disconnected from: {vc_channel}')
            await self.players[guild_id]['vc'].stop()
        

    ###################################
    # - - - - C O M M A N D S - - - - #
    ###################################
    @commands.command(name='play', description='Reproduce una pista o un link de YouTube, Spotify o Soundcloud.', brief='Reproduce una pista o video', aliases=['reproducir'])
    async def play(self, ctx, *query) -> None:
        # if no query is provided return
        if len(query) < 1:
            await ctx.send(embed=music_embed_generator('No se ha especificado ninguna canción'))
            return

        # join the query into a single string
        formated_query = " ".join(query)

        # check if the user is in a voice channel
        if not ctx.author.voice:
            await ctx.send(embed=music_embed_generator('Debes estar en un canal de voz para usar este comando'))
            return
        
        guild_id = str(ctx.guild.id)

        # if the guild_id is not in the players dictionary, add it
        if not self.players.get(guild_id): 
            self.players[guild_id] = {}

        # if the bot is not connected to a voice channel
        if not self.players[guild_id].get('vc'):
            # try to connect to the voice channel
            try:
                self.players[guild_id] = {
                    'vc': await ctx.author.voice.channel.connect(cls=wavelink.Player, self_deaf=True, self_mute=True),
                    'music_channel': None,
                    'user_list': [],
                    'view': None,
                    'view_message': None,
                    'lyrics': None,
                }
            except AttributeError: # if the user is not connected to a voice channel
                await ctx.send(embed=music_embed_generator('No estas conectado a un canal de voz'))
                return
            except discord.ClientException: # if the bot can't connect to the voice channel
                await ctx.send(embed=music_embed_generator('No me pude conectar a este canal de voz. Revisa si tengo los **permisos** necesarios para entrar.'))
                return
        
        vc = self.players[guild_id]['vc']
        user_list = self.players[guild_id]['user_list']

        # this makes the bot play the next song in the queue when the current one ends
        # and does not make any recommendations
        vc.autoplay = wavelink.AutoPlayMode.partial
        vc.inactive_timeout = 10

        # Set the music channel, we make this change in order to send the music embed to the music channel
        self.players[guild_id]['music_channel'] = ctx.channel
        
        # search for the track
        tracks: wavelink.Search = await wavelink.Playable.search(formated_query)

        # if no tracks are found return
        if not tracks:
            await ctx.send(embed=music_embed_generator(f'{ctx.author.mention} ninguna pista fue encontrada con: `{formated_query}`'))
            return

        # This is the user object that will be added to the user_list
        # adding the user to the user_list is useful to display the user's name and avatar in the playlist view
        user = await self.bot.fetch_user(ctx.author.id)
        nick = ctx.author.nick if ctx.author.nick else user.display_name
        username = user.display_name if ctx.author.nick else ctx.author.name
        user_object = {
            "name": f'{nick} ({username})', 
            "pic": user.display_avatar.url, 
            "timestamp": datetime.datetime.now()
        }
        
        if isinstance(tracks, wavelink.Playlist):
            added: int = await vc.queue.put_wait(tracks)
            link = f'[{tracks.name}]({tracks.url})'
            # This codes adds the user object to the user_list multiple times
            user_list.extend([user_object] * added)
            # self.user_list.extend(user_object for _ in range(added))
            await ctx.send(embed=music_embed_generator(f'📜 Playlist {link} (**{added}** canciones) ha sido agregada a la cola'))
        else:
            track: wavelink.Playable = tracks[0]
            await vc.queue.put_wait(track)
            duration = format_time(track.length) if not track.is_stream else '🎙 live'
            description = f'💿 Se ha agregado [{track.title}]({track.uri}) **[{duration}]** de `{track.author}`'
            user_list.append(user_object)
            await ctx.send(embed=music_embed_generator(description))
        
        if not vc.playing:
            vc = cast(wavelink.Player, ctx.voice_client)
            await vc.play(vc.queue.get(), volume=100)

            
    @commands.command(name='pause', description='Pausa la pista actual.', brief='Pausa la pista actual', aliases=['pausar'])
    @check_voice_channel_v2(players=players)
    async def pause(self, ctx):
        await ctx.message.delete(delay=5)
        # if await check_voice_channel(ctx, self.players, paused=True):
        #     return

        player = self.players[str(ctx.guild.id)]

        if player['vc'].paused:
            await ctx.send(embed=music_embed_generator('La canción ya está pausada'))
            return

        await player['vc'].pause(True)
        player['view'].children[2].emoji = '<:mb_resume:1244545666982744119>'
        player['view'].paused = True
        await player['view_message'].edit(view=player['view'])

    @commands.command(name='resume', description='Reanuda la pista actual.', brief='Reanuda la pista actual', aliases=['resumir'])
    @check_voice_channel_v2(players=players)
    async def resume(self, ctx):
        await ctx.message.delete(delay=5)
        # if await check_voice_channel(ctx, self.players, paused=True):
        #     return

        player = self.players[str(ctx.guild.id)]

        if not player['vc'].paused:
            await ctx.send(embed=music_embed_generator('La canción ya está sonando'))
            return

        await player['vc'].pause(False)
        player['view'].children[2].emoji = '<:mb_pause:1244545668563861625>'
        player['view'].paused = False
        await player['view_message'].edit(view=player['view'])

    @commands.command(name='current', description='Muestra la pista actual.', brief='Muestra la pista actual', aliases=['actual'])
    async def current(self, ctx):
        if await check_voice_channel(ctx, self.players):
            return
        
        vc = self.players[str(ctx.guild.id)]['vc']
        user_list = self.players[str(ctx.guild.id)]['user_list']
        track = vc.current
        current_position = format_time(int(vc.position))

        embed = now_playing(track, user=user_list[0] if user_list else None, current=True, position=current_position)

        await ctx.send(embed=embed)

    @commands.command(name='playlist', description='Muestra la lista de reproducción.', brief='Muestra la lista de reproducción', aliases=['lista', 'queue'])
    async def playlist(self, ctx):
        if await check_voice_channel(ctx, self.players):
            return
        
        view = PlaylistView(timeout=None)
        view.vc = self.vc
        view.music_channel = self.music_channel
        await view.send()
    
    @commands.command(name='skip', description='Salta la pista actual.', brief='Salta la pista actual', aliases=['saltar'])
    async def skip(self, ctx):
        if await check_voice_channel(ctx, self.players):
            return
        
        guild_id = str(ctx.guild.id)

        if self.players[guild_id]['vc'].queue.is_empty:
            self.players[guild_id]['view'].clear_items()
            await self.players[guild_id]['view_message'].edit(view=self.players[guild_id]['view'])           
            await self.players[guild_id]['vc'].stop()
            return

        await self.players[guild_id]['vc'].play(self.players[guild_id]['vc'].queue.get())

    @commands.command(name='stop', description='Detiene la reproducción.', brief='Detiene la reproducción', aliases=['detener'])
    async def stop(self, ctx):
        if await check_voice_channel(ctx, self.players):
            return
        
        guild_id = str(ctx.guild.id)
        self.players[guild_id]['view'].clear_items()
        await self.players[guild_id]['view_message'].edit(view=self.players[guild_id]['view'])
        await self.players[guild_id]['vc'].stop()

    @commands.command(name='disconnect', description='Desconecta al bot del canal de voz.', brief='Desconecta al bot del canal de voz', aliases=['desconectar'])
    async def disconnect(self, ctx):
        if await check_voice_channel(ctx, self.players):
            return
        
        guild_id = str(ctx.guild.id)
        self.players[guild_id]['view'].clear_items()
        await self.players[guild_id]['view_message'].edit(view=self.players[guild_id]['view'])
        await self.players[guild_id]['vc'].disconnect(force=True)
        await ctx.send(embed=music_embed_generator('Bot desconectado del canal de voz.'))        

    @commands.command(name='lyrics', description='Muestra la letra de la canción actual.', brief='Muestra la letra de la canción actual', aliases=['letra', 'letras'])
    async def lyrics(self, ctx):
        lyrics = self.players[str(ctx.guild.id)]['lyrics']

        await ctx.send(embed=music_embed_generator(lyrics if lyrics else 'No se encontraron letras para esta canción'))

async def setup(bot):
    music_bot = Music(bot)
    await bot.add_cog(music_bot)
    await music_bot.setup_hook()