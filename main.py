# main.py

import discord
from discord.ext import commands
from discord import app_commands # app_commands モジュールをインポート
import os
from PayPaython_mobile import PayPay
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv 

# ==================================
# 💡 設定 & ファイルパス
# ==================================
# .env ファイルを読み込む
load_dotenv() 
# 環境変数からトークンを取得
DISCORD_TOKEN = os.getenv("TOKEN") 

if not DISCORD_TOKEN:
    print("❌ エラー: .envファイルに 'TOKEN=○○' が設定されていません。")
    # トークンがない場合は起動せずに終了します
    exit(1)

GUILDS_JSON_PATH = Path(__file__).parent / "guilds.json"
# ==================================

# IntentsとBotの初期化
intents = discord.Intents.default()
intents.message_content = True 
# commands.Bot を使用し、プレフィックスは '!'
bot = commands.Bot(command_prefix='!', intents=intents) 

bot.user_sessions = {} # PayPayセッション管理用

# token.jsonの読み込み（変更なし）
token_path = "token.json"
if os.path.exists(token_path):
    try:
        with open(token_path, 'r') as f:
            tokens = json.load(f)
        for guild_id_str, access_token in tokens.items():
            try:
                guild_id = int(guild_id_str)
                paypay = PayPay(access_token=access_token)
                bot.user_sessions[guild_id] = paypay
                print(f"自動ログイン成功: サーバーID {guild_id}")
            except Exception as e:
                print(f"ログイン失敗（サーバー {guild_id_str}）: {e}")
    except Exception as e:
        print(f"token.json 読み込み失敗: {e}")
else:
    print("token.json が存在しません。自動ログインスキップ。")


