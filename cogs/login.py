import discord
from discord.ext import commands
from discord import app_commands # 追加
from PayPaython_mobile import PayPay
import json
import os

class LoginCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_sessions = {} # ログイン途中のセッションを一時保存する

    @app_commands.command(name="login_paypay", description="PayPayにログインします。")
    @app_commands.describe(
        phone="PayPay登録電話番号",
        password="PayPayパスワード"
    )
    async def paypay_login(self, interaction: discord.Interaction, phone: str, password: str): # 修正: interaction を使用
        await interaction.response.defer(ephemeral=True) # 修正: interaction.response.defer を使用
        
        # 既にセッションがある場合は警告
        if self.bot.user_sessions.get(interaction.guild_id):
            await interaction.followup.send("既にこのサーバーでPayPayにログインされています。", ephemeral=True)
            return

        try:
            # ログイン処理開始
            paypay = PayPay(phone=phone, password=password)
            
            # ログイン開始したユーザーIDで一時セッションを管理
            self.user_sessions[interaction.user.id] = paypay 
            
            await interaction.followup.send(
                "✅ **ログイン開始**\n届いたURLをこのチャット（DMではなくコマンドを実行したチャンネル）に**そのまま**送信してください。**絶対に開かずに送信**してね。", 
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ ログインエラー: {str(e)}", ephemeral=True)

    # on_message リスナーは commands.Cog.listener() のままで問題ありません。
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        paypay = self.user_sessions.get(message.author.id)
        if paypay:
            url_or_id = message.content.strip()
            try:
                # 認証リンクまたはIDでログインを完了
                paypay.login(url_or_id)

                # paypay tokenを保存
                token_path = "token.json"
                if os.path.exists(token_path) and os.path.getsize(token_path) > 0:
                    with open(token_path, 'r') as f:
                        tokens = json.load(f)
                else:
                    tokens = {}

                # サーバーIDをキーとしてアクセストークンを保存
                tokens[str(message.guild.id)] = paypay.access_token

                with open(token_path, 'w') as f:
                    json.dump(tokens, f, indent=2)

                # Botのメインセッションに追加
                self.bot.user_sessions[message.guild.id] = paypay
                await message.channel.send("🎉 **PayPayログイン成功！** 今後このサーバーでPayPayコマンドが利用可能です。")

                # 一時セッションを削除
                del self.user_sessions[message.author.id]

            except Exception as e:
                # エラーが起きてもセッションは維持し、再送を促す
                await message.channel.send(f"❌ 認証リンクの処理に失敗しました: {e}\nもう一度正しいURLまたはIDを送信してください。", delete_after=10)

async def setup(bot): # 修正: async setup
    await bot.add_cog(LoginCog(bot))