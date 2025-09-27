import discord
from discord.ext import commands
from discord import app_commands # 追加

class ClaimLinkCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @app_commands.command(name="paypay-qr-create", description="指定した金額のPayPay請求リンクを作ります。")
    async def claim_link(self, interaction: discord.Interaction): # 修正: interaction を使用
        await interaction.response.defer(ephemeral=True) # 修正: interaction.response.defer を使用
        
        paypay = self.bot.user_sessions.get(interaction.guild_id)
        if not paypay:
            await interaction.followup.send("PayPayの情報がありません。", ephemeral=True)
            return
        
        try:
            create_link = paypay.create_p2pcode() # 請求QRコード/リンクを生成
            
            await interaction.followup.send(
                f"✅ **請求リンク作成完了**\nリンク: <{create_link.p2pcode}>", # URLを<>で囲みリンクとして認識させる
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ エラー発生 : {str(e)}", ephemeral=True)


async def setup(bot): # 修正: async setup
    await bot.add_cog(ClaimLinkCog(bot))