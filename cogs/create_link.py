import discord
from discord.ext import commands
from discord import app_commands # 追加

class CreateLinkCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="paypay-link-create", description="指定した金額のPayPay送金リンクを作ります。")
    @app_commands.describe(
        amount="送金する金額",
        passcode="パスコード (任意)"
    )
    async def create_link(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1], passcode: str = None): # 修正: interaction を使用、型ヒントを app_commands に
        await interaction.response.defer(ephemeral=True) # 修正: interaction.response.defer を使用
        
        paypay = self.bot.user_sessions.get(interaction.guild_id)
        if not paypay:
            await interaction.followup.send("PayPayの情報がありません。", ephemeral=True)
            return

        try:
            if passcode:
                create_link = paypay.create_link(amount=amount, passcode=passcode)
            else:
                create_link = paypay.create_link(amount=amount)

            await interaction.followup.send(
                f"✅ **送金リンク作成完了 (¥{amount:,}円)**\nリンク: <{create_link.link}>",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ エラー発生: {str(e)}", ephemeral=True)

async def setup(bot): # 修正: async setup
    await bot.add_cog(CreateLinkCog(bot))