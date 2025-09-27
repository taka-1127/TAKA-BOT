import discord
from discord.ext import commands
from discord import app_commands, SelectOption, ButtonStyle, ChannelType
from discord.ui import Button, View, Select
import json
import os
import asyncio
from typing import Optional, Dict, Any, List, Union

# =========================================================
# ファイルパス設定
# =========================================================
# チケットごとの対応者情報や開いた人を管理
TICKET_DATA_FILE = "ticket_data.json"
# チケットパネル設置時の設定（カテゴリー、ロールなど）を保持
TICKET_PANEL_SETTINGS_FILE = "ticket_panel_settings.json" 

# =========================================================
# ヘルパー関数とデータ管理
# =========================================================
def _load_json(file_path):
    """JSONファイルからデータを読み込む"""
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def _save_json(file_path, data):
    """JSONファイルにデータを保存する"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# チケットごとの対応者情報を管理する辞書
ticket_data: Dict[str, Dict[str, Union[str, List[str]]]] = _load_json(TICKET_DATA_FILE)

# パネル設置設定を管理する辞書
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
    # チャンネル名に使用できない文字を削除・置換
    safe_opener_name = opener.name.lower().replace(' ', '-').replace('.', '')
    
    handler_name_suffix = ""
    if handler_ids:
        # ユーザーの要求: 「最後に押した人の名前になる」
        last_handler_id = handler_ids[-1]
        last_handler = channel.guild.get_member(int(last_handler_id))
        if last_handler:
            # チャンネル名に使用できない文字を削除・置換
            safe_handler_name = last_handler.display_name.lower().replace(' ', '-').replace('.', '')
            handler_name_suffix = f"_{safe_handler_name}"
        
    new_name = f"ticket-{safe_opener_name}{handler_name_suffix}_対応"
    
    # Discordのチャンネル名の制限 (100文字) を考慮
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
        
        # ターゲットIDの全てのインスタンスをリストから削除
        new_handler_ids = [h_id for h_id in handler_ids if h_id != self.target_id]
        
        ticket_data[channel_id]["handler_ids"] = new_handler_ids
        _save_json(TICKET_DATA_FILE, ticket_data)

        # チャンネル名更新
        opener = interaction.guild.get_member(int(self.opener_id))
        if opener:
            await _update_channel_name(interaction.channel, opener, new_handler_ids)
        
        # チャンネルの権限から削除 (念のため)
        target_member = interaction.guild.get_member(int(self.target_id))
        if target_member:
            await interaction.channel.set_permissions(target_member, overwrite=None) # 権限をリセット

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
        # 対応者リストから重複を除去してオプションを作成
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
        super().__init__(timeout=60)
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
        
        # チケットデータから削除
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

# --- チケット操作 View ---
class TicketInitialView(View):
    def __init__(self, bot: commands.Bot, opener_id: str, staff_role_id: str):
        super().__init__(timeout=None) # 永続 View
        self.bot = bot
        self.opener_id = opener_id
        self.staff_role_id = staff_role_id

    async def _check_staff_permission(self, interaction: discord.Interaction) -> bool:
        """スタッフロールまたはAdmin権限をチェックする"""
        if not self.staff_role_id:
            # ロール設定がない場合、Admin権限があればOK
            if interaction.user.guild_permissions.administrator:
                return True
        else:
            staff_role = interaction.guild.get_role(int(self.staff_role_id))
            if staff_role and staff_role in interaction.user.roles:
                return True
        
        # チャンネル作成者またはAdmin権限でもOK (閉じる操作のため)
        if str(interaction.user.id) == self.opener_id or interaction.user.guild_permissions.administrator:
             return True

        # 権限不足の場合
        await interaction.response.send_message(
            embed=create_error_embed("この操作を実行するには、**対応スタッフロール**または**管理者権限**が必要です。"),
            ephemeral=True
        )
        return False

    # --- 閉じるボタン ---
    @discord.ui.button(label="閉じる", style=ButtonStyle.danger, custom_id="ticket_close")
    async def close_button(self, interaction: discord.Interaction, button: Button):
        # チャンネル作成者、スタッフ、Adminのいずれかであれば実行可能
        if not await self._check_staff_permission(interaction):
            return

        # 確認Viewを表示
        await interaction.response.send_message(
            embed=discord.Embed(title="⚠️ 本当に閉じますか？", description="この操作は元に戻せません。", color=discord.Color.yellow()),
            view=ConfirmCloseView(self.bot),
            ephemeral=True
        )

    # --- 対応するボタン ---
    @discord.ui.button(label="このチケットを対応する", style=ButtonStyle.success, custom_id="ticket_handle")
    async def handle_button(self, interaction: discord.Interaction, button: Button):
        # スタッフまたはAdmin権限が必要
        if not await self._check_staff_permission(interaction):
            return

        channel_id = str(interaction.channel_id)
        user_id = str(interaction.user.id)
        global ticket_data
        
        if channel_id not in ticket_data:
            return await interaction.response.send_message(embed=create_error_embed("チケットデータが見つかりません。"), ephemeral=True)
        
        handler_ids = ticket_data[channel_id].get("handler_ids", [])
        opener_id = ticket_data[channel_id]["opener_id"]

        # チャンネル権限の更新 (念のため対応者にも閲覧権限を追加)
        await interaction.channel.set_permissions(interaction.user, view_channel=True, send_messages=True)
        
        # 対応者を追加 (最後に押した人がリストの最後になり、チャンネル名に反映される)
        if user_id not in handler_ids:
             handler_ids.append(user_id)
        else:
            # 既にいる場合は、その要素を削除してリストの最後に移動させる (最後に押した人にするため)
            handler_ids.remove(user_id)
            handler_ids.append(user_id)
            
        ticket_data[channel_id]["handler_ids"] = handler_ids
        _save_json(TICKET_DATA_FILE, ticket_data)

        # チャンネル名更新
        opener = interaction.guild.get_member(int(opener_id))
        if opener:
            await _update_channel_name(interaction.channel, opener, handler_ids)

        await interaction.response.send_message(
            embed=discord.Embed(
                description=f"✅ {interaction.user.mention} 様を対応者に追加しました。\nチャンネル名に反映されています。",
                color=discord.Color.green()
            ),
            # この応答はチケットチャンネルで誰もが見えるように
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

        # 対応者選択メニューを表示
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
        
        # 設定のロード
        settings = panel_settings.get(str(interaction.guild_id))
        if not settings:
            return await interaction.followup.send("❌ チケットパネルの設定が見つかりません。", ephemeral=True)
            
        category_id = settings.get("category_id")
        staff_role_id = settings.get("staff_role_id")
        welcome_message = settings.get("welcome_message", "ご用件をお聞かせください。")
        
        category = interaction.guild.get_channel(int(category_id))
        if not category or category.type != ChannelType.category:
            return await interaction.followup.send("❌ 設定されたカテゴリーが見つかりません。", ephemeral=True)

        # チャンネル名 (例: ticket-ユーザー名)
        opener_name = interaction.user.name.lower().replace(' ', '-').replace('.', '')
        
        # 既存チェック
        for channel in interaction.guild.channels:
            if channel.name.startswith(f"ticket-{opener_name}"):
                return await interaction.followup.send(f"❌ 既にチケット <#{channel.id}> が開かれています。", ephemeral=True)

        # 権限設定
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        if staff_role_id:
            staff_role = interaction.guild.get_role(int(staff_role_id))
            if staff_role:
                # スタッフロールには閲覧・送信権限を付与
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

        # 1. 歓迎メッセージ Embed の作成
        welcome_embed = discord.Embed(
            title="🎫 チケットが開かれました",
            description=f"ようこそ、{interaction.user.mention} 様。\n{welcome_message}",
            color=discord.Color.green()
        )
        
        # 2. チケットデータに初期情報を保存
        global ticket_data
        ticket_data[str(new_channel.id)] = {
            "opener_id": str(interaction.user.id),
            "handler_ids": []
        }
        _save_json(TICKET_DATA_FILE, ticket_data)

        # 3. チャンネルにメッセージとボタンを送信
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
        # 永続Viewを登録 (on_readyで復元)
        self.bot.add_view(ConfirmCloseView(self.bot))

    @commands.Cog.listener()
    async def on_ready(self):
        # Bot再起動時、永続的なボタンを復元
        settings = _load_json(TICKET_PANEL_SETTINGS_FILE)
        for guild_id in settings:
            label = settings[guild_id].get("label", "🎫 チケットを作成")
            custom_id = f"ticket_create_button_{guild_id}"
            
            # TicketPanelButtonを含むViewを復元
            view = View(timeout=None)
            view.add_item(TicketPanelButton(label, custom_id=custom_id))
            self.bot.add_view(view)

            # TicketInitialViewも復元 (カスタムIDが動的ではないため)
            # チャンネル作成時に渡す引数が必要なため、この方法では完全な復元は難しいが、
            # 少なくともボタンの見た目だけは表示される。
            # 今回はチャンネル作成時に必要な情報をカスタムIDに含められないため、
            # コールバック内でデータを再取得する設計になっている。
            staff_role_id = settings[guild_id].get("staff_role_id")
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

        # 1. 設定の保存
        guild_id = str(interaction.guild_id)
        panel_settings[guild_id] = {
            "category_id": str(category.id),
            "staff_role_id": str(role.id),
            "welcome_message": welcome,
            "label": label
        }
        _save_json(TICKET_PANEL_SETTINGS_FILE, panel_settings)

        # 2. パネルEmbedの作成
        embed = discord.Embed(
            title=title,
            description=description,
            color=discord.Color.blue()
        )
        if image:
            embed.set_image(url=image)

        # 3. ボタンViewの作成
        view = View(timeout=None) # 永続 View
        custom_id = f"ticket_create_button_{guild_id}"
        view.add_item(TicketPanelButton(label, custom_id=custom_id))

        # 4. パネルの送信
        await interaction.channel.send(embed=embed, view=view)

        await interaction.followup.send("✅ チケットパネルを正常に設置しました。Botを再起動してもボタンは機能し続けます。", ephemeral=True)


async def setup(bot: commands.Bot):
    # JSONファイルをロードして初期化
    global ticket_data
    global panel_settings
    ticket_data = _load_json(TICKET_DATA_FILE)
    panel_settings = _load_json(TICKET_PANEL_SETTINGS_FILE)
    
    await bot.add_cog(TicketCog(bot))
    # チケット操作 View のカスタムIDを登録
    bot.add_view(ConfirmCloseView(bot))