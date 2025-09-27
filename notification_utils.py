# cogs/notification_utils.py

import discord
import os
import json
from datetime import datetime

# ===============================================
# 1. PurchaseNotificationManager クラス (設定ファイルの読み書き)
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
    
    def set_notification_channel(self, channel_id):
        """通知チャンネルを設定"""
        config = self._load_config()
        config["notification_channel_id"] = str(channel_id)
        self._save_config(config)
    
    def get_notification_channel_id(self):
        """通知チャンネルIDを取得"""
        config = self._load_config()
        return config.get("notification_channel_id")
    
    def _load_config(self):
        """設定ファイルを読み込み"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_config(self, config):
        """設定ファイルに保存"""
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

# ===============================================
# 2. send_purchase_notification 関数 (通知の送信)
# ===============================================
async def send_purchase_notification(bot, guild_id, user_id, product_name, price, item_content):
    """購入通知を指定チャンネルに送信する非同期関数"""
    try:
        # notification_utils.py 内のクラスを使用
        notification_manager = PurchaseNotificationManager(guild_id)
        channel_id = notification_manager.get_notification_channel_id()
        
        if not channel_id:
            return
        
        # チャンネルの取得
        channel = bot.get_channel(int(channel_id))
        if not channel:
            # チャンネルIDは設定されているが、チャンネルが見つからない
            return 
        
        guild = bot.get_guild(int(guild_id))
        user = guild.get_member(int(user_id)) if guild else None
        user_mention = user.mention if user else f"<@{user_id}>"
        
        # 購入通知埋め込みを作成
        embed = discord.Embed(
            title="自動販売機",
            description=f"DMに商品が届きます。ご購入ありがとうございました。",
            color=discord.Color.green(),
            timestamp=datetime.now()
        )

        embed.add_field(name="購入者", value=user_mention, inline=False)
        embed.add_field(name="購入金額", value=f"```{price:,}円```", inline=False)
        embed.add_field(name="商品", value=f"```{product_name}```", inline=False)
        
        if len(item_content) > 100:
            item_preview = item_content[:97] + "..."
        else:
            item_preview = item_content

        embed.set_footer(
            text="Made by LT", 
            icon_url=bot.user.avatar.url if bot.user.avatar else discord.Embed.Empty
        )
        
        await channel.send(embed=embed)
        
    except Exception as e:
        print(f"購入通知送信エラー: {e}")