import discord
from discord.ext import commands
from discord import app_commands # 追加
from discord.ui import Button, View
import json
import os
import asyncio # 永続Viewの準備のために追加

# --- 永続 View ---
class PersistentView(View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot
        
        # チケット作成ボタンをViewに追加
        self.add_item(TicketCreateButton(label="🎫 チケットを作成", style=discord.ButtonStyle.primary, custom_id="ticket_create_button"))
        
        # 既存の永続Viewコンポーネントがあればここに追加 (元のコードにカスタムIDが不明なボタンがあったため、ここではTicketCreateButtonのみ)

# --- チケット作成ボタン ---
class TicketCreateButton(discord.ui.Button):
    def __init__(self, label, style, custom_id):
        super().__init__(label=label, style=style, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        # チャンネル作成ロジックはCogに委譲することが望ましいが、ここでは元のコードに倣い、
        # 必要な権限チェックとチャンネル作成を直接行う
        
        # チャンネル名 (例: ticket-ユーザー名)
        channel_name = f"ticket-{interaction.user.name.lower().replace(' ', '-')}"
        
        # 既にチケットチャンネルが存在するかチェック (簡略化のため、ここでは既存チェックは省略)
        
        # 権限設定 (デフォルトは読み取り不可、ユーザーとBOTは読み書き可能)
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
            # スタッフ権限を持つロールやユーザーのオーバーライトは、Cogで管理されている設定から取得する必要がある
        }
        
        try:
            # チャンネルの作成
            new_channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=interaction.channel.category, # パネル設置チャンネルと同じカテゴリーに作成
                overwrites=overwrites
            )
            
            # 作成完了の応答
            await interaction.followup.send(f"✅ チケットチャンネル {new_channel.mention} を作成しました。", ephemeral=True)
            
            # 1通目の自動応答を送信するために、Cogのインスタンスを通して `ticket_messages` を更新する必要がある
            cog = interaction.client.get_cog('TicketCog')
            if cog:
                cog.ticket_messages[new_channel.id] = 0 # 初期メッセージ数を0に設定
                cog._save_json(cog.ticket_messages_file, cog.ticket_messages)
            
            # チャンネル内に最初のメッセージを送信 (ユーザーへの案内)
            await new_channel.send(f"ようこそ、{interaction.user.mention} 様。チケットが開かれました。\nご用件をお聞かせください。")
            
        except discord.Forbidden:
            await interaction.followup.send("❌ チャンネル作成に必要な権限がありません。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)


class TicketCog(commands.Cog):
    """チケット機能（/チケットパネル設置 → ボタンで作成/削除、1通目/2通目の自動案内など）"""
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ticket_messages_file = "ticket_messages.json"
        self.ticket_messages = self._load_json(self.ticket_messages_file, cast_int_keys=True)
        self.settings_file = "ticket_settings.json"
        self.settings = self._load_json(self.settings_file)
        # self._view_registered = False # フラグは setup で代替

    # ---------- 永続データ (変更なし) ----------
    def _load_json(self, path: str, cast_int_keys: bool = False):
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                if os.path.getsize(path) > 0:
                    try:
                        data = json.load(f)
                        if cast_int_keys:
                            return {int(k): v for k, v in data.items()}
                        return data
                    except json.JSONDecodeError:
                        return {}
        return {}

    def _save_json(self, path: str, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)


    # ---------- コマンド (変更) ----------
    @app_commands.command( # 変更
        name="ticket-panel-set",
        description="このチャンネルにチケット作成パネルを設置します。（管理者専用）"
    )
    @app_commands.describe(
        title="パネルのタイトル",
        description="パネルの説明",
        button_label="ボタンのラベル"
    )
    async def set_ticket_panel(self, interaction: discord.Interaction, title: str, description: str, button_label: str = "🎫 チケットを作成"): # 変更: ctx -> interaction
        if interaction.user.guild_permissions is None or not interaction.user.guild_permissions.administrator: # 権限チェック
            return await interaction.response.send_message("❌ 管理者のみ実行できます。", ephemeral=True) 

        embed = discord.Embed(title=title, description=description, color=discord.Color.blue())
        view = PersistentView(self.bot)
        
        # ボタンのラベルを引数に応じて変更 (カスタムIDは固定)
        create_button = next((item for item in view.children if isinstance(item, TicketCreateButton)), None)
        if create_button:
            create_button.label = button_label
        
        await interaction.response.send_message("✅ チケットパネルを設置しました。", ephemeral=True) 
        await interaction.channel.send(embed=embed, view=view)

    @app_commands.command( # 変更
        name="ticket-staff-add",
        description="チケット対応を行うスタッフを追加します。（管理者専用）"
    )
    @app_commands.describe(
        user="スタッフに追加するユーザー"
    )
    async def add_staff(self, interaction: discord.Interaction, user: discord.Member): # 変更: ctx -> interaction
        if interaction.user.guild_permissions is None or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ 管理者のみ実行できます。", ephemeral=True)

        guild_id = str(interaction.guild_id)
        settings = self.settings.get(guild_id, {})
        staff_ids = settings.get("staff_ids", [])

        if user.id in staff_ids:
            return await interaction.response.send_message(f"❌ {user.mention} は既にスタッフに追加されています。", ephemeral=True)
            
        staff_ids.append(user.id)
        settings["staff_ids"] = staff_ids
        self.settings[guild_id] = settings
        self._save_json(self.settings_file, self.settings)
        
        await interaction.response.send_message(f"✅ スタッフに **{user.mention}** を追加しました。", ephemeral=True) 

    @app_commands.command( # 変更
        name="ticket-staff-remove",
        description="チケット対応を行うスタッフを削除します。（管理者専用）"
    )
    @app_commands.describe(
        user="スタッフから削除するユーザー"
    )
    async def remove_staff(self, interaction: discord.Interaction, user: discord.Member): # 変更: ctx -> interaction
        if interaction.user.guild_permissions is None or not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ 管理者のみ実行できます。", ephemeral=True)
            
        guild_id = str(interaction.guild_id)
        settings = self.settings.get(guild_id, {})
        staff_ids = settings.get("staff_ids", [])
        
        if user.id not in staff_ids:
            return await interaction.response.send_message(f"❌ {user.mention} はスタッフリストにいません。", ephemeral=True)
            
        staff_ids.remove(user.id)
        settings["staff_ids"] = staff_ids
        self.settings[guild_id] = settings
        self._save_json(self.settings_file, self.settings)
        
        await interaction.response.send_message(f"✅ スタッフから **{user.mention}** を削除しました。", ephemeral=True) 
        
    # ---------- イベントリスナー (変更なし) ----------
    @commands.Cog.listener()
    async def on_ready(self):
        # 永続Viewの再開
        self.bot.add_view(PersistentView(self.bot))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        cid = message.channel.id
        if cid not in self.ticket_messages:
            return

        self.ticket_messages[cid] += 1
        self._save_json(self.ticket_messages_file, self.ticket_messages)
        count = self.ticket_messages[cid]

        if count == 1:
            embed = discord.Embed(
                title="チケット作成ありがとうございます",
                description=(
                    "ぷにぷに代行の依頼の場合はメールアドレスとパスワードと依頼内容と受け取りリンク又は支払いリンクをお願いします\n"
                    "にゃんこ代行の依頼の場合は引き継ぎコードと認証番号と依頼内容と受け取りリンク又は支払いリンクをお願いします\n"
                    "ツムツム代行の依頼の場合はLINEのメールアドレスとパスワードと受け取りリンク又は支払いリンクをお願いします\n"
                    "その他の代行の依頼の場合は担当者をお待ち下さい"
                ),
                color=discord.Color.blue(),
            )
            await message.channel.send(embed=embed)
        elif count == 2:
            settings = self.settings.get(str(message.guild.id), {})
            staff_ids = settings.get("staff_ids", [])
            mentions = " ".join([f"<@{sid}>" for sid in staff_ids])
            embed = discord.Embed(title="依頼ありがとうございます", description="担当者が対応致しますので、しばらくお待ちください。", color=discord.Color.orange())
            await message.channel.send(content=mentions, embed=embed)

async def setup(bot): # 変更: async setup
    await bot.add_cog(TicketCog(bot)) # 変更: await