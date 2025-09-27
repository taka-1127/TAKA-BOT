import discord
from discord.ext import commands
from discord import app_commands

class BotLinkCog(commands.Cog):
    """
    BOTが導入されているサーバーのリンクを表示するコマンド
    """
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="bot-link", description="BOTが導入されているサーバー情報と招待リンクをEmbedで表示します。")
    async def show_bot_links(self, interaction: discord.Interaction):
        """
        BOTが導入されているサーバー名と永久招待リンクをEmbedで表示します。
        """
        
        # 【修正箇所1】: 最初にdeferを実行し、Discordに応答中であることを伝える
        await interaction.response.defer(ephemeral=True)
        
        embed = discord.Embed(
            title="BOT導入済みサーバー一覧",
            color=discord.Color.blue()
        )

        for guild in self.bot.guilds:
            try:
                # 永久招待リンクを作成できるチャンネルを探す
                invite_channel = None
                for channel in guild.text_channels:
                    permissions = channel.permissions_for(guild.me)
                    if permissions.create_instant_invite:
                        invite_channel = channel
                        break

                if invite_channel:
                    # 招待リンクを作成（max_uses=0, unique=True は元のコードから採用）
                    invite = await invite_channel.create_invite(max_uses=0, unique=True)
                    embed.add_field(name=f"✅ {guild.name}", value=f"[招待リンク]({invite.url})", inline=False)
                else:
                    embed.add_field(name=f"❌ {guild.name}", value="招待リンクを作成できませんでした。", inline=False)
            except Exception as e:
                # サーバーごとのエラーをEmbedに追加
                embed.add_field(name=f"⚠️ {guild.name}", value=f"エラーが発生しました: {type(e).__name__}", inline=False)
        
        # 【修正箇所2】: defer後の最終的な応答は followup.send で一度だけ実行
        # Embedに全サーバーの情報が追加された後に送信します。
        try:
            await interaction.followup.send(embed=embed, ephemeral=True) 
        except Exception as e:
            # 最終的なメッセージ送信のエラー処理
            await interaction.followup.send(f"❌ 最終的なメッセージ送信中にエラーが発生しました: {str(e)}", ephemeral=True)

async def setup(bot):
    await bot.add_cog(BotLinkCog(bot))