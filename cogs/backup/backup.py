# cogs/backup/backup.py

import discord
from discord.ext import commands
from discord import app_commands
import asyncio
from typing import Optional, Dict, Any
import os
import httpx # HTTPリクエスト用
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import threading
from pathlib import Path
import json
import re # ロールメンション解析のために必要
import urllib.parse # URLエンコードのために必要

# =========================================================
# 設定 (ご自身の情報に置き換えてください)
# =========================================================
CLIENT_ID = 1418479907930898463
# ★★★ Renderの環境変数からCLIENT_SECRETを読み込むように変更 ★★★
# ローカルでテストする場合は os.environ.get("CLIENT_SECRET", "あなたのローカルシークレット")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "GAue03xOW8pnX8h-v2sg8sEsvkAa0Uqd") 
# ★★★ ⚠️ Renderにデプロイ後、このREDIRECT_URIをあなたのRenderドメインに書き換えてください ★★★
# 例: https://taka-vending-pro.onrender.com/auth
REDIRECT_URI = "https://taka-vending-pro.onrender.com/auth"
# OAuth2 スコープ (identify: ユーザー情報, guilds.join: サーバーにユーザーを追加)
SCOPES = "identify guilds.join"

# =========================================================
# ファイルパス (main.py と同じ階層にあることを想定)
# =========================================================
BASE_DIR = Path(__file__).parent.parent.parent
JSON_FILE_PATH = BASE_DIR / "verified_users.json"
SUCCESS_HTML_PATH = BASE_DIR / "success.html"
ERROR_HTML_PATH = BASE_DIR / "error.html"

# FastAPIアプリケーションの初期化
app = FastAPI()

# グローバル変数
bot_instance: Optional[commands.Bot] = None
verification_roles: Dict[int, int] = {} # Key: guild_id, Value: role_id
ERROR_HTML_PLACEHOLDER = "Discordとの認証に失敗しました。"


# =========================================================
# ファイル操作関数
# =========================================================
def load_users() -> Dict[str, Dict[str, Any]]:
    """JSONファイルからユーザーデータを読み込む"""
    if not JSON_FILE_PATH.exists():
        return {}
    try:
        with open(JSON_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        print("WARNING: verified_users.json が破損しています。空のデータを返します。")
        return {}

def save_users(users: Dict[str, Dict[str, Any]]):
    """ユーザーデータをJSONファイルに保存する"""
    with open(JSON_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)

def _get_html_content(path: Path) -> str:
    """HTMLファイルの内容を読み込む"""
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            print(f"ERROR: HTMLファイル {path.name} の読み込み中にエラーが発生しました: {e}")
            return "<h1>Error: HTML file not found (Read Error).</h1>"
    return f"<h1>Error: HTML file not found: {path.name} is missing.</h1>"

# ファイル読み込み
SUCCESS_HTML_TEMPLATE = _get_html_content(SUCCESS_HTML_PATH)
ERROR_HTML_TEMPLATE = _get_html_content(ERROR_HTML_PATH)


# =========================================================
# FastAPI エンドポイント
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def home_page():
    return "<h1>Discord Backup Bot Web Server Running</h1>"

@app.get("/auth")
async def auth_callback(request: Request):
    """
    Discord OAuth2コールバックエンドポイント。
    アクセストークンを取得し、ユーザーをサーバーに参加・ロール付与させる。
    """
    code = request.query_params.get("code")
    guild_id = request.query_params.get("state")
    
    if not code or not guild_id:
        print("❌ OAuth2: codeまたはstate(guild_id)がありません。")
        return HTMLResponse(ERROR_HTML_TEMPLATE.replace(ERROR_HTML_PLACEHOLDER, "認証リンクに不備があります。もう一度お試しください。"))

    # 認証時に付与すべきロールIDを一時メモリから取得
    role_to_assign = verification_roles.get(int(guild_id))
    roles_to_send = [str(role_to_assign)] if role_to_assign else [] # ロールIDは文字列でAPIに送信

    # 1. Access Tokenの取得
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    }
    
    try:
        async with httpx.AsyncClient() as client:
            token_response = await client.post("https://discord.com/api/oauth2/token", data=data)
            token_response.raise_for_status()
            token_data = token_response.json()
            access_token = token_data.get("access_token")
            
            if not access_token:
                raise Exception("アクセストークンの取得に失敗しました。")

            # 2. ユーザー情報の取得
            user_response = await client.get(
                "https://discord.com/api/v10/users/@me", 
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_response.raise_for_status()
            user_data = user_response.json()
            user_id = user_data.get("id")
            
            if not user_id:
                raise Exception("ユーザーIDの取得に失敗しました。")

            # 3. ユーザーをサーバーに追加＆ロール付与
            try:
                add_user_response = await client.put(
                    f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}",
                    headers={"Authorization": f"Bot {bot_instance.http.token}"},
                    json={"access_token": access_token, "roles": roles_to_send} 
                )
                
                if add_user_response.status_code not in [201, 204]:
                    add_user_response.raise_for_status()
                
                print(f"✅ OAuth2: ユーザー {user_data.get('username', 'Unknown')} をサーバー {guild_id} に追加・ロール付与を試行。")
                
                # 4. ユーザー情報を JSON に保存または更新
                users = load_users()
                users[user_id] = {
                    "username": user_data.get("username", user_data.get("global_name", "Unknown User")),
                    "role_id": str(role_to_assign) if role_to_assign else users.get(user_id, {}).get("role_id"), 
                    "guild_id": guild_id, 
                    "access_token": access_token 
                }
                save_users(users)

                return HTMLResponse(SUCCESS_HTML_TEMPLATE) 
                
            except httpx.HTTPStatusError as e:
                error_msg = "認証は完了しましたが、ボットの**権限不足**によりロールの付与・サーバー参加に失敗しました。管理者に連絡してください。" if e.response.status_code == 403 else f"認証・サーバー参加時にDiscord APIエラーが発生しました: {e.response.status_code}"
                print(f"❌ サーバー/ロール付与エラー: {e}")
                return HTMLResponse(ERROR_HTML_TEMPLATE.replace(ERROR_HTML_PLACEHOLDER, error_msg))

    except httpx.HTTPStatusError as e:
        error_message = f"認証プロセス中にDiscord APIエラーが発生しました: {e.response.status_code} - {e.response.text[:100]}..."
        print(f"❌ OAuth2 HTTPエラー: {e}")
        return HTMLResponse(ERROR_HTML_TEMPLATE.replace(ERROR_HTML_PLACEHOLDER, error_message))
    except Exception as e:
        print(f"❌ OAuth2 予期せぬエラー: {e}")
        return HTMLResponse(ERROR_HTML_TEMPLATE.replace(ERROR_HTML_PLACEHOLDER, f"予期せぬエラーが発生しました: {str(e)}"))

