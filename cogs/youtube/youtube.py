import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import requests
import os
import asyncio
import shutil
import re 
import glob
from typing import Dict, Any, Optional

# ffmpeg の有無を判定
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

# =========================================================
# カスタム View (時間指定)
# =========================================================

class TimeSelectionView(discord.ui.View):
    def __init__(self, format_type: str, url: str, max_duration: str = None):
        super().__init__(timeout=60)
        self.format_type = format_type
        self.url = url
        self.max_duration = max_duration

        if not FFMPEG_AVAILABLE:
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.custom_id == "time_button":
                    item.disabled = True
                    item.label = "時間指定（ffmpeg未導入のため無効）"

    @discord.ui.button(label="全体をダウンロード", style=discord.ButtonStyle.secondary, emoji="📥", row=0)
    async def full_download_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.edit_message(content="📥 ダウンロードを準備中...", view=None)
        cog = interaction.client.get_cog('YouTubeCog')
        if cog:
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
        selected_start = self.start_time.value if self.start_time.value else None
        selected_end = self.end_time.value if self.end_time.value else None

        if not selected_start and not selected_end:
            await interaction.response.send_message("❌ 開始時間または終了時間のいずれかを入力してください。", ephemeral=True)
            return

        await interaction.response.edit_message(content="⏱️ 時間指定ダウンロードを準備中...", view=None)
        
        cog = interaction.client.get_cog('YouTubeCog')
        if cog:
            await cog.start_direct_download(interaction, self.format_type, self.url, start_time=selected_start, end_time=selected_end)


