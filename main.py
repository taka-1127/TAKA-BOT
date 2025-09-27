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
# ★修正: サーバーメンバーの管理（特にバックアップ機能）に必要なIntentsを追加
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True # メンバーIntentsを有効化
intents.guilds = True # ギルドIntentsを有効化

# commands.Bot を使用し、プレフィックスは '!'
bot = commands.Bot(command_prefix='!', intents=intents) 

bot.user_sessions = {} # PayPayセッション管理用


# -------------------------------------------------------------------
# Helper: guilds.json の読み書き
# -------------------------------------------------------------------
def load_whitelisted_guilds():
    """ホワイトリストに登録されたギルドIDのリストを読み込む"""
    if not GUILDS_JSON_PATH.exists():
        return []
    try:
        with open(GUILDS_JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get("whitelisted_guilds", [])
    except (json.JSONDecodeError, FileNotFoundError):
        return []

def save_whitelisted_guilds(guild_ids: list):
    """ホワイトリストに登録されたギルドIDのリストを保存する"""
    data = {"whitelisted_guilds": guild_ids}
    with open(GUILDS_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)

# token.jsonの読み込み（変更なし）
token_path = "token.json"
if os.path.exists(token_path):
    try:
        with open(token_path, 'r') as f:
            tokens = json.load(f)
        for guild_id_str, access_token in tokens.items():
            try:
                # PayPayセッションを初期化 (Bot起動時にロード)
                guild_id = int(guild_id_str)
                paypay = PayPay(access_token=access_token)
                bot.user_sessions[guild_id] = paypay
                print(f"INFO: PayPay session loaded for Guild ID {guild_id}.")
            except ValueError:
                print(f"WARNING: Invalid guild ID in token.json: {guild_id_str}")
    except Exception as e:
        print(f"ERROR: Failed to load token.json: {e}")


# ==================================
# ✅ Bot イベント
# ==================================
@bot.event
async def on_ready():
    print(f'\nログインしました: {bot.user} (ID: {bot.user.id})')
    # コグの非同期読み込み関数を呼び出す
    await setup_cogs() 
    print("Botの起動準備が完了しました。")

# --- DMカスタムコマンド処理 (on_message) ---
@bot.event
async def on_message(message: discord.Message):
    # Bot自身のメッセージは無視
    if message.author.bot:
        return

    # DMでなければプレフィックスコマンドのみ処理
    if message.guild:
        await bot.process_commands(message)
        return

    # DMの場合のカスタムコマンド処理
    content = message.content.strip()
    whitelisted_guilds = load_whitelisted_guilds()

    # --- 1. ab#agl <サーバーID> (Add Guild to List) ---
    if content.lower().startswith("ab#agl"):
        parts = content.split()
        if len(parts) != 2:
            await message.channel.send("❌ コマンド形式が不正です。`ab#agl <サーバーID>` の形式で入力してください。")
            return
            
        try:
            guild_id = int(parts[1])
        except ValueError:
            await message.channel.send("❌ サーバーIDは数字で入力してください。")
            return
            
        guild = bot.get_guild(guild_id)
        if not guild:
            await message.channel.send("❌ そのIDのサーバーが見つかりませんでした。Botが参加していることを確認してください。")
            return

        if guild_id not in whitelisted_guilds:
            whitelisted_guilds.append(guild_id)
            save_whitelisted_guilds(whitelisted_guilds)

        await message.channel.send(
            f"✅ {message.author.mention} サーバー `{guild.name}` が**ホワイトリストに追加され、同期されました！**"
        )
        # ★修正箇所: カスタムDMコマンドが完了したら必ずreturnする
        return 
        
    # --- 2. ab#cgl <サーバーID> (Cancel Guild from List) ---
    elif content.lower().startswith("ab#cgl"):
        parts = content.split()
        if len(parts) != 2:
            await message.channel.send("❌ コマンド形式が不正です。`ab#cgl <サーバーID>` の形式で入力してください。")
            return
            
        try:
            guild_id = int(parts[1])
        except ValueError:
            await message.channel.send("❌ サーバーIDは数字で入力してください。")
            return

        if guild_id in whitelisted_guilds:
            whitelisted_guilds.remove(guild_id)
            save_whitelisted_guilds(whitelisted_guilds)
            removed_name = bot.get_guild(guild_id).name if bot.get_guild(guild_id) else str(guild_id)
        
            await message.channel.send(
                f"❌ {message.author.mention} サーバー `{removed_name}` が**ホワイトリストから削除されました**。"
            )
        else:
            await message.channel.send("⚠️ そのサーバーIDはホワイトリストに登録されていません。")
            
        # ★修正箇所: カスタムDMコマンドが完了したら必ずreturnする
        return

    # --- 3. ab#list (List Guilds) ---
    elif content.lower() == "ab#list":
        if not whitelisted_guilds:
            await message.channel.send("ホワイトリストに登録されているサーバーはありません。")
            # ★修正箇所: カスタムDMコマンドが完了したら必ずreturnする
            return 
            
        guild_list = []
        for guild_id in whitelisted_guilds:
            guild = bot.get_guild(guild_id)
            if guild:
                guild_list.append(f"**{guild.name}** (ID: {guild_id})")
            else:
                guild_list.append(f"**不明なサーバー** (ID: {guild_id}) - Botが参加していません")
                
        embed = discord.Embed(
            title="✅ ホワイトリスト登録済みサーバー",
            description="\n".join(guild_list),
            color=discord.Color.green()
        )
        await message.channel.send(embed=embed)
        
        # ★修正箇所: カスタムDMコマンドが完了したら必ずreturnする
        return
    
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

    # フォルダ内を再帰的に検索
    for py in base_dir.rglob("*.py"):
        if py.name == "__init__.py":
            continue
        if not has_setup(py):
            continue

        # cogs/youtube/youtube.py -> cogs.youtube.youtube に変換
        rel = py.relative_to(base_dir).with_suffix("")
        module = "cogs." + ".".join(rel.parts)
        
        try:
            # 🔥 await を付けて非同期関数を正しく実行
            await bot.load_extension(module) 
            print(f"✅ Cog loaded: {module}")
        except Exception as e:
            # エラー発生時も他のコグの読み込みは続行
            print(f"❌ Cog load failed: {module} -> {type(e).__name__}: {e}")

# setup_hookとして設定することで on_ready の前に非同期処理が可能になる
bot.setup_hook = setup_cogs 

# ==================================
# 🚀 Botの実行
# ==================================
if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)