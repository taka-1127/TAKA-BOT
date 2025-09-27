# cogs/backup/backup.py

import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, Dict, Any, List
import os
import httpx 
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import threading
from pathlib import Path
import json
import re 
import urllib.parse 

# =========================================================
# 設定 (Render/環境変数対応)
# =========================================================
# CLIENT_ID はそのまま利用
CLIENT_ID = 1418479907930898463
# Renderの環境変数からCLIENT_SECRETを読み込む
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "YOUR_LOCAL_SECRET") 
# Renderのドメインに書き換え済みであることを確認
REDIRECT_URI = "https://taka-vending-pro.onrender.com/auth" 
SCOPES = "identify guilds.join"

# =========================================================
# グローバル/ファイル設定
# =========================================================
BASE_DIR = Path(__file__).parent.parent.parent
JSON_FILE_PATH = BASE_DIR / "verified_users.json"
# ギルドIDと、認証後に付与するロールIDを保持
verification_roles: Dict[int, int] = {} 
bot_instance: Optional[commands.Bot] = None

# =========================================================
# ユーザーデータ管理関数
# =========================================================
def load_users() -> Dict[str, Any]:
    """認証済みユーザーデータをロードする"""
    if not JSON_FILE_PATH.exists():
        return {}
    try:
        with open(JSON_FILE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_users(data: Dict[str, Any]):
    """認証済みユーザーデータを保存する"""
    with open(JSON_FILE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def add_user(user_id: str, access_token: str, refresh_token: str, guild_id: str, role_id: Optional[str] = None):
    """ユーザーの認証情報を追加/更新する"""
    users = load_users()
    users[user_id] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "guild_id": guild_id,
        "role_id": role_id
    }
    save_users(users)

def remove_user(user_id: str):
    """ユーザーの認証情報を削除する"""
    users = load_users()
    if user_id in users:
        del users[user_id]
        save_users(users)

# =========================================================
# FastAPI Webサーバー設定
# =========================================================
app = FastAPI()

@app.get("/", response_class=HTMLResponse)
async def root():
    return "Discord Bot OAuth2 Web Server is running."

@app.get("/auth", response_class=HTMLResponse)
async def oauth2_callback(request: Request):
    """Discord OAuth2コールバック処理"""
    code = request.query_params.get("code")
    state = request.query_params.get("state") # stateにはguild_idが入っている
    
    if not code or not state:
        return RedirectResponse("/error?msg=OAuth2認証に失敗しました。")

    try:
        # 1. トークンの交換
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                "https://discord.com/api/v10/oauth2/token",
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": REDIRECT_URI,
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded"
                }
            )
            token_response.raise_for_status()
            token_data = token_response.json()
            access_token = token_data["access_token"]
            refresh_token = token_data["refresh_token"]

            # 2. ユーザー情報の取得
            user_response = await client.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_response.raise_for_status()
            user_data = user_response.json()
            user_id = user_data["id"]

            # 3. ユーザーをサーバーに追加 (guilds.joinスコープが必要)
            guild_id = state
            role_to_assign = verification_roles.get(int(guild_id))
            roles_list: List[str] = []
            if role_to_assign:
                roles_list.append(str(role_to_assign))

            # Botトークンを使用してユーザーをサーバーに追加
            if bot_instance and bot_instance.http.token:
                 async with httpx.AsyncClient() as client_bot:
                    add_user_response = await client_bot.put(
                        f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}",
                        headers={"Authorization": f"Bot {bot_instance.http.token}"},
                        json={"access_token": access_token, "roles": roles_list}
                    )
                    add_user_response.raise_for_status()

            # 4. ユーザー情報をファイルに保存
            add_user(user_id, access_token, refresh_token, guild_id, str(role_to_assign) if role_to_assign else None)
            
            # 成功ページを返す
            success_path = BASE_DIR / "success.html"
            if success_path.exists():
                with open(success_path, 'r', encoding='utf-8') as f:
                    html_content = f.read()
                return HTMLResponse(content=html_content, status_code=200)
            else:
                return "認証成功！Discordに戻って確認してください。"

    except httpx.HTTPStatusError as e:
        error_path = BASE_DIR / "error.html"
        error_msg = f"HTTPエラーが発生しました: {e.response.status_code}. 詳細: {e.response.text}"
        
        if error_path.exists():
            with open(error_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            html_content = html_content.replace("{ERROR_MESSAGE}", error_msg)
            return HTMLResponse(content=html_content, status_code=500)
        else:
            return f"認証プロセスでエラーが発生しました: {error_msg}"
    except Exception as e:
        error_path = BASE_DIR / "error.html"
        error_msg = f"不明なエラーが発生しました: {e}"
        if error_path.exists():
            with open(error_path, 'r', encoding='utf-8') as f:
                html_content = f.read()
            html_content = html_content.replace("{ERROR_MESSAGE}", error_msg)
            return HTMLResponse(content=html_content, status_code=500)
        else:
            return f"認証プロセスで不明なエラーが発生しました: {e}"


# =========================================================
# Discord コグ
# =========================================================
class BackupCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------
    # /backup-verify (認証メッセージ送信)
    # -------------------------
    @app_commands.command(
        name="backup-verify", 
        description="認証メッセージを送信し、認証後に付与するロールと通知を設定します。"
    )
    @app_commands.describe(
        role="認証後に付与したいロール",
        send_notice="定型文のバックアップ通知メッセージを送信しますか？ (True/False)",
        title="認証メッセージのタイトル（任意）",
        description="認証メッセージの説明（任意）",
        image="認証メッセージに表示する画像URL（任意）"
    )
    async def verify(
        self, 
        interaction: discord.Interaction, 
        role: discord.Role,
        send_notice: bool, # true/falseで選択
        title: Optional[str] = "@everyone バックアップ認証のお願い", 
        description: Optional[str] = "下のボタンを押して認証してください。", 
        image: Optional[str] = None
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)

        # 1. 定型文の定義 (ユーザーの文言をそのまま使用)
        NOTICE_MESSAGE = (
            "@everyone\n"
            "**バックアップ認証のお願い**\n"
            "-# このサーバーが飛んだ(制限時・新鯖作成など)場合を考えてメンバーバックアップとなります。新鯖等では初期は配布させて頂きますので、是非どうぞ。\n"
            "ベットロックのように、認証すると無差別にサーバーに追加する訳ではありません。サーバーが飛んだ時にメンバーバックアップとしてしか使用しないので認証お願いします\n"
            "-# **Backup Certification Request**\n"
            "-# This is a member backup in case this server goes down (restriction, creation of a new mackerel, etc.). We will distribute the initials in the new mackerel, etc., so please do so.\n"
            "It is not like a betlock, which indiscriminately adds members to the server when they authenticate. It will only be used as a member backup in case the server goes down, so please authenticate."
        )
        
        # 2. 認証リンクの作成 (Render対応済みのREDIRECT_URIを使用)
        encoded_redirect_uri = urllib.parse.quote(REDIRECT_URI, safe='') 
        encoded_scopes = urllib.parse.quote(SCOPES, safe='') 

        auth_url = (
            f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&"
            f"redirect_uri={encoded_redirect_uri}&response_type=code&scope={encoded_scopes}&"
            f"state={interaction.guild_id}"
        )
        
        # 3. ロールIDを一時メモリに保存
        verification_roles[interaction.guild_id] = role.id

        # 4. 認証メッセージの作成 (Embed + ボタン)
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue()
        )
        if image:
            embed.set_image(url=image)

        # 認証ボタン
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="認証", style=discord.ButtonStyle.link, url=auth_url))

        # 5. メッセージ送信: 認証用Embed + ボタン (ephemeral=Falseで公開)
        # 応答は interaction.channel.send を使用することで、誰でも見れるように保証
        await interaction.channel.send(
            embed=embed, 
            view=view,
        )
        
        # 6. オプションの定型文メッセージ送信
        if send_notice:
            # Trueの場合のみ、通常のテキストメッセージとして公開送信
            await interaction.channel.send(
                content=NOTICE_MESSAGE,
            )

        # 7. 管理者への完了通知
        await interaction.followup.send(
            embed=discord.Embed(
                description=f"✅ 認証メッセージを公開送信しました。\n定型文メッセージ送信: **{send_notice}**\n認証時、ロール: **{role.name}** が付与されます。",
                color=discord.Color.green()
            ),
            ephemeral=True
        )


    # -------------------------
    # /backup-call (サーバー復帰用)
    # -------------------------
    @app_commands.command(
        name="backup-call", 
        description="認証済みメンバーを呼び戻し、オプションでロールを付与します（管理者専用）。"
    )
    @app_commands.describe(
        target_role="呼び戻したメンバーに付与するロール（任意。指定がなければロール付与は行われません）",
        target_users="呼び戻したいユーザーのメンション（任意・複数可）"
    )
    async def backup_call( 
        self, 
        interaction: discord.Interaction, 
        target_role: Optional[discord.Role] = None, 
        target_users: Optional[str] = None
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        users_data = load_users()
        
        # ターゲットユーザーを特定
        if target_users:
            user_ids_to_call = re.findall(r"<@!?(\d+)>", target_users)
        else:
            user_ids_to_call = list(users_data.keys())

        if not user_ids_to_call:
            return await interaction.followup.send("❌ 呼び戻す対象の認証済みユーザーが見つかりませんでした。", ephemeral=True)

        guild = interaction.guild
        called_count = 0
        failed_count = 0
        
        roles_to_assign = [str(target_role.id)] if target_role else []
        
        for user_id in user_ids_to_call:
            if user_id in users_data:
                user_info = users_data[user_id]
                access_token = user_info.get("access_token")
                
                member = guild.get_member(int(user_id))
                
                if member:
                    if target_role:
                        try:
                            await member.add_roles(target_role)
                            called_count += 1
                        except discord.Forbidden:
                            failed_count += 1
                        except Exception:
                            failed_count += 1
                    else:
                        called_count += 1
                elif access_token:
                    try:
                        async with httpx.AsyncClient() as client:
                            add_user_response = await client.put(
                                f"https://discord.com/api/v10/guilds/{guild.id}/members/{user_id}",
                                headers={"Authorization": f"Bot {self.bot.http.token}"},
                                json={"access_token": access_token, "roles": roles_to_assign}
                            )
                            
                            if add_user_response.status_code in [201, 204]:
                                called_count += 1
                            else:
                                failed_count += 1
                                
                    except Exception:
                        failed_count += 1
                else:
                     failed_count += 1
                            
                if target_role:
                     user_info["role_id"] = str(target_role.id)
                user_info["guild_id"] = str(guild.id)
        
        save_users(users_data)
        
        message = f"✅ **{called_count}人**のメンバーの呼び戻し処理を完了しました。\n"
        if target_role:
             message += f"指定ロール（{target_role.name}）の付与も試行されました。\n"
        else:
             message += "ロールの指定がなかったため、ロール付与は行っていません。\n"
             
        if failed_count > 0:
            message += f"⚠️ **{failed_count}人**のメンバーの処理に失敗しました（権限不足、トークン期限切れなど）。"
            
        await interaction.followup.send(message)

    # -------------------------
    # /backup-count
    # ------------------------
    @app_commands.command(
        name="backup-count",
        description="認証済みメンバーの総数を表示します。"
    )
    async def backup_count(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        users = load_users()
        count = len(users)
        
        embed = discord.Embed(
            title="バックアップメンバー数",
            description=f"現在、**{count}人**のメンバーがバックアップに登録されています。",
            color=discord.Color.purple()
        )
        await interaction.followup.send(embed=embed)


# ---------------------------------------------------------
# Webサーバーを起動する関数
# ---------------------------------------------------------
def run_web_server():
    """uvicornを使用してFastAPIサーバーを起動する"""
    # Renderは環境変数PORTでポートを指定するため、それを優先
    render_port = int(os.environ.get("PORT", 8002)) 
    print(f"INFO: Webサーバーをポート {render_port} で起動します。")
    try:
        # Renderではhost="0.0.0.0"、ポートは環境変数PORT
        uvicorn.run(app, host="0.0.0.0", port=render_port, log_level="warning") 
    except Exception as e:
        print(f"ERROR: Webサーバーの起動に失敗しました: {e}")


# ---------------------------------------------------------
# コグのセットアップ関数
# ---------------------------------------------------------
async def setup(bot: commands.Bot):
    global bot_instance
    bot_instance = bot
    
    # Webサーバーを別スレッドで起動
    thread = threading.Thread(target=run_web_server)
    thread.daemon = True
    thread.start()
    
    await bot.add_cog(BackupCog(bot))