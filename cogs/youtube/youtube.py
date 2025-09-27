import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp
import requests
import os
import asyncio
import shutil
import re 
from typing import Dict, Any, Optional

# ffmpeg の有無を判定
FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

# =========================================================
# カスタム View (時間指定)
# =========================================================

class TimeSelectionView(discord.ui.View):
    # (変更なし)

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
    # (変更なし)
    
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
            # start_time, end_timeに None も許容
            await cog.start_direct_download(interaction, self.format_type, self.url, start_time=selected_start, end_time=selected_end)


# ----------------------------------
# (省略: YouTubeCogクラス内)
# ----------------------------------

    # ヘルパーメソッド (yt-dlpを利用してダウンロードを実行する実際のロジック)
    def _download_video(self, url: str, format_type: str, output_path: str, start_time: Optional[str] = None, end_time: Optional[str] = None) -> Optional[str]:
        """yt-dlpで動画をダウンロードし、最終ファイル名を返す"""
        
        # フォーマット設定 (変更なし)
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
        
        # 時間指定のクロッピング設定 (変更なし)
        if start_time or end_time:
            if not FFMPEG_AVAILABLE:
                raise Exception("時間指定ダウンロードには、Botが動作する環境にffmpegが必要です。")
            
            # テンポラリフォーマットとしてmp4を優先
            remux_format = 'mp4' if final_ext == 'mp4' or final_ext == 'mp3' else final_ext
            
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
        
        temp_dir = os.path.dirname(output_path) # ダウンロードディレクトリ
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                
                # ★修正点: ダウンロードディレクトリ内のファイルを探索し、最終的なファイル名を見つける
                import glob
                
                # yt-dlpが post-processor を使用した場合、拡張子が変更されることがあるため、
                # テンポラリディレクトリ内のファイルリストを取得する
                # basenameに %() プレースホルダーが含まれる場合があるため、ワイルドカードで検索
                base_name_pattern = output_path.replace('%(title)s', info_dict.get('title', '*'))
                base_name_pattern = base_name_pattern.replace('%(ext)s', '*')
                
                # globでダウンロードディレクトリ内の全ファイルを検索
                downloaded_files = glob.glob(f"{temp_dir}/*")
                
                # 最終的な拡張子を持つファイルを探す
                for f in downloaded_files:
                     if f.endswith(f".{final_ext}") and os.path.getsize(f) > 0:
                         return f
                
                # 見つからなかった場合は、ダウンロードディレクトリ内の最初のファイルを返す（最後の手段）
                if downloaded_files and os.path.getsize(downloaded_files[0]) > 0:
                     return downloaded_files[0]

                return None 
                
        except Exception as e:
            print(f"YT-DLP Error: {e}")
            raise Exception(f"ダウンロードに失敗しました。ファイルが公開されているか確認してください。")


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
            info = await asyncio.to_thread(self._extract_video_info, url)
            max_duration_text = info.get("max_duration_text")
            
            if max_duration_text:
                embed = discord.Embed(
                    title="ダウンロード形式と時間選択",
                    description=f"動画タイトル: **{info.get('title', '不明なタイトル')}**\n最大動画時間: **{max_duration_text}**\n\nどの範囲をダウンロードしますか？",
                    color=discord.Color.blue()
                )
                view = TimeSelectionView(format_type, url, max_duration_text)
                
                await interaction.followup.send(content="⬇ ダウンロード形式と時間を選択してください:", embed=embed, view=view, ephemeral=True)
            else:
                await self.start_direct_download(interaction, format_type, url)

        except Exception as e:
            await interaction.followup.send(f"❌ 動画情報の取得中にエラーが発生しました: {str(e)}", ephemeral=True)

    # --- ダウンロード実行ロジック ---
    async def start_direct_download(self, interaction: discord.Interaction, format_type: str, url: str, start_time: str = None, end_time: str = None):
        temp_dir = f"temp_dl_{interaction.id}"
        os.makedirs(temp_dir, exist_ok=True)
        filename = None
        
        try:
            await interaction.edit_original_response(content="⏳ ダウンロードを開始しています...")

            output_path = os.path.join(temp_dir, "%(title)s.%(ext)s")
            
            # _download_videoを呼び出す
            filename = await asyncio.to_thread(
                self._download_video, 
                url, 
                format_type, 
                output_path, 
                start_time, 
                end_time
            )
            
            if not filename or not os.path.exists(filename):
                return await interaction.edit_original_response(content="❌ ダウンロードに失敗しました。ファイルが生成されませんでした。")

            file_size_mb = os.path.getsize(filename) / (1024 * 1024)
            
            # Gofileにアップロード
            await self.upload_to_gofile_for_interaction(interaction, filename, file_size_mb)

        except Exception as e:
            await interaction.edit_original_response(content=f"❌ ダウンロード/処理中にエラーが発生しました: {str(e)}")
        finally:
            # ★修正点: finallyブロックでtemp_dir全体を確実に削除
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)


    async def upload_to_gofile_for_interaction(self, interaction: discord.Interaction, filename, file_size_mb):
        # (変更なし)
        await interaction.edit_original_response(content=f"📤 アップロード中です...\n💾 ファイルサイズ: {file_size_mb:.1f}MB")
        try:
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