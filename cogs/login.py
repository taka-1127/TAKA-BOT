# cogs/login.py

import discord
from discord.ext import commands
from discord import app_commands
from PayPaython_mobile import PayPay
import json
import os
import asyncio 
import re 

# token.jsonのパスを定義
TOKEN_PATH = "token.json"

# PayPay URL/IDの正規表現
PAYPAY_URL_REGEX = re.compile(r"https?://\S+|^\d{6,}$") 

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

# PayPay 初期化を同期的に実行するヘルパー関数 (asyncio.to_thread用)
def init_paypay_session(phone: str, password: str) -> PayPay:
    """PayPayオブジェクトを初期化する（同期処理）"""
    return PayPay(phone=phone, password=password)

# PayPay 認証を同期的に実行するヘルパー関数 (asyncio.to_thread用)
def complete_paypay_login(paypay_session: PayPay, url_or_id: str):
    """PayPayログインを完了する（同期処理）"""
    return paypay_session.login(url_or_id)


class LoginCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ログイン途中のセッション管理
        self.user_sessions = {} 

    # /paypay-login スラッシュコマンド
    @app_commands.command(name="paypay-login", description="PayPayにログインするための認証を開始します。")
    @app_commands.describe(
        phone="PayPay登録電話番号",
        password="PayPayパスワード"
    )
    async def paypay_login(self, interaction: discord.Interaction, phone: str, password: str):
        # タイムアウト回避のため、最初に defer
        await interaction.response.defer(ephemeral=True)
        
        # 既にこのサーバーで永続セッションがある場合は警告
        if self.bot.user_sessions.get(interaction.guild_id):
            await interaction.followup.send("既にこのサーバーでPayPayにログインされています。", ephemeral=True)
            return

        try:
            # 重いPayPay初期化を別スレッドで非同期実行
            paypay = await asyncio.to_thread(init_paypay_session, phone, password)
            
            # ログイン開始したユーザーIDで一時セッションを管理
            self.user_sessions[interaction.user.id] = paypay 
            
            # DMに送信するように指示
            await interaction.followup.send(
                f"{interaction.user.mention} 届いたURLを**開かず**、このBotの**DM**に送信してください。", 
                ephemeral=True
            )
            
            # DMへ誘導メッセージを送信 
            try:
                await interaction.user.send(
                    "🔐 **PayPay認証の最終ステップです**\n"
                    "PayPayから届いた認証URLを**開かずに**、ここにそのまま貼り付けて送信してください。\n"
                    "認証後にこのBotとPayPayアカウントが連携されます。"
                )
            except discord.Forbidden:
                pass 

        except Exception as e:
            await interaction.followup.send(f"❌ ログイン開始に失敗しました: {type(e).__name__}: {e}", ephemeral=True)
            if interaction.user.id in self.user_sessions:
                del self.user_sessions[interaction.user.id]

    # DMでPayPay URL/IDを検知する Cog Listener
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1. Bot自身のメッセージ、またはサーバーメッセージは無視
        if message.author.bot or message.guild:
            return
        
        user_id = message.author.id
        content = message.content.strip()
        
        # 2. ログイン途中のユーザーで、かつ内容がURL/IDパターンに一致する場合のみ処理
        if user_id in self.user_sessions and PAYPAY_URL_REGEX.search(content):
            paypay = self.user_sessions[user_id]
            url_or_id = content
            
            # 認証リンク処理中であることをユーザーに伝える
            await message.channel.send("🔄 認証リンクを処理中です。しばらくお待ちください...")

            try:
                # 重いPayPayログイン完了処理を別スレッドで非同期実行
                await asyncio.to_thread(complete_paypay_login, paypay, url_or_id)

                # --- token.json に保存するロジック ---
                tokens = load_tokens()
                
                # 暫定措置: Botが参加しているサーバーの最初のIDを使用 (DMからはサーバーIDが取得できないため)
                # ★注意: このロジックは、Botが参加しているサーバーが一つだけの場合にのみ正しく機能します。
                if self.bot.guilds:
                    guild_id_to_save = str(self.bot.guilds[0].id) 
                else:
                    await message.channel.send("❌ Botが参加しているサーバーがないため、PayPayアカウントを連携できません。")
                    del self.user_sessions[user_id]
                    return
                     
                tokens[guild_id_to_save] = paypay.access_token
                save_tokens(tokens)

                # Botのメインセッションに追加 (永続セッション)
                self.bot.user_sessions[int(guild_id_to_save)] = paypay
                
                # 処理完了メッセージ
                await message.channel.send("🎉 **PayPayログイン成功！** **BOTとPayPayアカウントがりんくされました**")

                # 一時セッションを削除
                del self.user_sessions[user_id]

            except Exception as e:
                # エラーメッセージの改善
                error_message = str(e)
                if "PayPayLoginError" in error_message:
                    user_friendly_error = (
                        "連携に失敗しました。以下の点を確認してください:\n"
                        "1. **認証リンクまたはIDが完全にコピーされているか**\n"
                        "2. **認証リンクまたはIDが期限切れになっていないか** (最新のURLを使用してください)"
                    )
                    await message.channel.send(f"❌ ログインに失敗しました。\n\n{user_friendly_error}")
                else:
                    await message.channel.send(f"❌ ログインに失敗しました。認証リンクまたはIDが正しいか確認し、もう一度送信してください。\nエラー: {type(e).__name__}: {e}")
        
        return 
        

async def setup(bot: commands.Bot):
    await bot.add_cog(LoginCog(bot))