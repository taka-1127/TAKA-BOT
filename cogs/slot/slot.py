import discord
from discord.ext import commands
from discord import app_commands # 追加
import datetime
import re

class SlotCog(commands.Cog):
    """スロットチャンネル作成（公開/非公開・期間（1週間/1ヶ月/永久）・追加ユーザー対応）"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="slot_create", description="スロットチャンネルを作成します") # 変更
    @app_commands.describe( # Optionの代わりにdescribe
        owner="スロットチャンネルの所有者",
        category="作成するカテゴリー",
        is_public="公開(True)/非公開(False)",
        duration="期間を選択（1週間/1ヶ月/永久）",
        additional_users="追加ユーザーをメンションで（任意・複数可）"
    )
    @app_commands.choices(duration=[ # choicesも使用
        app_commands.Choice(name="1週間", value="1週間"),
        app_commands.Choice(name="1ヶ月", value="1ヶ月"),
        app_commands.Choice(name="永久", value="永久"),
    ])
    async def slot_create(
        self,
        interaction: discord.Interaction, # 変更: ctx -> interaction
        owner: discord.Member, # 変更: Optionを外し、型ヒントを付ける
        category: discord.CategoryChannel, # 変更: Optionを外し、型ヒントを付ける
        is_public: bool, # 変更: Optionを外し、型ヒントを付ける
        duration: str, # 変更: Optionを外し、型ヒントを付ける
        additional_users: str = None,
    ):
        if interaction.user.guild_permissions is None or not interaction.user.guild_permissions.administrator: # 変更: 権限チェック
            return await interaction.response.send_message("❌ 管理者のみ実行できます。", ephemeral=True) # 変更

        # --- 期間の計算 ---
        today = datetime.date.today()
        duration_text = ""
        if duration == "1週間":
            end_date = today + datetime.timedelta(days=7)
            duration_text = f"{end_date.month}月{end_date.day}日まで"
        elif duration == "1ヶ月":
            end_date = today + datetime.timedelta(days=30) # 簡略化のため30日
            duration_text = f"{end_date.month}月{end_date.day}日まで"
        elif duration == "永久":
            duration_text = "永久"

        # チャンネル名の設定
        channel_name = f"slot-{owner.name.lower().replace(' ', '-')}-{owner.id}様 {duration_text}"

        # --- 権限のオーバーライト ---
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False), # 変更: ctx.guild -> interaction.guild
            owner: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            self.bot.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }

        if additional_users:
            user_ids = re.findall(r"<@!?(\d+)>", additional_users)
            for uid in user_ids:
                try:
                    m = await interaction.guild.fetch_member(int(uid)) # 変更: ctx.guild -> interaction.guild
                    overwrites[m] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                except discord.NotFound:
                    continue

        if is_public:
            overwrites[interaction.guild.default_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True) # 変更

        # --- チャンネル作成 ---
        try:
            ch = await category.create_text_channel(name=channel_name, overwrites=overwrites)
            embed = discord.Embed(title="スロット作成しました", description=f"このチャンネルは{owner.display_name}様専用です", color=discord.Color.green())
            await ch.send(embed=embed)
            await interaction.response.send_message(f"✅ スロットチャンネル **{ch.name}** を作成しました！所有者: {owner.mention}", ephemeral=True) # 変更
        except discord.Forbidden:
            await interaction.response.send_message("❌ チャンネル作成に必要な権限がありません。", ephemeral=True) # 変更
        except Exception as e:
            await interaction.response.send_message(f"❌ エラーが発生しました: {e}", ephemeral=True) # 変更

async def setup(bot): # 変更: async setup
    await bot.add_cog(SlotCog(bot)) # 変更: await