# cogs/youtube.py
import discord
from discord.ext import commands
from discord import app_commands # 追加
import yt_dlp
import requests
import os
import asyncio
import shutil
import re # タイムスタンプ抽出のためにreを追加
from pathlib import Path
from typing import Optional

# ffmpeg の有無を判定（インストールされていれば自動で True になる）
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

# ダウンロード一時ディレクトリ
DOWNLOAD_DIR = Path("youtube_downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Gofileのアップロードリンク
GOFILE_UPLOAD_URL = "https://store1.gofile.io/uploadFile"

# --- UI View ---

class TimeSelectionView(discord.ui.View):
    def __init__(self, format_type: str, url: str, max_duration: float = None):
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
            await cog.start_download(interaction, self.url, self.format_type, max_duration=self.max_duration)

    @discord.ui.button(label="時間を指定してダウンロード", style=discord.ButtonStyle.secondary, emoji="✂️", row=0, custom_id="time_button")
    async def time_download_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        # モーダルを表示
        await interaction.response.send_modal(TimeInputModal(self.url, self.format_type, self.max_duration))
        # 元のメッセージは編集しない（モーダルが完了するまで待つ）

class TimeInputModal(discord.ui.Modal):
    def __init__(self, url: str, format_type: str, max_duration: float):
        super().__init__(title="ダウンロード時間指定")
        self.url = url
        self.format_type = format_type
        self.max_duration = max_duration

        self.start_time = discord.ui.TextInput(
            label="開始時間 (例: 00:00:15 または 15s)",
            placeholder="h:mm:ss または 秒数",
            max_length=10,
            required=True
        )
        self.end_time = discord.ui.TextInput(
            label="終了時間 (例: 00:00:30 または 30s)",
            placeholder="h:mm:ss または 秒数",
            max_length=10,
            required=True
        )
        self.add_item(self.start_time)
        self.add_item(self.end_time)

    async def on_submit(self, interaction: discord.Interaction):
        start_ts = self.start_time.value
        end_ts = self.end_time.value
        
        await interaction.response.edit_message(content="📥 ダウンロードを準備中... (時間指定)", view=None)

        cog = interaction.client.get_cog('YouTubeCog')
        if cog:
            await cog.start_download(
                interaction, 
                self.url, 
                self.format_type, 
                start_time_ts=start_ts, 
                end_time_ts=end_ts,
                max_duration=self.max_duration
            )

# --- コグ ---

class YouTubeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _convert_timestamp_to_seconds(self, ts: str) -> Optional[int]:
        """h:mm:ss形式または秒数を秒単位の整数に変換する"""
        if not ts:
            return None
        
        ts = ts.strip().lower()

        # 秒数のみの場合 (例: 30s, 30)
        if ts.endswith('s'):
            ts = ts[:-1]
        
        try:
            return int(ts)
        except ValueError:
            pass

        # h:mm:ss 形式の場合
        parts = ts.split(':')
        seconds = 0
        if len(parts) == 3:
            seconds += int(parts[0]) * 3600
            seconds += int(parts[1]) * 60
            seconds += int(parts[2])
        elif len(parts) == 2:
            seconds += int(parts[0]) * 60
            seconds += int(parts[1])
        elif len(parts) == 1:
            seconds += int(parts[0])
        
        return seconds if seconds > 0 else None

    # @app_commands.command で youtube コマンドを定義
    @app_commands.command(name="youtube", description="YouTubeから動画や音声をダウンロードします。")
    @app_commands.describe(
        url="YouTubeのURL",
        format_type="ダウンロード形式",
    )
    @app_commands.choices(format_type=[
        app_commands.Choice(name="動画 (.mp4)", value="mp4"),
        app_commands.Choice(name="音声 (.mp3)", value="mp3"),
    ])
    async def youtube_command(self, interaction: discord.Interaction, url: str, format_type: str):
        # 応答を遅延
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        if format_type == "mp3" and not FFMPEG_AVAILABLE:
            await interaction.followup.send(
                "❌ MP3 (音声) 形式でのダウンロードにはFFmpegが必要です。Botが導入されている環境をご確認ください。",
                ephemeral=True
            )
            return

        try:
            # yt-dlpで動画情報を取得（同期処理を非同期実行）
            info = await asyncio.to_thread(self._get_video_info, url)
            
            # 最大持続時間を取得（秒）
            max_duration = info.get('duration') 
            
            # UIを表示してユーザーに選択させる
            embed = discord.Embed(
                title="📥 ダウンロードオプション",
                description=(
                    f"**タイトル**: {info.get('title', '不明')}\n"
                    f"**形式**: {format_type.upper()}\n"
                    f"**長さ**: {max_duration}秒 ({max_duration // 60}分{max_duration % 60}秒)\n\n"
                    "ダウンロード範囲を選択してください。"
                ),
                color=discord.Color.blue()
            )
            
            view = TimeSelectionView(format_type, url, max_duration)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        except yt_dlp.DownloadError as e:
            await interaction.followup.send(f"❌ 動画情報の取得に失敗しました。URLを確認してください: `{e}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 予期しないエラー: {e}", ephemeral=True)

    def _get_video_info(self, url):
        """動画情報を同期的に取得するヘルパー"""
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'force_generic_extractor': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
            
    # --- ダウンロードとアップロードのメイン処理 ---

    async def start_download(self, 
                             interaction: discord.Interaction, 
                             url: str, 
                             format_type: str, 
                             start_time_ts: str = None, 
                             end_time_ts: str = None,
                             max_duration: float = None):
        
        # 一時ファイル名
        unique_id = f"{interaction.id}_{interaction.user.id}"
        temp_filename = DOWNLOAD_DIR / f"{unique_id}.{format_type}"
        
        await interaction.edit_original_response(content=f"⏳ ダウンロード中... ({format_type.upper()})")

        try:
            # 1. ダウンロード処理
            filename_path = await asyncio.to_thread(
                self._download_video, 
                url, 
                format_type, 
                temp_filename, 
                start_time_ts, 
                end_time_ts, 
                max_duration
            )
            
            if not filename_path:
                await interaction.edit_original_response(content="❌ ダウンロード処理が失敗しました。")
                return

            file_size_mb = os.path.getsize(filename_path) / (1024 * 1024)
            
            # 2. Gofileアップロード
            await self.upload_to_gofile_for_interaction(interaction, filename_path, file_size_mb, max_duration)

        except yt_dlp.DownloadError as e:
            await interaction.edit_original_response(content=f"❌ ダウンロードエラーが発生しました: `{e}`")
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ ダウンロード中に予期しないエラーが発生しました: `{e}`")
            print(f"FATAL DOWNLOAD ERROR: {e}")
        finally:
            # 3. ファイルのクリーンアップ
            if Path(temp_filename).exists():
                os.remove(temp_filename)

    def _download_video(self, url, format_type, output_path, start_time_ts=None, end_time_ts=None, max_duration=None) -> Optional[Path]:
        """yt-dlpとffmpegを使用して動画をダウンロード・トリミングする（同期処理）"""
        
        # 共通オプション
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best' if format_type == 'mp4' else 'bestaudio/best',
            'outtmpl': str(output_path.with_suffix('')) + '.%(ext)s', # 拡張子をyt-dlpに任せる
            'postprocessors': [],
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4' if format_type == 'mp4' else 'm4a',
            'restrictfilenames': True,
        }
        
        # MP3変換オプション
        if format_type == 'mp3' and FFMPEG_AVAILABLE:
             ydl_opts['postprocessors'].append({
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            })
        
        # トリミングオプション (ffmpegが必要)
        if start_time_ts and end_time_ts and FFMPEG_AVAILABLE:
            start_sec = self._convert_timestamp_to_seconds(start_time_ts)
            end_sec = self._convert_timestamp_to_seconds(end_time_ts)
            
            if start_sec is not None and end_sec is not None and end_sec > start_sec:
                # durationを計算 (秒)
                duration_sec = end_sec - start_sec
                
                # youtube-dlp の postprocessor で ffmpeg トリミングを使用
                ydl_opts['postprocessors'].append({
                    'key': 'FFmpegVideoRemuxer',
                    'container': 'mp4' if format_type == 'mp4' else 'mp3'
                })
                ydl_opts['postprocessors'].append({
                    'key': 'SponsorBlock' # yt-dlpのバグ回避のため追加
                })
                ydl_opts['postprocessors'].append({
                    'key': 'FFmpegPostProcessor',
                    'args': [
                        '-ss', str(start_sec), # 開始時間
                        '-t', str(duration_sec), # 持続時間
                        '-c', 'copy' # コーデックをコピーで高速化
                    ]
                })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # yt-dlpが保存した実際のファイルパスを取得
            download_path = Path(ydl.prepare_filename(info))
            
            # yt-dlpは拡張子を調整することがあるため、正確なパスを返す
            if format_type == 'mp3':
                # mp3に変換された後のファイル名を探す
                mp3_path = download_path.with_suffix('.mp3')
                if mp3_path.exists():
                    return mp3_path
            
            # mp4や元の拡張子の場合
            if download_path.exists():
                return download_path

        return None # ダウンロード失敗

    async def upload_to_gofile_for_interaction(self, interaction: discord.Interaction, filename, file_size_mb, max_duration):
        await interaction.edit_original_response(content=f"📤 アップロード中です...\n💾 ファイルサイズ: {file_size_mb:.1f}MB")
        
        if file_size_mb > 100:
             await interaction.edit_original_response(content=f"❌ ファイルサイズが大きすぎます（{file_size_mb:.1f}MB）。100MB以下にしてください。")
             return

        try:
            # requestsは同期処理なのでasyncio.to_threadでラップ
            response = await asyncio.to_thread(
                requests.post,
                GOFILE_UPLOAD_URL,
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
    await bot.add_cog(YouTubeCog(bot))