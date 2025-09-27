import discord
from discord.ext import commands
from discord import app_commands # 追加

class BalanceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="paypay-balance-check", description="現在のPayPay残高を確認します。")
    async def check_balance(self, interaction: discord.Interaction): # 修正: interaction を使用
        await interaction.response.defer(ephemeral=True) # 修正: interaction.response.defer を使用

        paypay = self.bot.user_sessions.get(interaction.guild_id)
        if not paypay:
            await interaction.followup.send("PayPayの情報がありません。", ephemeral=True)
            return

        try:
            balance = paypay.get_balance()
                    
            embed = discord.Embed(title="PayPay残高", color=discord.Color.blurple())
            embed.add_field(name="💰 総残高", value=f"**{balance.all_balance:,}円**", inline=False)
            embed.add_field(name="💸 使用可能残高", value=f"{balance.useable_balance:,}円", inline=True)
            embed.add_field(name="💡 マネーライト", value=f"{balance.money_light:,}円", inline=True)
            embed.add_field(name="💵 マネー", value=f"{balance.money:,}円", inline=True)
            embed.add_field(name="⭐ ポイント", value=f"{balance.points:,}円", inline=True)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ エラー発生 : {str(e)}", ephemeral=True)

async def setup(bot): # 修正: async setup
    await bot.add_cog(BalanceCog(bot))