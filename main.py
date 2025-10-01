# main.py

import discord
from discord.ext import commands
from discord import app_commands 
import os
from PayPaython_mobile import PayPay
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv 
from typing import Optional, Dict, Any 
import re # reモジュールを追加

# ==================================
# 💡 設定 & ファイルパス
# ==================================
# .env ファイルを読み込む
load_dotenv() 
# 環境変数からトークンを取得
DISCORD_TOKEN = os.getenv("TOKEN") 

if not DISCORD_TOKEN:
    print("❌ エラー: .envファイルに 'TOKEN=○○' が設定されていません。")
    exit(1)

# 🔥 復活: guilds.json のパス
GUILDS_JSON_PATH = Path(__file__).parent / "guilds.json"
# ==================================

# IntentsとBotの初期化
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True 
intents.guilds = True 

# commands.Bot を使用し、プレフィックスは '!'
bot = commands.Bot(command_prefix='!', intents=intents) 

bot.user_sessions = {} # PayPayセッション管理用


# -------------------------------------------------------------------
# 🔥 復活: Helper: guilds.json の読み書き (ホワイトリスト管理)
# -------------------------------------------------------------------
def load_whitelisted_guilds() -> list[str]:
    """ホワイトリストに登録されたギルドIDのリストを読み込む"""
    if not GUILDS_JSON_PATH.exists():
        return []
    try:
        with open(GUILDS_JSON_PATH, 'r', encoding='utf-8') as f:
            # ギルドIDのリストを返すことを期待
            data = json.load(f)
            return [str(g_id) for g_id in data if str(g_id).isdigit()]
    except Exception as e:
        print(f"❌ エラー: guilds.json の読み込みまたは解析中にエラーが発生しました: {e}")
        return []

def save_whitelisted_guilds(guild_ids: list):
    """ホワイトリストに登録されたギルドIDのリストを保存する"""
    try:
        with open(GUILDS_JSON_PATH, 'w', encoding='utf-8') as f:
            # 文字列として保存
            json.dump([str(g_id) for g_id in guild_ids], f, indent=2)
    except Exception as e:
        print(f"❌ エラー: guilds.json の保存中にエラーが発生しました: {e}")
# -------------------------------------------------------------------


# -------------------------------------------------------------------
# 🔥 ab#pay コマンドで使用するダミーデータと設定 (変更なし)
# -------------------------------------------------------------------
# 変更後の固定自販機ID
TARGET_VM_ID = "1119588177448013965"

# ⚠️ 注意: 実際には、この情報をDBや設定ファイルから読み書きする必要があります。
# {discord_user_id: {phone: str, password_obf: str, linked_vms: dict}}
bot.paypay_user_data = {
    # 実行ユーザーのダミーID (このコードでは `!admin` の実行者IDが使用される)
    # 実際のユーザーIDに置き換える必要があります。
    "YOUR_USER_ID_HERE": { 
        "phone": "09012345678", # 実際の電話番号
        "password_obf": "********", # パスワードは絶対に平文で保存しないでください
        "linked_vms": {
            TARGET_VM_ID: {
                "vm_name": "自販機A",
                "vm_file": "vending_machine_1119588177448013965.json" # 関連ファイル名
            }
        }
    }
}
# -------------------------------------------------------------------


# -------------------------------------------------------------------
# Helper: token.json から PayPay セッションを読み込む (変更なし)
# -------------------------------------------------------------------
def load_paypay_sessions():
    """token.json から PayPay セッションを読み込み、bot.user_sessions にセットする"""
    token_path = "token.json"
    if os.path.exists(token_path):
        try:
            with open(token_path, 'r') as f:
                tokens = json.load(f)
            for guild_id_str, access_token in tokens.items():
                try:
                    guild_id = int(guild_id_str)
                    # アクセストークンを使ってPayPayセッションを再構築
                    paypay = PayPay(access_token=access_token)
                    bot.user_sessions[guild_id] = paypay
                    print(f"✅ PayPay session restored for Guild ID: {guild_id}")
                except Exception as e:
                    print(f"⚠️ 警告: Guild ID {guild_id_str} のPayPayセッション復元に失敗しました: {e}")
        except Exception as e:
            print(f"❌ エラー: token.json の読み込みまたは解析中にエラーが発生しました: {e}")


# ==================================
# AdminView のボタン実装 (変更なし)
# ==================================

