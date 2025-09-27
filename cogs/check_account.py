import discord
from discord.ext import commands
from discord import app_commands # 追加

class AccountCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="paypay-acc-check", description="PayPayアカウントの情報を表示します。")
    async def check_account(self, interaction: discord.Interaction): # 修正: interaction を使用
        await interaction.response.defer(ephemeral=True) # 修正: interaction.response.defer を使用

        try:
            # サーバーIDからセッションを取得するロジックを保持
            paypay = self.bot.user_sessions.get(interaction.guild_id)
            if not paypay:
                await interaction.followup.send("PayPayの情報がありません。", ephemeral=True)
                return
            
            profile = paypay.get_profile()
            
            # Embed を使用して見やすくする
            embed = discord.Embed(
                title="PayPayアカウント情報",
                color=discord.Color.gold()
            )
            embed.add_field(name="ユーザー名", value=profile.name, inline=False)
            embed.add_field(name="ユーザーID", value=profile.external_user_id, inline=False)
            
            if profile.icon:
                embed.set_thumbnail(url=profile.icon)
                
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ エラー発生 : {str(e)}", ephemeral=True)
    
async def setup(bot): # 修正: async setup
    await bot.add_cog(AccountCog(bot))