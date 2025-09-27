# cogs/purchase_notifications.py の完全修正版

import discord
from discord.ext import commands
from discord import app_commands
import os
import json
from datetime import datetime
from typing import Optional

# ===============================================
# 1. PurchaseNotificationManager クラス (設定ファイルの読み書き)
#    (元: notification_utils.py の内容を統合)
# ===============================================
class PurchaseNotificationManager:
    """通知チャンネルの設定を管理するクラス"""
    def __init__(self, guild_id):
        self.guild_id = str(guild_id)
        # 設定を保存するディレクトリ。例: notification_config/123456789...
        self.config_dir = os.path.join("notification_config", self.guild_id)
        self.config_file = os.path.join(self.config_dir, "config.json")
        
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
    
    def set_notification_channel(self, channel_id: int):
        """通知チャンネルを設定"""
        config = self._load_config()
        config["notification_channel_id"] = str(channel_id)
        self._save_config(config)
    
    def get_notification_channel_id(self) -> Optional[str]:
        """通知チャンネルIDを取得"""
        config = self._load_config()
        return config.get("notification_channel_id")
    
    def _load_config(self) -> dict:
        """設定ファイルを読み込み"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_config(self, config: dict):
        """設定ファイルに保存"""
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

# ===============================================
# 2. send_purchase_notification 関数 (通知ロジック)
#    (元: notification_utils.py の内容を統合)
# ===============================================
async def send_purchase_notification(bot: commands.Bot, guild_id: int, user_id: int, product_name: str, price: int, item_content: str):
    """
    購入が発生した際に、設定されたチャンネルに通知を送信する
    """
    notification_manager = PurchaseNotificationManager(guild_id)
    channel_id = notification_manager.get_notification_channel_id()
    
    if not channel_id:
        return  # 通知チャンネルが設定されていない場合は何もしない
    
    channel = bot.get_channel(int(channel_id))
    if not channel:
        return  # チャンネルが見つからない場合は何もしない
    
    guild = bot.get_guild(int(guild_id))
    # ユーザーが見つからない場合もあるため、fetch_memberではなくget_memberでキャッシュから取得
    user = guild.get_member(int(user_id)) if guild else None
    user_mention = user.mention if user else f"<@{user_id}>"
    
    # 購入通知埋め込みを作成
    embed = discord.Embed(
        title="✅ 自動販売機 購入通知",
        description=f"DMに商品が届きます。ご購入ありがとうございました。",
        color=discord.Color.green(),
        timestamp=datetime.now()
    )

    embed.add_field(name="購入者", value=user_mention, inline=False)
    embed.add_field(name="購入金額", value=f"```{price:,}円```", inline=False)
    embed.add_field(name="商品", value=f"```{product_name}```", inline=False)
    
    # アイテム内容が長すぎる場合は省略
    if len(item_content) > 100:
        item_preview = item_content[:97] + "..."
    else:
        item_preview = item_content

    embed.set_footer(
        text=f"内容プレビュー: {item_preview}", 
        icon_url=bot.user.avatar.url if bot.user.avatar else discord.Embed.Empty
    )
    
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        # チャンネルに書き込み権限がない場合
        print(f"ERROR: チャンネルID {channel_id} に通知を送信できませんでした (権限不足)。")
    except Exception as e:
        print(f"ERROR: 通知送信中に予期せぬエラーが発生しました: {e}")

# ===============================================
# 3. SetVendingMachineCog クラス (スラッシュコマンド)
# ===============================================
class SetNotificationChannelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="set-notification-channel",
        description="自動販売機の購入通知を送るチャンネルを設定します（管理者専用）。"
    )
    @app_commands.describe(
        channel="通知を送りたいテキストチャンネル"
    )
    async def set_notification_channel_command(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)

        await interaction.response.defer(ephemeral=True)

        try:
            # 統合された PurchaseNotificationManager を使用
            manager = PurchaseNotificationManager(interaction.guild_id)
            manager.set_notification_channel(channel.id)
            
            await interaction.followup.send(
                f"✅ 購入通知チャンネルを {channel.mention} に設定しました。",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)


async def setup(bot: commands.Bot):
    """コグをボットにロードする関数"""
    await bot.add_cog(SetNotificationChannelCog(bot))