class VMSelectButton(discord.ui.Button):
    def __init__(self, bot: commands.Bot, user_id: str, vm_id: str, vm_name: str):
        super().__init__(label=f"📦 {vm_name} を表示/ID変更", style=discord.ButtonStyle.secondary)
        self.bot = bot
        self.user_id = user_id
        self.vm_id = vm_id
        self.vm_name = vm_name

    async def callback(self, interaction: discord.Interaction):
        # 権限チェック (AdminControlViewの実行者か)
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("❌ この操作はコマンド実行者のみが行えます。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        
        # 処理ロジック (ここではメッセージを送るだけ)
        await interaction.followup.send(
            f"🛠️ 自販機 **{self.vm_name}** (`{self.vm_id}`) の管理画面へ移動します...\n"
            "⚠️ **ID変更**は `/vm-id-change` コマンドを使用してください。",
            ephemeral=True
        )


class AdminControlView(discord.ui.View):
    def __init__(self, bot: commands.Bot, user_id: str):
        super().__init__(timeout=180) # 3分後にタイムアウト
        self.bot = bot
        self.user_id = str(user_id) # strで保存

        # ユーザーデータからリンクされたVMの情報を取得してボタンを作成
        user_data = bot.paypay_user_data.get(self.user_id, {})
        linked_vms = user_data.get('linked_vms', {})
        
        if linked_vms:
            for vm_id, vm_info in linked_vms.items():
                self.add_item(VMSelectButton(bot, self.user_id, vm_id, vm_info.get('vm_name', '不明な自販機')))
        else:
            # リンクされたVMがない場合のダミーボタン
            self.add_item(discord.ui.Button(label="リンクされた自販機はありません", style=discord.ButtonStyle.secondary, disabled=True))


# ==================================
# イベントハンドラ
# ==================================

@bot.event
async def on_ready():
    """BotがDiscordに接続したときに実行される"""
    print('------------------------------------')
    print(f'Bot Name: {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    print('------------------------------------')

    # PayPayセッションの復元
    load_paypay_sessions()

    # コグの非同期読み込みを実行
    await setup_cogs()
    
    # スラッシュコマンドを同期
    try:
        # bot.tree.sync() は setup_hook で実行されるため、ここでは省略可能だが念のため実行
        synced = await bot.tree.sync()
        print(f"✅ Synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")

    print('Bot is ready.')


@bot.event
async def on_message(message: discord.Message):
    """メッセージが送信されたときに実行される"""
    if message.author.bot:
        return
    
    # ギルド (サーバー) のみで動作
    if message.guild is None:
        if message.content.startswith('ab#'):
             await message.channel.send("❌ このカスタムコマンドはサーバー内でのみ実行できます。")
        await bot.process_commands(message)
        return

    # ------------------------------------------------
    # 🔥 修正・追加: ab#pay などのカスタムコマンド処理
    # ------------------------------------------------
    content_parts = message.content.strip().split()
    command = content_parts[0].lower()
    
    # Botのオーナー（または管理者）のみがホワイトリストコマンドを実行できるようにする
    is_owner = await bot.is_owner(message.author)
    
    # ギルドIDを抽出（あれば）
    target_guild_id_str = content_parts[1] if len(content_parts) > 1 and content_parts[1].isdigit() else None
    
    # --- ホワイトリスト管理コマンド ---
    
    if command == 'ab#agl':
        # サーバーのホワイトリストへの追加（有効化）
        if not is_owner:
            return await message.channel.send("❌ **権限不足**: このコマンドはBotのオーナーのみ実行可能です。")
        
        if not target_guild_id_str:
            return await message.channel.send("❌ **構文エラー**: `ab#agl [サーバーID]` の形式で指定してください。")
            
        guild_id = target_guild_id_str
        whitelisted_guilds = load_whitelisted_guilds()
        
        if guild_id in whitelisted_guilds:
            return await message.channel.send(f"⚠️ **警告**: サーバーID `{guild_id}` は既にホワイトリストに登録されています。")
            
        whitelisted_guilds.append(guild_id)
        save_whitelisted_guilds(whitelisted_guilds)
        await message.channel.send(f"✅ **成功**: サーバーID `{guild_id}` をホワイトリストに追加し、Botの利用を有効化しました。")
        return
    
    elif command == 'ab#dgl':
        # サーバーのホワイトリストからの削除（無効化）
        if not is_owner:
            return await message.channel.send("❌ **権限不足**: このコマンドはBotのオーナーのみ実行可能です。")
        
        if not target_guild_id_str:
            return await message.channel.send("❌ **構文エラー**: `ab#dgl [サーバーID]` の形式で指定してください。")
            
        guild_id = target_guild_id_str
        whitelisted_guilds = load_whitelisted_guilds()
        
        if guild_id not in whitelisted_guilds:
            return await message.channel.send(f"⚠️ **警告**: サーバーID `{guild_id}` はホワイトリストに登録されていません。")
            
        whitelisted_guilds.remove(guild_id)
        save_whitelisted_guilds(whitelisted_guilds)
        await message.channel.send(f"✅ **成功**: サーバーID `{guild_id}` をホワイトリストから削除し、Botの利用を無効化しました。")
        return

    elif command == 'ab#cgl':
        # サーバーのホワイトリスト登録確認
        if not is_owner:
            return await message.channel.send("❌ **権限不足**: このコマンドはBotのオーナーのみ実行可能です。")
        
        if not target_guild_id_str:
            return await message.channel.send("❌ **構文エラー**: `ab#cgl [サーバーID]` の形式で指定してください。")
            
        guild_id = target_guild_id_str
        whitelisted_guilds = load_whitelisted_guilds()
        
        if guild_id in whitelisted_guilds:
            status = "✅ 登録済み (有効)"
            color = discord.Color.green()
        else:
            status = "❌ 未登録 (無効)"
            color = discord.Color.red()
            
        embed = discord.Embed(
            title="🌐 ホワイトリスト登録確認",
            description=f"サーバーID `{guild_id}` の登録状況:",
            color=color
        )
        embed.add_field(name="ステータス", value=status, inline=False)
        await message.channel.send(embed=embed)
        return
    
    # --- PayPay 支払いコマンド ---
    
    elif command == 'ab#pay':
        # 支払い処理のロジックをここに実装 (簡易的な応答)
        
        # サーバーがホワイトリストに登録されているかチェック
        whitelisted_guilds = load_whitelisted_guilds()
        if str(message.guild.id) not in whitelisted_guilds:
            return await message.channel.send(f"❌ **利用不可**: このサーバー (`{message.guild.id}`) はBotの利用が許可されていません。オーナーに`ab#agl`コマンドで有効化を依頼してください。")
            
        # 支払いロジック (ダミー)
        try:
            # 支払い金額の抽出 (例: ab#pay 500)
            amount_str = content_parts[1] if len(content_parts) > 1 else "500"
            amount = int(amount_str)
            
            # PayPayセッションの確認
            paypay_session = bot.user_sessions.get(message.guild.id)
            if not paypay_session:
                return await message.channel.send("❌ **PayPay未ログイン**: このサーバーでPayPayにログインしていません。`/login_paypay`でログインしてください。")

            await message.channel.send(f"✅ **PayPay支払い処理を開始します。**\n金額: **{amount:,}円**\n自販機ID: TARGET_VM_ID\n\n*（ここでは支払い処理のコードは省略されています。）*")
        except ValueError:
             await message.channel.send("❌ **構文エラー**: `ab#pay [金額]` の形式で金額は数字で指定してください。（例: `ab#pay 500`）")
        except Exception as e:
            await message.channel.send(f"❌ **エラー**: 支払処理中に予期せぬエラーが発生しました: `{e}`")

        return
    
    # ------------------------------------------------
    # 管理者コマンドの処理 (!admin) (変更なし)
    # ------------------------------------------------
    if message.content == '!admin':
        # 実行者IDを文字列として取得
        user_id = str(message.author.id) 

        # ユーザーのPayPay/VM管理データを取得
        user_data = bot.paypay_user_data.get(user_id)

        if not user_data:
            # データがない場合は警告メッセージ
            embed = discord.Embed(
                title="❌ アクセス拒否",
                description="あなたのアカウントは管理者として登録されていません。",
                color=discord.Color.red()
            )
            try:
                await message.channel.send(embed=embed)
            except discord.Forbidden:
                print(f"❌ チャンネル {message.channel.id} にメッセージを送信できませんでした (権限不足)。")
            return

        # メンション形式での名前と情報
        user_mention = message.author.mention 
        phone_num = user_data['phone']
        
        paypay_info = (
            f"1. {user_mention}\n"
            f"　 　電話番号：**{phone_num[:4]}xxxxxxx{phone_num[-4:]}**\n" # 一部マスク
            f"　 　パスワード：**{user_data['password_obf']}**" # マスクされたパス
        )

        embed = discord.Embed(
            title="🛠️ PayPay/自販機 管理画面",
            description=paypay_info,
            color=discord.Color.blue()
        )
        embed.set_footer(text="自販機閲覧・ID変更は下のコンポーネントをご利用ください。")

        # 2つのコンポーネントを持つViewをアタッチ
        view = AdminControlView(bot=bot, user_id=user_id)
        
        try:
            await message.channel.send(embed=embed, view=view)
        except discord.Forbidden:
            print(f"❌ チャンネル {message.channel.id} にメッセージを送信できませんでした。")
            
        return

    # Botコマンドの処理
    await bot.process_commands(message)


# ==================================
# 🔥 非同期コグ読み込み (setup_hook) (変更なし)
# ==================================
async def setup_cogs():
    """Botが接続する前にコグを非同期で読み込む"""
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
        # setup 関数または async def setup 関数が存在するか
        return ("def setup(" in txt) or ("async def setup(" in txt)

    # cogsディレクトリとそのサブディレクトリ内の.pyファイルを検索
    for py in base_dir.rglob("*.py"):
        if py.name == "__init__.py":
            continue
        if not has_setup(py):
            continue

        # モジュール名に変換 (例: cogs/backup/backup.py -> cogs.backup.backup)
        # main.pyと同じ階層のcogsからの相対パスをモジュール名にする
        rel = py.relative_to(Path(__file__).parent).with_suffix("") 
        module = ".".join(rel.parts)
        
        try:
            # 🔥 await を付けて非同期関数を正しく実行
            await bot.load_extension(module) 
            print(f"✅ Cog loaded: {module}")
        except Exception as e:
            print(f"❌ Failed to load cog {module}: {e}")

# 実行
try:
    bot.run(DISCORD_TOKEN)
except discord.HTTPException as e:
    # 50035 Invalid Form Body のようなエラーが出た場合
    print(f"❌ Discord APIエラーが発生しました: {e}")
except Exception as e:
    print(f"❌ Botの起動中に予期せぬエラーが発生しました: {e}")