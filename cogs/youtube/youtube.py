import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import requests
import os
import asyncio
import shutil
import re 

# ffmpeg の有無を判定（インストールされていれば自動で True になる）
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None


class TimeSelectionView(discord.ui.View):
    def __init__(self, format_type: str, url: str, max_duration: str = None):
        super().__init__(timeout=60)
        self.format_type = format_type
        self.url = url
        self.max_duration = max_duration

        # ffmpeg が無い場合は時間指定ボタンを無効化＋ラベル変更
        if not FFMPEG_AVAILABLE:
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.custom_id == "time_button":
                    item.disabled = True
                    item.label = "時間指定（ffmpeg未導入のため無効）"

    # @discord.ui.button は変更なし
    @discord.ui.button(label="全体をダウンロード", style=discord.ButtonStyle.secondary, emoji="📥", row=0)
    async def full_download_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="📥 ダウンロードを準備中...", view=None)
        cog = interaction.client.get_cog('YouTubeCog')
        if cog:
            # max_duration はここで渡す必要がないため省略
            await cog.start_direct_download(interaction, self.format_type, self.url)

    @discord.ui.button(label="時間を指定してダウンロード", style=discord.ButtonStyle.primary, emoji="⏱️", row=0, custom_id="time_button")
    async def time_download_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(TimeInputModal(self.format_type, self.url, self.max_duration))

# --- TimeInputModal (時間指定用のモーダル) ---
class TimeInputModal(discord.ui.Modal):
    def __init__(self, format_type: str, url: str, max_duration: str):
        super().__init__(title="ダウンロード時間指定")
        self.format_type = format_type
        self.url = url
        
        self.start_time = discord.ui.TextInput(
            label="開始時間 (例: 1:30 または 90s)",
            placeholder="00:00:00 から開始",
            required=False,
            max_length=10
        )
        self.end_time = discord.ui.TextInput(
            label="終了時間 (例: 5:00 または 300s)",
            placeholder=f"最大 {max_duration} まで",
            required=False,
            max_length=10
        )
        
        self.add_item(self.start_time)
        self.add_item(self.end_time)
        
    async def on_submit(self, interaction: discord.Interaction):
        start = self.start_time.value if self.start_time.value else None
        end = self.end_time.value if self.end_time.value else None

        if not start and not end:
            await interaction.response.send_message("❌ 開始時間または終了時間のいずれかを入力してください。", ephemeral=True)
            return

        await interaction.response.edit_message(content="⏱️ 時間指定ダウンロードを準備中...", view=None)
        
        # モーダルの後の処理はCogに委譲
        cog = interaction.client.get_cog('YouTubeCog')
        if cog:
            await cog.start_direct_download(interaction, self.format_type, self.url, start_time=start, end_time=end)


class YouTubeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # ⚠️ コマンドが消える問題への対処: 起動時にグローバルおよび全ギルドで同期 ⚠️
        print("INFO: Attempting to sync YouTube slash commands...")
        try:
            # Botが所属するすべてのギルドに対してコマンドを同期し、同期漏れを防ぎます。
            for guild in self.bot.guilds:
                await self.bot.tree.sync(guild=guild)
            
            # グローバル同期も実行（念のため）
            await self.bot.tree.sync() 

            print("INFO: YouTube slash commands synced successfully across all guilds.")
        except Exception as e:
            print(f"ERROR: Failed to sync YouTube slash commands: {e}")
            
    # ヘルパーメソッド (元のコードのロジックを維持)
    def _extract_video_info(self, url):
        # ... (動画情報抽出ロジック)
        return {"max_duration_text": "05:00", "title": "Test Video Title"} # 仮の戻り値
    
    def _download_video(self, url, format_type, output_path, start_time=None, end_time=None):
        # ... (yt-dlpを使用したダウンロードロジック)
        return "downloaded_file.mp4" # 仮の戻り値
    
    # --- コマンド ---
    @app_commands.command(
        name="youtube-dl",
        description="YouTube動画をダウンロードしてファイルまたはリンクで送付します。"
    )
    @app_commands.describe(
        url="ダウンロードしたいYouTube動画のURL",
        format_type="ダウンロード形式を選択"
    )
    @app_commands.choices(format_type=[
        app_commands.Choice(name="動画 (mp4)", value="mp4"),
        app_commands.Choice(name="音声 (mp3)", value="mp3"),
        app_commands.Choice(name="音声 (m4a)", value="m4a"),
    ])
    async def youtube_download(self, interaction: discord.Interaction, url: str, format_type: str):
        await interaction.response.defer(ephemeral=True)

        try:
            # 同期処理を非同期で実行
            info = await asyncio.to_thread(self._extract_video_info, url)
            max_duration_text = info.get("max_duration_text")
            
            if max_duration_text:
                embed = discord.Embed(
                    title="ダウンロード形式と時間選択",
                    description=f"最大動画時間: **{max_duration_text}**\n\nどの範囲をダウンロードしますか？",
                    color=discord.Color.blue()
                )
                view = TimeSelectionView(format_type, url, max_duration_text)
                
                await interaction.followup.send(content="⬇ ダウンロード形式と時間を選択してください:", embed=embed, view=view, ephemeral=True)
            else:
                # max_durationが取得できなかった場合、全体ダウンロードをすぐに開始
                await self.start_direct_download(interaction, format_type, url)

        except Exception as e:
            await interaction.followup.send(f"❌ 動画情報の取得中にエラーが発生しました: {str(e)}", ephemeral=True)

    # --- ダウンロード実行ロジック (interactionで動作するように調整) ---
    async def start_direct_download(self, interaction: discord.Interaction, format_type: str, url: str, start_time: str = None, end_time: str = None):
        temp_dir = f"temp_dl_{interaction.id}"
        os.makedirs(temp_dir, exist_ok=True)
        filename = None
        
        try:
            # interaction.edit_original_responseのcontentを修正
            await interaction.edit_original_response(content="⏳ ダウンロードを開始しています...")

            # ダウンロード処理 (同期) を非同期で実行
            output_path = os.path.join(temp_dir, "%(title)s.%(ext)s")
            filename = await asyncio.to_thread(
                self._download_video, 
                url, 
                format_type, 
                output_path, 
                start_time, 
                end_time
            )
            
            # ダウンロード後のファイル処理
            if not filename or not os.path.exists(filename):
                return await interaction.edit_original_response(content="❌ ダウンロードに失敗しました。")

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            
            # Gofileにアップロード
            # ★修正点: 不要な引数 (max_duration) を削除★
            await self.upload_to_gofile_for_interaction(interaction, filename, file_size_mb)

        except Exception as e:
            await interaction.edit_original_response(content=f"❌ ダウンロード/処理中にエラーが発生しました: {str(e)}")
        finally:
            if filename and os.path.exists(filename):
                try: os.remove(filename)
                except: pass
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)


    async def upload_to_gofile_for_interaction(self, interaction: discord.Interaction, filename, file_size_mb):
        # ★修正点: max_duration 引数を削除し、ファイルサイズ表示に専念★
        await interaction.edit_original_response(content=f"📤 アップロード中です...\n💾 ファイルサイズ: {file_size_mb:.1f}MB")
        try:
            # requestsは同期処理なのでasyncio.to_threadでラップ
            response = await asyncio.to_thread(
                requests.post,
                "https://store1.gofile.io/uploadFile",
                files={"file": open(filename, "rb")},
                timeout=300
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "ok":
                    link = data["data"]["downloadPage"]
                    await interaction.edit_original_response(content=f"✅ **アップロード完了**\n🔗 **ダウンロードリンク**: {link}")
                else:
                    await interaction.edit_original_response(content="❌ アップロードが失敗しました。しばらく後に再度お試しください。")
            else:
                await interaction.edit_original_response(content=f"❌ アップロードサーバーでエラーが発生しました。(エラーコード: {response.status_code})")
        except requests.RequestException:
            await interaction.edit_original_response(content="❌ アップロード中に通信エラーが発生しました。\nインターネット接続をご確認ください。")
        except Exception:
            await interaction.edit_original_response(content="❌ アップロード中に予期しないエラーが発生しました。\n管理者にお問い合わせください。")


async def setup(bot):
    await bot.add_cog(YouTubeCog(bot))