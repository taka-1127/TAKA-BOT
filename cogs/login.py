# cogs/login.py
import discord
from discord.ext import commands
from discord import app_commands
from PayPaython_mobile import PayPay
import json
import os
import re 
import asyncio # 🔥 修正: asyncio をインポート

# token.jsonのパスを定義 (main.pyと同じ階層にあることを想定)
TOKEN_PATH = "token.json"

# ヘルパー関数: token.json の読み書き
def load_tokens():
    if os.path.exists(TOKEN_PATH) and os.path.getsize(TOKEN_PATH) > 0:
        try:
            with open(TOKEN_PATH, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}
    return {}

def save_tokens(tokens):
    with open(TOKEN_PATH, 'w') as f:
        json.dump(tokens, f, indent=2)

# PayPay 初期化を同期的に実行するヘルパー関数
def init_paypay_session(phone: str, password: str) -> PayPay:
    """PayPayオブジェクトを初期化する（同期処理）"""
    return PayPay(phone=phone, password=password)

# PayPay 認証を同期的に実行するヘルパー関数
def complete_paypay_login(paypay_session: PayPay, url_or_id: str):
    """PayPayログインを完了する（同期処理）"""
    return paypay_session.login(url_or_id)


class LoginCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.user_sessions = {} 

    # /paypay-login スラッシュコマンド
    @app_commands.command(name="paypay-login", description="PayPayにログインするための認証を開始します。")
    @app_commands.describe(
        phone="PayPay登録電話番号",
        password="PayPayパスワード"
    )
    async def paypay_login(self, interaction: discord.Interaction, phone: str, password: str):
        # 🔥 修正: 応答の defer を時間のかかる処理の前に移動
        await interaction.response.defer(ephemeral=True)
        
        if self.bot.user_sessions.get(interaction.guild_id):
            await interaction.followup.send("既にこのサーバーでPayPayにログインされています。", ephemeral=True)
            return

        try:
            # 🔥 修正: 重いPayPay初期化を別スレッドで非同期実行 (await interaction.response.defer() の後)
            paypay = await asyncio.to_thread(init_paypay_session, phone, password)
            
            self.user_sessions[interaction.user.id] = paypay 
            
            # リプライメンションとEphemeralメッセージでDM送信を指示
            await interaction.followup.send(
                f"{interaction.user.mention} 届いたURLを**開かず**、このBotの**DM**にそのまま送信してください。", 
                ephemeral=True
            )
            
            # DMへ誘導メッセージを送信 
            try:
                await interaction.user.send(
                    "🔐 **PayPay認証の最終ステップです**\n"
                    "PayPayから届いた認証URLを**開かずに**、ここにそのまま貼り付けて送信してください。"
                )
            except discord.Forbidden:
                pass 

        except Exception as e:
            # エラー時も followup.send を使用
            await interaction.followup.send(f"❌ ログイン開始に失敗しました: {type(e).__name__}: {e}", ephemeral=True)
            if interaction.user.id in self.user_sessions:
                del self.user_sessions[interaction.user.id]

    # DMでURLを検知し、ログインを完了させるロジック
    async def handle_dm_paypay_url(self, message: discord.Message, url_or_id: str):
        user_id = message.author.id
        
        if user_id not in self.user_sessions:
            await message.channel.send("❌ ログイン処理が開始されていません。サーバーで `/paypay-login` コマンドを実行してから、もう一度URLを送信してください。")
            return

        paypay = self.user_sessions[user_id]
        
        try:
            # 🔥 修正: 重いPayPayログイン完了処理を別スレッドで非同期実行
            await asyncio.to_thread(complete_paypay_login, paypay, url_or_id)

            # --- token.json に保存するロジック ---
            tokens = load_tokens()
            
            if self.bot.guilds:
                guild_id_to_save = str(self.bot.guilds[0].id)
            else:
                 await message.channel.send("❌ Botが参加しているサーバーがないため、PayPayアカウントを連携できません。")
                 del self.user_sessions[user_id]
                 return
                 
            tokens[guild_id_to_save] = paypay.access_token
            save_tokens(tokens)

            self.bot.user_sessions[int(guild_id_to_save)] = paypay
            
            await message.channel.send("🎉 **PayPayログイン成功！** **BOTとPayPayアカウントがりんくされました**")

            del self.user_sessions[user_id]

        except Exception as e:
            await message.channel.send(f"❌ ログインに失敗しました。認証リンクまたはIDが正しいか確認し、もう一度送信してください。\nエラー: {type(e).__name__}: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(LoginCog(bot))