# ==================================
# 💡 guilds.json ファイル操作ヘルパー
# ==================================
def load_whitelisted_guilds() -> dict:
    """ホワイトリストのサーバーデータを読み込む"""
    if not GUILDS_JSON_PATH.exists():
        return {}
    try:
        with open(GUILDS_JSON_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ guilds.json 読み込み失敗: {e}")
        return {}

def save_whitelisted_guilds(data: dict):
    """ホワイトリストのサーバーデータを保存する"""
    try:
        with open(GUILDS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"❌ guilds.json 保存失敗: {e}")


# ==================================
# 💡 Bot イベント
# ==================================
@bot.event
async def on_ready():
    print(f'{bot.user}がログインしたよ')
    
    server_count = len(bot.guilds)
    activity = discord.Game(name=f"/help | {server_count} servers")
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print(f"ステータスを設定: /help | {server_count} servers")
    
    # スラッシュコマンドをDiscordに同期する (グローバル同期)
    try:
        # setup_hookでコグが読み込まれているため、ここで正しく同期されるはず
        synced_commands = await bot.tree.sync()
        print(f"✅ スラッシュコマンド {len(synced_commands)} 個をグローバル同期しました。")
    except Exception as e:
        print(f"❌ スラッシュコマンドのグローバル同期に失敗しました: {e}")
    

@bot.event
async def on_guild_join(guild):
    server_count = len(bot.guilds)
    activity = discord.Game(name=f"/help | {server_count} servers")
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print(f"サーバー参加: {guild.name} (ID: {guild.id})")
    print(f"ステータス更新: /help | {server_count} servers")

@bot.event
async def on_guild_remove(guild):
    server_count = len(bot.guilds)
    activity = discord.Game(name=f"/help | {server_count} servers")
    await bot.change_presence(activity=activity, status=discord.Status.online)
    print(f"サーバー離脱: {guild.name} (ID: {guild.id})")
    print(f"ステータス更新: /help | {server_count} servers")


# ==================================
# 💡 コマンドチェック関数 (スラッシュコマンドに適用)
# ==================================
@app_commands.check
async def check_whitelisted(interaction: discord.Interaction):
    """サーバーがホワイトリストに含まれているか確認する"""
    # DMでの実行は常に許可
    if not interaction.guild:
        return True 
    
    whitelisted_guilds = load_whitelisted_guilds()
    guild_id_str = str(interaction.guild_id)
    
    # ホワイトリストに含まれていれば True を返し、コマンドを許可
    if guild_id_str in whitelisted_guilds:
        return True 
    else:
        # ホワイトリスト外の場合は False を返し、コマンドを非表示・ブロック
        return False
        
# Bot本体の add_check() を使用してグローバルチェックとして適用
bot.add_check(check_whitelisted)


# ==================================
# 💡 DMコマンドリスナー (ab#agl, ab#cgl, ab#list)
# ==================================
@bot.event
async def on_message(message: discord.Message):
    # BOT自身とサーバーチャンネルからのメッセージは無視
    if message.author.bot or message.guild:
        # commands.Bot の機能を使う場合は最後にこれを実行
        await bot.process_commands(message) 
        return

    # DMでの処理
    content = message.content.strip()
    whitelisted_guilds = load_whitelisted_guilds()
    
    # --- 1. ab#agl <サーバーID> (Add Guild to List) ---
    if content.lower().startswith("ab#agl"):
        try:
            guild_id = int(content.split()[1])
        except (IndexError, ValueError):
            await message.channel.send("❌ 無効なフォーマットです。例: `ab#agl 1234567890`")
            return
            
        guild = bot.get_guild(guild_id)
        if not guild:
            await message.channel.send(f"❌ BOTがサーバーID `{guild_id}` に参加していません。BOTをサーバーに招待してください。")
            return

        guild_id_str = str(guild_id)
        if guild_id_str in whitelisted_guilds:
            await message.channel.send(f"⚠️ サーバー `{guild.name}` は既にホワイトリストに登録されています。")
            return

        # 登録
        whitelisted_guilds[guild_id_str] = {
            "name": guild.name,
            "icon_url": str(guild.icon.url) if guild.icon else None,
        }
        save_whitelisted_guilds(whitelisted_guilds)
        
        # リプライ
        await message.channel.send(
            f"✅ {message.author.mention} サーバー `{guild.name}` が**ホワイトリストに追加され、同期されました！**"
        )
        # 個別のサーバーでスラッシュコマンドを同期
        try:
             await bot.tree.sync(guild=guild) 
        except Exception as e:
            print(f"❌ サーバー {guild.name} ({guild.id}) のコマンド同期失敗: {e}")
            await message.channel.send(f"⚠️ コマンドの同期に失敗しました。BOTに `applications.commands` スコープを付与しているか確認してください。")
            
        
    # --- 2. ab#cgl <サーバーID> (Cancel Guild from List) ---
    elif content.lower().startswith("ab#cgl"):
        try:
            guild_id = int(content.split()[1])
        except (IndexError, ValueError):
            await message.channel.send("❌ 無効なフォーマットです。例: `ab#cgl 1234567890`")
            return

        guild_id_str = str(guild_id)
        if guild_id_str not in whitelisted_guilds:
            await message.channel.send(f"⚠️ サーバーID `{guild_id}` はホワイトリストに登録されていません。")
            return
            
        # 削除
        removed_name = whitelisted_guilds[guild_id_str]['name']
        del whitelisted_guilds[guild_id_str]
        save_whitelisted_guilds(whitelisted_guilds)
        
        # リプライ
        await message.channel.send(
            f"❌ {message.author.mention} サーバー `{removed_name}` が**ホワイトリストから削除されました**。"
        )
        # コマンドをサーバーから削除するために同期
        guild = bot.get_guild(guild_id)
        if guild:
             bot.tree.clear_commands(guild=guild)
             await bot.tree.sync(guild=guild)
             
    # --- 3. ab#list (List Guilds) ---
    elif content.lower() == "ab#list":
        if not whitelisted_guilds:
            await message.channel.send("ホワイトリストに登録されているサーバーはありません。")
            return
            
        embed = discord.Embed(
            title="✅ ホワイトリスト登録済みサーバー一覧",
            color=discord.Color.green()
        )
        
        for guild_id_str, data in list(whitelisted_guilds.items()):
            if len(embed.fields) >= 25:
                embed.set_footer(text="表示制限により一部サーバーは省略されました。")
                break
                
            guild_id = int(guild_id_str)
            guild = bot.get_guild(guild_id)
            
            guild_name = guild.name if guild else data['name']
            
            # 招待リンクを取得
            invite_link = "❌ リンク作成不可"
            if guild:
                try:
                    invite_channel = next(
                        (ch for ch in guild.text_channels 
                         if ch.permissions_for(guild.me).create_instant_invite), 
                        None
                    )
                    if invite_channel:
                        # 10分/1回限定の招待
                        invite = await invite_channel.create_invite(max_uses=1, max_age=600, unique=True) 
                        invite_link = f"[招待リンク]({invite.url})"
                    else:
                         invite_link = "❌ 招待権限なし"
                except discord.Forbidden:
                    invite_link = "❌ 招待作成の権限不足"
                except Exception:
                    invite_link = "❌ エラー発生"
            else:
                 invite_link = "❌ BOT未参加"


            # Embedのフィールドに追加
            value_text = f"ID: `{guild_id_str}`\n{invite_link}"
            
            # サムネイル設定（最初のサーバーのアイコンを使用）
            if embed.thumbnail.url is discord.Embed.Empty:
                 if guild and guild.icon:
                     embed.set_thumbnail(url=guild.icon.url)
                 elif data.get('icon_url'):
                     embed.set_thumbnail(url=data['icon_url'])
                     
            embed.add_field(name=f"🌐 {guild_name}", value=value_text, inline=True)
        
        await message.channel.send(embed=embed)
    
    # Botコマンドの処理
    await bot.process_commands(message)


# ==================================
# 🔥 修正箇所: 非同期コグ読み込み (setup_hook)
# ==================================
async def setup_cogs():
    """Botが接続する前にコグを非同期で読み込む（RuntimeWarningを解消）"""
    print("\nコグを非同期で読み込み中...")
    # main.pyからの相対パスでcogsフォルダを指定
    base_dir = Path(__file__).parent / "cogs" 
    
    if not base_dir.exists():
        print(f"⚠️ 警告: Cogディレクトリ ({base_dir}) が見つかりませんでした。")
        return # Cogの読み込みをスキップ

    def has_setup(fn: Path) -> bool:
        """ファイル内に setup 関数が定義されているかを確認"""
        try:
            txt = fn.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return False
        return ("def setup(" in txt) or ("async def setup(" in txt)

    for py in base_dir.rglob("*.py"):
        if py.name == "__init__.py":
            continue
        if not has_setup(py):
            continue

        rel = py.relative_to(base_dir).with_suffix("")
        module = "cogs." + ".".join(rel.parts)
        try:
            # 🔥 await を付けて非同期関数を正しく実行
            await bot.load_extension(module) 
            print(f"✅ Cog loaded: {module} (Async)")
        except Exception as e:
            print(f"❌ Cog load failed: {module} ({e})")
    
    print("✅ 全てのコグの非同期読み込みが完了しました。")

# bot.setup_hook に非同期読み込み関数を登録する
# bot.run() の内部で、この関数が自動的に await されて実行されます。
bot.setup_hook = setup_cogs

# Botの起動
if DISCORD_TOKEN:
    print("\nDiscord Botを起動します...")
    bot.run(DISCORD_TOKEN)