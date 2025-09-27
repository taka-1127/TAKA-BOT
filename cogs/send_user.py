import discord
from discord.ext import commands
from discord import app_commands # 追加
from PayPaython_mobile import PayPay

class SendUserCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="paypay-send-user",
        description="指定した金額をPayPayで指定ユーザーに送金します。"
    )
    @app_commands.describe(
        amount="送金する金額",
        target_name="送金先のユーザー名または電話番号"
    )
    async def send_user_link(self, interaction: discord.Interaction, amount: app_commands.Range[float, 1], target_name: str): # 修正: interaction を使用、型ヒントを app_commands に
        await interaction.response.defer(ephemeral=True) # 修正: interaction.response.defer を使用
        
        try:
            # サーバーごとのPayPayインスタンス
            paypay: PayPay = self.bot.user_sessions.get(interaction.guild_id)
            if not paypay:
                await interaction.followup.send("PayPay情報がありません。", ephemeral=True)
                return
            
            # 応答メッセージを編集して処理中であることを示す
            await interaction.followup.send(f"👤 {target_name} に {amount:,} 円を送金処理中…", ephemeral=True)

            # フレンド以外も検索できるように is_global=True
            # amountはint型に変換する必要があるため、floatをintに丸める
            int_amount = int(amount) 
            
            user_info = paypay.search_p2puser(user_id=target_name, is_global=True, order=0)
            if not user_info:
                await interaction.edit_original_response(content=f"❌ **{target_name}** がPayPayユーザーとして見つかりませんでした。")
                return

            # 取得した external_id を使って送金
            send_result = paypay.send_money(amount=int_amount, receiver_id=user_info.external_id)

            await interaction.edit_original_response(
                content=(
                    f"✅ **送金完了!**\n**{user_info.name}** ({target_name}) に **{int_amount:,} 円** を送金しました。\n"
                    f"チャットルームID: `{send_result.chat_room_id}`"
                )
            )

        except Exception as e:
            await interaction.edit_original_response(content=f"❌ 送金エラーが発生しました: {e}")

async def setup(bot): # 修正: async setup
    await bot.add_cog(SendUserCog(bot))