# =========================================================
# Discord コグ
# =========================================================
class YouTubeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        print("INFO: Attempting to sync YouTube slash commands...")
        try:
            for guild in self.bot.guilds:
                # ギルド単位でのコマンド同期は時間がかかるため、通常はグローバル同期で十分
                # await self.bot.tree.sync(guild=guild)
                pass
            await self.bot.tree.sync() 
            print("INFO: YouTube slash commands synced successfully across all guilds.")
        except Exception as e:
            print(f"ERROR: Failed to sync YouTube slash commands: {e}")
            
    # ヘルパーメソッド (yt-dlpを利用して動画情報を取得する実際のロジック)
    def _extract_video_info(self, url: str) -> Dict[str, Any]:
        """動画のタイトル、長さなどを抽出する"""
        ydl_opts = {
            'noplaylist': True,
            'quiet': True,
            'simulate': True, # ダウンロードはしない
            'force_generic_extractor': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            duration_sec = info.get('duration')

            max_duration_text = ""
            if duration_sec is not None:
                # 秒を HH:MM:SS 形式に変換
                h = duration_sec // 3600
                m = (duration_sec % 3600) // 60
                s = duration_sec % 60
                if h > 0:
                     max_duration_text = f"{h:02d}:{m:02d}:{s:02d}"
                else:
                     max_duration_text = f"{m:02d}:{s:02d}"
            
            return {
                "max_duration_text": max_duration_text if max_duration_text else "不明",
                "title": info.get('title', 'Unknown Title')
            }

    # ヘルパーメソッド (yt-dlpを利用してダウンロードを実行する実際のロジック)
    def _download_video(self, url: str, format_type: str, output_path: str, start_time: Optional[str] = None, end_time: Optional[str] = None) -> Optional[str]:
        """yt-dlpで動画をダウンロードし、最終ファイル名を返す"""
        
        # フォーマット設定
        if format_type == "mp4":
            format_string = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            final_ext = 'mp4'
        elif format_type == "mp3":
            format_string = 'bestaudio/best'
            final_ext = 'mp3'
        elif format_type == "m4a":
            format_string = 'bestaudio[ext=m4a]/best'
            final_ext = 'm4a'
        else:
            raise ValueError("無効なフォーマットタイプ")

        postprocessors = []

        if format_type in ["mp3", "m4a"]:
            postprocessors.append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format_type,
                'preferredquality': '192',
            })
        
        # 時間指定のクロッピング設定
        if start_time or end_time:
            # ffmpegが必須
            if not FFMPEG_AVAILABLE:
                raise Exception("時間指定ダウンロードには、Botが動作する環境にffmpegが必要です。")
            
            postprocessors.append({
                'key': 'FFmpegPostProcessor',
                'postprocessor_args': [
                    *(['-ss', start_time] if start_time else []),
                    *(['-to', end_time] if end_time else []),
                ],
            })
            # 時間指定後のファイルが、希望の最終拡張子になるようにremuxerを最後に配置
            postprocessors.append({
                'key': 'FFmpegVideoRemuxer',
                'preferedformat': final_ext,
            })
        
        ydl_opts = {
            'format': format_string,
            'outtmpl': output_path,
            'noplaylist': True,
            'quiet': True,
            'force_generic_extractor': True,
            'postprocessors': postprocessors
        }
        
        temp_dir = os.path.dirname(output_path)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                
                # ★修正済み: ダウンロードディレクトリ内のファイルを探索し、最終的なファイル名を見つける
                downloaded_files = glob.glob(f"{temp_dir}/*")
                
                # 最終的な拡張子を持つファイルを探す
                for f in downloaded_files:
                     if f.endswith(f".{final_ext}") and os.path.getsize(f) > 0:
                         return f
                
                # 見つからなかった場合は、ダウンロードディレクトリ内の最初のファイルを返す（最後の手段）
                if downloaded_files:
                     first_file = downloaded_files[0]
                     if os.path.getsize(first_file) > 0:
                        return first_file

                return None 
                
        except Exception as e:
            print(f"YT-DLP Error: {e}")
            raise Exception(f"ダウンロードに失敗しました。ファイルが公開されているか確認してください。")


    # --- ヘルパー: ダウンロード実行とファイル処理 ---
    async def start_direct_download(self, interaction: discord.Interaction, format_type: str, url: str, start_time: str = None, end_time: str = None):
        # 一時ディレクトリの作成
        temp_dir = f"temp_dl_{interaction.id}"
        os.makedirs(temp_dir, exist_ok=True)
        
        try:
            if not os.path.isdir(temp_dir):
                 await interaction.edit_original_response(content="❌ ダウンロード用の一時フォルダ作成に失敗しました。")
                 return
                 
            await interaction.edit_original_response(content="⏳ ダウンロードを開始します...")

            # yt-dlpに渡す出力パス
            output_path = os.path.join(temp_dir, "%(title)s.%(ext)s")
            
            # 同期処理である _download_video を非同期で実行
            filename = await asyncio.to_thread(
                self._download_video, 
                url, 
                format_type, 
                output_path, 
                start_time, 
                end_time
            )
            
            if not filename or not os.path.exists(filename):
                raise Exception("ダウンロードされたファイルが見つかりませんでした。")

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            
            # Discordアップロード制限 (ここでは25MBを仮定)
            DISCORD_MAX_SIZE_MB = 25 

            if file_size_mb > DISCORD_MAX_SIZE_MB:
                # Gofile経由でのアップロード
                max_duration = "" # 情報がないため空
                await self.upload_to_gofile_for_interaction(interaction, filename, file_size_mb, max_duration)
            else:
                # Discordに直接アップロード
                await interaction.edit_original_response(content=f"✅ ダウンロード完了。Discordにアップロード中... ({file_size_mb:.1f}MB)")
                
                # アップロード時にファイル名を調整
                discord_filename = os.path.basename(filename) 
                
                await interaction.channel.send(
                    content=f"📥 {interaction.user.mention} 様のご要望のファイルです。",
                    file=discord.File(filename, filename=discord_filename)
                )
                await interaction.delete_original_response()

        except Exception as e:
            error_message = f"❌ **処理中にエラーが発生しました。**\n```{e}```"
            try:
                # original_responseがない場合があるため、try-except
                await interaction.edit_original_response(content=error_message)
            except:
                 await interaction.followup.send(content=error_message, ephemeral=True)
                 
        finally:
            # ★修正済み: finallyブロックでtemp_dir全体を確実に削除
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    async def upload_to_gofile_for_interaction(self, interaction: discord.Interaction, filename, file_size_mb, max_duration):
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


async def setup(bot: commands.Bot):
    # ★修正済み: setup関数は正しい
    await bot.add_cog(YouTubeCog(bot))