# cogs/backup/backup.py の class BackupCog から setup 関数直前までを置き換えてください

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
        description="認証メッセージを送信し、認証後に付与するロールを設定します。"
    )
    @app_commands.describe(
        role="認証後に付与したいロール",
        # title と description をオプショナルに変更
        title="認証メッセージのタイトル（任意。未入力時は定型文を使用）",
        description="認証メッセージの説明（任意。未入力時は定型文を使用）",
        image="認証メッセージに表示する画像URL（任意）"
    )
    async def verify(
        self, 
        interaction: discord.Interaction, 
        role: discord.Role, # ロールのみを選択可能に固定
        title: Optional[str] = None, # 任意に変更
        description: Optional[str] = None, # 任意に変更
        image: Optional[str] = None
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)

        # 1. デフォルトメッセージの定義
        DEFAULT_TITLE = "@everyone バックアップ認証のお願い"
        DEFAULT_DESCRIPTION = (
            "**日本語:**\n"
            "- このサーバーが飛んだ(制限時・新鯖作成など)場合を考えてメンバーバックアップとなります。新鯖等では初期は配布させて頂きますので、是非どうぞ。\n"
            "ベッドロックのように、認証すると無差別にサーバーに追加する訳ではありません。サーバーが飛んだ時にメンバーバックアップとしてしか使用しないので認証お願いします\n\n"
            "**English:**\n"
            "- **Backup Certification Request**\n"
            "- This is a member backup in case this server goes down (restriction, creation of a new server, etc.). We will distribute the initials in the new server, etc., so please do so.\n"
            "It is not like a bedlock, which indiscriminately adds members to the server when they authenticate. It will only be used as a member backup in case the server goes down, so please authenticate."
        )

        # ユーザー入力がなければデフォルトを使用
        final_title = title if title else DEFAULT_TITLE
        final_description = description if description else DEFAULT_DESCRIPTION
        
        # 1. ロールIDの特定 (型がRoleなのでそのまま取得)
        role_id = role.id
            
        # 2. 認証リンクの作成 (URLエラーの修正済み)
        encoded_redirect_uri = urllib.parse.quote(REDIRECT_URI, safe='') 
        encoded_scopes = urllib.parse.quote(SCOPES, safe='') 

        auth_url = (
            f"https://discord.com/oauth2/authorize?client_id={CLIENT_ID}&"
            f"redirect_uri={encoded_redirect_uri}&response_type=code&scope={encoded_scopes}&"
            f"state={interaction.guild_id}"
        )

        # デバッグ情報
        print("-" * 50)
        print(f"DEBUG: AUTH_URL (Encoded) generated: {auth_url}")
        print("-" * 50)
        
        # 3. ロールIDを一時メモリに保存 (認証時に利用)
        verification_roles[interaction.guild_id] = role_id

        # 4. 認証メッセージの作成
        embed = discord.Embed(
            title=final_title,
            description=final_description,
            color=discord.Color.green()
        )
        if image:
            embed.set_image(url=image)

        # 認証ボタン
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="認証", style=discord.ButtonStyle.link, url=auth_url))

        # 5. メッセージ送信
        # ★★★ 誰もが見られるように ephemeral=False に固定 ★★★
        await interaction.followup.send(
            embed=embed, 
            view=view,
            ephemeral=False 
        )
        
        # 6. 管理者への通知
        await interaction.followup.send(
            embed=discord.Embed(
                description=f"✅ 認証メッセージを送信しました。\n認証時、ロール: **{role.name}** が付与されます。",
                color=discord.Color.blue()
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
        target_role: Optional[discord.Role] = None, # ロールは任意
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
        
        # 付与するロールIDのリスト
        roles_to_assign = [str(target_role.id)] if target_role else []
        
        # 呼び戻し処理の実行
        for user_id in user_ids_to_call:
            if user_id in users_data:
                user_info = users_data[user_id]
                access_token = user_info.get("access_token")
                
                member = guild.get_member(int(user_id))
                
                if member:
                    # サーバーにいる場合はロールを付与 (target_roleが指定されている場合のみ)
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
                    # サーバーにいない場合は、OAuth2の機能でサーバーに復帰させる
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
                            
                # ユーザーのバックアップ情報更新
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
    # ★★★ 修正箇所: Renderは環境変数PORTでポートを指定するため、それを優先 ★★★
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
