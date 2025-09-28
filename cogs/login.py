# cogs/login.py
import discord
from discord.ext import commands
from discord import app_commands
from PayPaython_mobile import PayPay
import json
import os
import re # URLを検出するために追加

# token.jsonのパスを定義 (main.pyと同じ階層にあることを想定)
TOKEN_PATH = "token.json"

# PayPay認証URLのパターンを定義
PAYPAY_URL_PATTERN = re.compile(r"https://www\.paypay\.ne\.jp/portal/oauth2")

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

class LoginCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # ログイン途中のセッションを一時保存する (key: user_id, value: PayPay object)
        self.user_sessions = {} 

    # /paypay-login スラッシュコマンド
    @app_commands.command(name="paypay-login", description="PayPayにログインするための認証を開始します。")
    @app_commands.describe(
        phone="PayPay登録電話番号",
        password="PayPayパスワード"
    )
    async def paypay_login(self, interaction: discord.Interaction, phone: str, password: str):
        # 応答を公開チャンネルに残さないように、Ephemeral（自分のみ）で待機
        await interaction.response.defer(ephemeral=True)
        
        # 既にこのサーバーでセッションがある場合は警告
        if self.bot.user_sessions.get(interaction.guild_id):
            await interaction.followup.send("既にこのサーバーでPayPayにログインされています。", ephemeral=True)
            return

        try:
            # ログイン処理開始
            paypay = PayPay(phone=phone, password=password)
            
            # ログイン開始したユーザーIDで一時セッションを管理
            self.user_sessions[interaction.user.id] = paypay 
            
            # リプライメンションとEphemeralメッセージでDM送信を指示
            await interaction.followup.send(
                f"{interaction.user.mention} 届いたURLを**開かず**、このBotの**DM**にそのまま送信してください。", 
                ephemeral=True
            )
            
            # DMへ誘導メッセージを送信 (DMがブロックされている場合は失敗するが無視)
            try:
                await interaction.user.send(
                    "🔐 **PayPay認証の最終ステップです**\n"
                    "PayPayから届いた認証URLを**開かずに**、ここにそのまま貼り付けて送信してください。"
                )
            except discord.Forbidden:
                pass # DMブロックの場合は何もしない

        except Exception as e:
            await interaction.followup.send(f"❌ ログイン開始に失敗しました: {e}", ephemeral=True)
            if interaction.user.id in self.user_sessions:
                del self.user_sessions[interaction.user.id]

    # DMでURLを検知し、ログインを完了させるロジック (main.pyで処理をLoginCogに引き渡す)
    async def handle_dm_paypay_url(self, message: discord.Message, url_or_id: str):
        """main.pyから呼び出され、DMで受け取ったURLで認証を完了させる"""
        user_id = message.author.id
        
        # ログイン途中のセッションが存在するか確認
        if user_id not in self.user_sessions:
            await message.channel.send("❌ ログイン処理が開始されていません。サーバーで `/paypay-login` コマンドを実行してから、もう一度URLを送信してください。")
            return

        paypay = self.user_sessions[user_id]
        
        try:
            # 認証リンクまたはIDでログインを完了
            paypay.login(url_or_id)

            # --- token.json に保存するロジック ---
            tokens = load_tokens()
            
            # DMのため、どのサーバーに紐づけるかが不明。
            # 今回は「ユーザーID」をキーとしてPayPayトークンを保存するように変更します。
            # (ただし、元のコードではBotの全サーバーで Paypaython_mobile を利用するために「サーバーID」をキーとしていたため、
            #  ここでは元のロジックを再現するために、現在Botが参加している**最初のサーバーID**を暫定で利用します。)
            
            # ★注意: どのサーバーに紐づけるかの情報がDMからは取得できません。
            # 暫定的に、Botが参加している任意のサーバーIDを使用します。
            # 本来はユーザーがコマンドを実行したサーバーIDをどこかに保存しておくべきです。
            
            # 暫定措置: Botが参加しているサーバーの最初のIDを使用
            if self.bot.guilds:
                guild_id_to_save = str(self.bot.guilds[0].id)
            else:
                 await message.channel.send("❌ Botが参加しているサーバーがないため、PayPayアカウントを連携できません。")
                 del self.user_sessions[user_id]
                 return
                 
            # サーバーIDをキーとしてアクセストークンを保存
            tokens[guild_id_to_save] = paypay.access_token

            save_tokens(tokens)

            # Botのメインセッションに追加 (サーバーIDベースでBot全体のセッションに追加)
            self.bot.user_sessions[int(guild_id_to_save)] = paypay
            
            # 処理完了メッセージ
            await message.channel.send("🎉 **PayPayログイン成功！** **BOTとPayPayアカウントがりんくされました**")

            # 一時セッションを削除
            del self.user_sessions[user_id]

        except Exception as e:
            # エラーが起きてもセッションは維持し、再送を促す
            await message.channel.send(f"❌ ログインに失敗しました。認証リンクまたはIDが正しいか確認し、もう一度送信してください。\nエラー: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(LoginCog(bot))