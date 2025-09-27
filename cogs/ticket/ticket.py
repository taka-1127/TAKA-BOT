import discord
from discord.ext import commands
from discord import app_commands, SelectOption, ButtonStyle, ChannelType
from discord.ui import Button, View, Select
import json
import os
import asyncio
from typing import Optional, Dict, Any, List, Union
from pathlib import Path

# =========================================================
# ファイルパス設定 (Botのルートディレクトリを参照し、自動生成をサポート)
# =========================================================
# cogs/ticket.py が 'cogs' フォルダ内にあることを前提とし、親の親ディレクトリ（ルート）を参照
BASE_DIR = Path(__file__).parent.parent.parent 
# Botのルートディレクトリにファイルを保存する
TICKET_DATA_FILE = BASE_DIR / "ticket_data.json"
TICKET_PANEL_SETTINGS_FILE = BASE_DIR / "ticket_panel_settings.json" 

# =========================================================
# ヘルパー関数とデータ管理
# =========================================================
def _load_json(file_path: Path):
    """JSONファイルからデータを読み込む (存在しない場合は自動生成し、空の辞書を返す)"""
    if not file_path.exists():
        # ファイルが存在しない場合、空の辞書を保存し、自動生成する
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        return {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # JSONが空の場合（ファイルが存在するが中身が空の場合）
            if not data:
                return {}
            return data
    except json.JSONDecodeError:
        # JSONが破損している場合
        return {}
    except Exception as e:
        print(f"Error loading {file_path.name}: {e}")
        return {}

def _save_json(file_path: Path, data: Dict[str, Any]):
    """JSONファイルにデータを保存する"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving {file_path.name}: {e}")

# 初期ロード (ここでファイルが存在しない場合は自動生成される)
ticket_data: Dict[str, Dict[str, Union[str, List[str]]]] = _load_json(TICKET_DATA_FILE)
panel_settings: Dict[str, Dict[str, str]] = _load_json(TICKET_PANEL_SETTINGS_FILE)


def create_error_embed(description: str) -> discord.Embed:
    """赤色のエラーメッセージEmbedを作成する"""
    return discord.Embed(
        title="⛔ 権限不足エラー",
        description=description,
        color=discord.Color.red()
    )

async def _update_channel_name(channel: discord.TextChannel, opener: discord.Member, handler_ids: List[str]):
    """チャンネル名を更新するロジック"""
    safe_opener_name = opener.name.lower().replace(' ', '-').replace('.', '')
    
    handler_name_suffix = ""
    if handler_ids:
        last_handler_id = handler_ids[-1]
        last_handler = channel.guild.get_member(int(last_handler_id))
        if last_handler:
            safe_handler_name = last_handler.display_name.lower().replace(' ', '-').replace('.', '')
            handler_name_suffix = f"_{safe_handler_name}"
        
    new_name = f"ticket-{safe_opener_name}{handler_name_suffix}_対応"
    
    if len(new_name) > 100:
        new_name = new_name[:100]

    if channel.name != new_name:
        try:
            await channel.edit(name=new_name, reason="対応者の変更に伴うチケットチャンネル名の更新")
        except discord.HTTPException as e:
            print(f"チャンネル名の変更に失敗しました: {e}")

# =========================================================
# カスタム View (ボタンとセレクトメニュー)
# =========================================================

# --- 対応者削除 確認 View ---
class ConfirmRemoveView(View):
    def __init__(self, bot: commands.Bot, target_id: str, opener_id: str):
        super().__init__(timeout=60)
        self.bot = bot
        self.target_id = target_id
        self.opener_id = opener_id

    @discord.ui.button(label="👍はい", style=ButtonStyle.green)
    async def confirm_remove(self, interaction: discord.Interaction, button: Button):
        channel_id = str(interaction.channel_id)
        global ticket_data
        
        if channel_id not in ticket_data:
            return await interaction.response.edit_message(embed=create_error_embed("チケットデータが見つかりません。"), view=None)

        handler_ids = ticket_data[channel_id].get("handler_ids", [])
        
        new_handler_ids = [h_id for h_id in handler_ids if h_id != self.target_id]
        
        ticket_data[channel_id]["handler_ids"] = new_handler_ids
        _save_json(TICKET_DATA_FILE, ticket_data)

        opener = interaction.guild.get_member(int(self.opener_id))
        if opener:
            await _update_channel_name(interaction.channel, opener, new_handler_ids)
        
        target_member = interaction.guild.get_member(int(self.target_id))
        if target_member:
            await interaction.channel.set_permissions(target_member, overwrite=None) 

        await interaction.response.edit_message(
            embed=discord.Embed(
                description=f"✅ 該当する対応者を削除しました。\n現在対応者は **{len(new_handler_ids)}** 人です。",
                color=discord.Color.green()
            ),
            view=None
        )

    @discord.ui.button(label="👎いいえ", style=ButtonStyle.red)
    async def cancel_remove(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            embed=discord.Embed(title="キャンセルしました", description="削除は実行されませんでした。", color=discord.Color.yellow()),
            view=None
        )

# --- 対応者削除セレクトメニュー View ---
class HandlerSelectView(View):
    def __init__(self, bot: commands.Bot, current_handler_ids: List[str], opener_id: str):
        super().__init__(timeout=60)
        self.bot = bot
        self.opener_id = opener_id
        
        options: List[SelectOption] = []
        for handler_id in set(current_handler_ids):
            member = self.bot.get_user(int(handler_id))
            if member:
                options.append(SelectOption(label=member.display_name, value=handler_id))
        
        self.select_menu = Select(
            placeholder="削除したい対応者を選択",
            options=options,
            custom_id="handler_remove_select"
        )
        self.select_menu.callback = self.select_callback
        self.add_item(self.select_menu)

    async def select_callback(self, interaction: discord.Interaction):
        selected_id = interaction.data['values'][0]
        selected_user = self.bot.get_user(int(selected_id))

        await interaction.response.edit_message(
            embed=discord.Embed(
                title="確認", 
                description=f"本当に **{selected_user.display_name}** 様を削除しますか？",
                color=discord.Color.orange()
            ),
            view=ConfirmRemoveView(self.bot, selected_id, self.opener_id),
            attachments=[],
        )

# --- 閉じる確認 View ---
class ConfirmCloseView(View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None) # 永続 View
        self.bot = bot

    @discord.ui.button(label="👍はい", style=ButtonStyle.green, custom_id="confirm_close_yes")
    async def confirm_close(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="チケットを閉じます", 
                description="5秒後にこのチケットチャンネルは削除されます。", 
                color=discord.Color.orange()
            ),
            view=None
        )
        
        channel_id = str(interaction.channel_id)
        global ticket_data
        if channel_id in ticket_data:
            del ticket_data[channel_id]
            _save_json(TICKET_DATA_FILE, ticket_data)
        
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"チケットクローズ by {interaction.user.name}")
        except:
            pass

    @discord.ui.button(label="👎いいえ", style=ButtonStyle.red, custom_id="confirm_close_no")
    async def cancel_close(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            embed=discord.Embed(title="キャンセルしました", description="チケットはそのまま残ります。", color=discord.Color.green()),
            view=None
        )

# --- チケット操作 View (チャンネル内に送信されるボタン) ---
class TicketInitialView(View):
    def __init__(self, bot: commands.Bot, opener_id: str, staff_role_id: str):
        super().__init__(timeout=None) 
        self.bot = bot
        self.opener_id = opener_id
        self.staff_role_id = staff_role_id

    async def _check_staff_permission(self, interaction: discord.Interaction, for_close: bool = False) -> bool:
        """対応スタッフロールまたはAdmin権限をチェックする"""
        is_admin = interaction.user.guild_permissions.administrator
        is_opener = str(interaction.user.id) == self.opener_id
        is_staff = False

        if self.staff_role_id:
            staff_role = interaction.guild.get_role(int(self.staff_role_id))
            if staff_role and staff_role in interaction.user.roles:
                is_staff = True
        
        # 閉じる操作の場合: 作成者、スタッフ、AdminのいずれかであればOK
        if for_close and (is_admin or is_opener or is_staff):
             return True
        
        # 対応/削除操作の場合: スタッフ、AdminであればOK
        if not for_close and (is_admin or is_staff):
            return True
        
        # 権限不足の場合
        error_msg = "この操作を実行するには、**対応スタッフロール**または**管理者権限**が必要です。"
        if for_close:
             error_msg = "チケットを閉じるには、**作成者**、**対応スタッフ**または**管理者権限**が必要です。"
             
        await interaction.response.send_message(
            embed=create_error_embed(error_msg),
            ephemeral=True
        )
        return False

    # --- 閉じるボタン ---
    @discord.ui.button(label="閉じる", style=ButtonStyle.danger, custom_id="ticket_close")
    async def close_button(self, interaction: discord.Interaction, button: Button):
        if not await self._check_staff_permission(interaction, for_close=True):
            return

        await interaction.response.send_message(
            embed=discord.Embed(title="⚠️ 本当に閉じますか？", description="この操作は元に戻せません。", color=discord.Color.yellow()),
            view=ConfirmCloseView(self.bot),
            ephemeral=True
        )

    # --- 対応するボタン ---
    @discord.ui.button(label="このチケットを対応する", style=ButtonStyle.success, custom_id="ticket_handle")
    async def handle_button(self, interaction: discord.Interaction, button: Button):
        if not await self._check_staff_permission(interaction):
            return

        channel_id = str(interaction.channel_id)
        user_id = str(interaction.user.id)
        global ticket_data
        
        if channel_id not in ticket_data:
            return await interaction.response.send_message(embed=create_error_embed("チケットデータが見つかりません。"), ephemeral=True)
        
        handler_ids = ticket_data[channel_id].get("handler_ids", [])
        opener_id = ticket_data[channel_id]["opener_id"]

        await interaction.channel.set_permissions(interaction.user, view_channel=True, send_messages=True)
        
        if user_id in handler_ids:
            handler_ids.remove(user_id) 
        handler_ids.append(user_id) 
            
        ticket_data[channel_id]["handler_ids"] = handler_ids
        _save_json(TICKET_DATA_FILE, ticket_data)

        opener = interaction.guild.get_member(int(opener_id))
        if opener:
            await _update_channel_name(interaction.channel, opener, handler_ids)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ {interaction.user.mention} 様を対応者に追加しました。\nチャンネル名に反映されています。",
                color=discord.Color.green()
            ),
            ephemeral=False 
        )
        
    # --- 対応者を削除するボタン ---
    @discord.ui.button(label="対応者を削除する", style=ButtonStyle.secondary, custom_id="ticket_remove_handler")
    async def remove_handler_button(self, interaction: discord.Interaction, button: Button):
        if not await self._check_staff_permission(interaction):
            return

        channel_id = str(interaction.channel_id)
        global ticket_data

        if channel_id not in ticket_data:
            return await interaction.response.send_message(embed=create_error_embed("チケットデータが見つかりません。"), ephemeral=True)

        handler_ids = ticket_data[channel_id].get("handler_ids", [])
        opener_id = ticket_data[channel_id]["opener_id"]
        
        if not handler_ids:
            return await interaction.response.send_message("❌ 現在、対応者は登録されていません。", ephemeral=True)

        await interaction.response.send_message(
            embed=discord.Embed(title="対応者削除", description="削除したい対応者をセレクトメニューから選択してください。", color=discord.Color.blue()),
            view=HandlerSelectView(self.bot, handler_ids, opener_id),
            ephemeral=True
        )

# --- チケットパネルのボタン ---
class TicketPanelButton(discord.ui.Button):
    def __init__(self, label, custom_id):
        super().__init__(label=label, style=ButtonStyle.primary, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        settings = panel_settings.get(str(interaction.guild_id))
        if not settings:
            return await interaction.followup.send("❌ チケットパネルの設定が見つかりません。`/ticket` コマンドで設定してください。", ephemeral=True)
            
        category_id = settings.get("category_id")
        staff_role_id = settings.get("staff_role_id")
        welcome_message = settings.get("welcome_message", "ご用件をお聞かせください。")
        
        category = interaction.guild.get_channel(int(category_id))
        if not category or category.type != ChannelType.category:
            return await interaction.followup.send("❌ 設定されたカテゴリーが見つかりません。", ephemeral=True)

        opener_name = interaction.user.name.lower().replace(' ', '-').replace('.', '')
        
        for channel in interaction.guild.channels:
            if channel.name.startswith(f"ticket-{opener_name}"):
                return await interaction.followup.send(f"❌ 既にチケット <#{channel.id}> が開かれています。", ephemeral=True)

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        if staff_role_id:
            staff_role = interaction.guild.get_role(int(staff_role_id))
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
                
        try:
            new_channel = await interaction.guild.create_text_channel(
                name=f"ticket-{opener_name}",
                category=category,
                overwrites=overwrites,
                reason=f"チケット作成: {interaction.user.name}"
            )
        except discord.Forbidden:
            return await interaction.followup.send("❌ チャンネルを作成する権限がありません。", ephemeral=True)

        welcome_embed = discord.Embed(
            title="🎫 チケットが開かれました",
            description=f"ようこそ、{interaction.user.mention} 様。\n{welcome_message}",
            color=discord.Color.green()
        )
        
        global ticket_data
        ticket_data[str(new_channel.id)] = {
            "opener_id": str(interaction.user.id),
            "handler_ids": []
        }
        _save_json(TICKET_DATA_FILE, ticket_data)

        await new_channel.send(
            embed=welcome_embed,
            view=TicketInitialView(self.bot, str(interaction.user.id), staff_role_id)
        )
        
        await interaction.followup.send(f"✅ チケット <#{new_channel.id}> を作成しました。", ephemeral=True)


# =========================================================
# Discord コグ
# =========================================================
class TicketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(ConfirmCloseView(self.bot))

    @commands.Cog.listener()
    async def on_ready(self):
        # ⚠️ コマンドが消える問題への対処: 起動時にグローバルに同期 ⚠️
        try:
            # ギルドIDを指定しないグローバル同期
            await self.bot.tree.sync() 
            print("INFO: Slash commands synced globally.")
        except Exception as e:
            print(f"ERROR: Failed to sync slash commands: {e}")

        # Bot再起動時、永続的なボタンを復元
        global panel_settings
        panel_settings = _load_json(TICKET_PANEL_SETTINGS_FILE) 

        for guild_id, settings in panel_settings.items():
            label = settings.get("label", "🎫 チケットを作成")
            custom_id = f"ticket_create_button_{guild_id}"
            
            view = View(timeout=None)
            view.add_item(TicketPanelButton(label, custom_id=custom_id))
            self.bot.add_view(view)

            staff_role_id = settings.get("staff_role_id")
            global ticket_data
            ticket_data = _load_json(TICKET_DATA_FILE)
            for channel_id, data in ticket_data.items():
                if self.bot.get_channel(int(channel_id)):
                     self.bot.add_view(TicketInitialView(self.bot, data["opener_id"], staff_role_id))


    # --- /ticket コマンド (パネル設置) ---
    @app_commands.command(
        name="ticket",
        description="チケットパネルを設置します。カテゴリーやロールを指定できます。"
    )
    @app_commands.describe(
        category="チケットチャンネルを作成するカテゴリー",
        role="チケット対応スタッフが持つロール（このロールを持つ人のみがボタン操作可）",
        title="Embedのタイトル（任意）",
        description="Embedの説明（小さい文字）（任意）",
        image="Embedの下部に表示する画像URL（任意）",
        label="ボタンに表示するテキスト（任意）",
        welcome="チケット作成時にチャンネルに送る歓迎メッセージ（任意）"
    )
    @app_commands.default_permissions(administrator=True)
    async def ticket_panel(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel,
        role: discord.Role,
        title: Optional[str] = "サポートチケット",
        description: Optional[str] = "サポートが必要な場合は、下のボタンを押してチケットを作成してください。",
        image: Optional[str] = None,
        label: Optional[str] = "🎫 チケットを作成",
        welcome: Optional[str] = "ご用件をお聞かせください。"
    ):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)
        panel_settings[guild_id] = {
            "category_id": str(category.id),
            "staff_role_id": str(role.id),
            "welcome_message": welcome,
            "label": label
        }
        _save_json(TICKET_PANEL_SETTINGS_FILE, panel_settings)

        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue()
        )
        if image:
            embed.set_image(url=image)

        # 既存のビューがあれば削除し、新しいビューを登録し直すことで重複を防ぐ
        custom_id = f"ticket_create_button_{guild_id}"
        view = View(timeout=None) 
        view.add_item(TicketPanelButton(label, custom_id=custom_id))

        await interaction.channel.send(embed=embed, view=view)

        await interaction.followup.send("✅ チケットパネルを正常に設置しました。Botを再起動してもボタンは機能し続けます。", ephemeral=True)


async def setup(bot: commands.Bot):
    # JSONファイルをロードして初期化
    global ticket_data
    global panel_settings
    ticket_data = _load_json(TICKET_DATA_FILE)
    panel_settings = _load_json(TICKET_PANEL_SETTINGS_FILE)
    
    await bot.add_cog(TicketCog(bot))
    bot.add_view(ConfirmCloseView(bot))