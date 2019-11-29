from discord.ext import commands
from discord.ext.commands import Bot, Context
from models.command import CommandInfo
from util.env import Env
from util.discord.channel import ChannelUtil
from util.discord.messages import Messages
from db.models.user import User
from db.models.stats import Stats
from db.redis import RedisDB

import config
import discord
import datetime

## Command documentation
TIPSTATS_INFO = CommandInfo(
    triggers = ["tipstats"],
    overview = "Display your personal tipping stats for a specific server.",
    details = f"This will display your personal tipping statistics from the server you send the command from. This command can't be used in DM"
)
TOPTIPS_INFO = CommandInfo(
    triggers = ["toptips"],
    overview = "Display biggest tips for a specific server.",
    details = f"This will display the biggest tip of all time, of the current month, and of the day for the current server. This command can't be used in DM"
)

class TipStats(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    async def cog_before_invoke(self, ctx: Context):
        ctx.error = False
        # TODO - account for stats banned
        # Only allow tip commands in public channels
        msg = ctx.message
        if ChannelUtil.is_private(msg.channel):
            await Messages.send_error_dm(msg.author, "You can only view statistics in a server, not via DM.")
            ctx.error = True
            return
        if ctx.command.name in ['tipstats_cmd']:
            # Make sure user exists in DB
            user = await User.get_user(msg.author)
            if user is None:
                ctx.error = True
                await Messages.send_error_dm(msg.author, f"You should create an account with me first, send me `{config.Config.instance().command_prefix}help` to get started.")
                return
            # Update name, if applicable
            await user.update_name(msg.author.name)
            ctx.user = user

    @commands.command(aliases=TIPSTATS_INFO.triggers)
    async def tipstats_cmd(self, ctx: Context):
        if ctx.error:
            await Messages.add_x_reaction(ctx.message)
            return

        msg = ctx.message
        user: User = ctx.user

        if await RedisDB.instance().exists(f"tipstatsspam{msg.author.id}{msg.guild.id}"):
            await Messages.add_timer_reaction(msg)
            await Messages.send_error_dm(msg.author, "Why don't you wait awhile before trying to get your tipstats again")
            return

        stats: Stats = await user.get_stats(server_id=msg.guild.id)
        response = ""
        if stats is None or stats.total_tips == 0:
            response = f"<@{msg.author.id}> You haven't sent any tips in this server yet, tip some people and then check your stats later"
        else:
            response = f"<@{msg.author.id}> You have sent **{stats.total_tips}** tips totaling **{stats.total_tipped_amount} {Env.currency_symbol()}**. Your biggest tip of all time is **{stats.top_tip} {Env.currency_symbol()}**"

        # TODO - no spam channels
        await msg.channel.send(response)
        await RedisDB.instance().set(f"tipstatsspam{msg.author.id}{msg.guild.id}", "as", expires=300)

    @commands.command(aliases=TOPTIPS_INFO.triggers)
    async def toptips_cmd(self, ctx: Context):
        if ctx.error:
            await Messages.add_x_reaction(ctx.message)
            return

        msg = ctx.message   
        if await RedisDB.instance().exists(f"toptipsspam{msg.channel.id}"):
            await Messages.add_timer_reaction(msg)
            return


        # This would be better to be 1 query but, i'm not proficient enough with tortoise-orm
        top_tip = await Stats.filter(
            server_id=msg.guild.id
        ).order_by('-top_tip').prefetch_related('user').limit(1).first()
        if top_tip is None:
            await RedisDB.instance().set(f"toptipsspam{msg.channel.id}", "as", expires=300)
            await msg.channel.send("There are no stats for this server yet. Send some tips first!")
            return
        # Get datetime object representing first day of this month
        now = datetime.datetime.utcnow()
        month = str(now.month).zfill(2)
        year = now.year
        first_day_of_month = datetime.datetime.strptime(f'{month}/01/{year} 00:00:00', '%m/%d/%Y %H:%M:%S')
        # Find top tip of the month
        top_tip_month = await Stats.filter(
            server_id=msg.guild.id,
            top_tip_month_at__gte=first_day_of_month
        ).order_by('-top_tip_month').prefetch_related('user').limit(1).first()
        # Get datetime object representing 24 hours ago
        past_24h = now - datetime.timedelta(hours=24)
        # Find top tip of the month
        top_tip_day = await Stats.filter(
            server_id=msg.guild.id,
            top_tip_day_at__gte=past_24h
        ).order_by('-top_tip_day').prefetch_related('user').limit(1).first()

        embed = discord.Embed(colour=0xFBDD11 if Env.banano() else discord.Colour.dark_blue())
        embed.set_author(name='Biggest Tips', icon_url="https://github.com/bbedward/Graham_Nano_Tip_Bot/raw/master/assets/banano_logo.png" if Env.banano() else "https://github.com/bbedward/Graham_Nano_Tip_Bot/raw/master/assets/nano_logo.png")
        new_line = '\n' # Can't use this directly inside f-expression, so store it in a variable
        if top_tip_day is not None:
            embed.description = f"**Last 24 Hours**\n```{top_tip_day.top_tip_day} {Env.currency_symbol()} - by {top_tip_day.user.name}```"
        if top_tip_month is not None:
            embed.description += f"{new_line if top_tip_day is not None else ''}**In {now.strftime('%B')}**\n```{top_tip_month.top_tip_month} {Env.currency_symbol()} - by {top_tip_month.user.name}```"
        embed.description += f"{new_line if top_tip_day is not None or top_tip_month is not None else ''}**All Time**\n```{top_tip.top_tip} {Env.currency_symbol()} - by {top_tip.user.name}```"

        await msg.channel.send(embed=embed)