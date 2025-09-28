import discord
from discord.ext import commands
from discord import app_commands # 最新のコマンド定義に使用
from typing import Optional 
import asyncio # on_timeoutで非同期処理を使うためインポート

# Discord BotのオーナーID。必要に応じて変更してください。
HELP_OWNER_ID = 1418975779156394156 

# ---- ページング用 View ----
class HelpPaginatorView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], start_page: int = 0):
        super().__init__(timeout=180) # タイムアウトを180秒に設定
        self.pages = pages
        self.index = start_page
        self.total_pages = len(pages)
        self.message: Optional[discord.Message] = None
        self.update_buttons()
    
    # ★★★ 修正箇所: get_itemをクラスのメソッドとして定義 ★★★
    def get_item(self, custom_id: str) -> Optional[discord.ui.Item]:
        """カスタムIDに基づいてビューアイテムを取得します。"""
        # self.childrenからカスタムIDを持つアイテムを探す
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)) and getattr(item, 'custom_id', None) == custom_id:
                return item
        return None
    # ★★★ 修正終わり ★★★

    def update_buttons(self):
        """ページ番号に応じてボタンの有効/無効を更新"""
        # get_item を使用してカスタムIDでボタンを取得
        prev_btn = self.get_item("help_prev")
        next_btn = self.get_item("help_next")
        
        if prev_btn:
             prev_btn.disabled = (self.index == 0)
        if next_btn:
            next_btn.disabled = (self.index >= self.total_pages - 1)


    async def show(self, interaction: discord.Interaction):
        """ページ内容を編集して表示する"""
        self.update_buttons()
        # interaction.response.edit_message を使用してメッセージを更新
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    # 修正: コールバックの引数を (self, interaction: discord.Interaction) に統一
    @discord.ui.button(label="◀ 前のページへ", style=discord.ButtonStyle.secondary, custom_id="help_prev")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button): # button引数も追加
        if self.index > 0:
            self.index -= 1
        await self.show(interaction)

    # 修正: コールバックの引数を (self, interaction: discord.Interaction) に統一
    @discord.ui.button(label="次のページへ ▶", style=discord.ButtonStyle.primary, custom_id="help_next")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button): # button引数も追加
        if self.index < len(self.pages) - 1:
            self.index += 1
        await self.show(interaction)
    
    async def on_timeout(self) -> None:
        """タイムアウト時にボタンを無効化する"""
        if self.message:
            try:
                # self.message があれば編集を試みる
                for item in self.children:
                    if hasattr(item, 'disabled'):
                        item.disabled = True
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass
        

class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # app_commands.command を使用するために、コマンドをボットツリーに追加する準備をする

    # =========================
    # /help コマンド (app_commands.command を使用)
    # =========================
    @app_commands.command(
        name="help", 
        description="このBOTの全機能一覧をページ形式で表示します。"
    )
    @app_commands.describe(
        page="表示したいページ番号。",
        ephemeral="他の人に見せない(True)/見せる(False)を設定します。"
    )
    async def help_command(self, interaction: discord.Interaction, page: app_commands.Range[int, 1] = None, ephemeral: bool = True):
        # interaction.response.defer() で応答を保留
        await interaction.response.defer(ephemeral=ephemeral)

        pages = []
        # 全機能の洗い出しに基づき、全6ページに再構成
        total_pages = 6
        
        # --- 1ページ目：PayPay管理 (6コマンド) ---
        p1 = discord.Embed(
            title=f"📖 機能一覧 1/{total_pages}：PayPay管理",
            description="PayPayアカウントに関する全ての操作コマンド",
            color=discord.Color.blue()
        )
        p1.add_field(name="/login_paypay", value="電話番号とパスワードでPayPayにログインしセッションを作成します。", inline=False)
        p1.add_field(name="/paypay-acc-check", value="現在ログイン中のPayPayアカウント情報を確認します。", inline=False)
        p1.add_field(name="/paypay-balance-check", value="現在のPayPay残高（総残高・使用可能残高など）を確認します。", inline=False)
        p1.add_field(name="/paypay-link-create", value="指定した金額のPayPay送金リンクを作成します。", inline=False)
        p1.add_field(name="/paypay-qr-create", value="PayPayの請求QRコード用リンクを作成します。", inline=False)
        p1.add_field(name="/paypay-send-user", value="指定した金額をPayPayで指定ユーザー（ID/電話番号）に送金します。", inline=False)
        pages.append(p1)

        # --- 2ページ目：自販機管理 (6コマンド) ---
        p2 = discord.Embed(
            title=f"📖 機能一覧 2/{total_pages}：自動販売機",
            description="自動販売機の作成・商品管理に関するコマンド",
            color=discord.Color.green()
        )
        p2.add_field(name="/vm-create", value="新しい自動販売機（パネル）を作成します。", inline=False)
        p2.add_field(name="/vm-add-product", value="自販機に新しい商品を追加または既存の商品を編集します。", inline=False)
        p2.add_field(name="/vm-add-stock", value="自販機の商品に在庫（アイテム内容）を追加します。", inline=False)
        p2.add_field(name="/vm-list", value="このサーバーの自販機の一覧を表示します。", inline=False)
        p2.add_field(name="/vm-delete", value="自販機を完全に削除します。", inline=False)
        p2.add_field(name="/vm-notify-channel", value="自販機の購入通知を送るチャンネルを設定します。", inline=False)
        pages.append(p2)
        
        # --- 3ページ目：代行・チケット (4コマンド) ---
        p3 = discord.Embed(
            title=f"📖 機能一覧 3/{total_pages}：チケット・便利コマンド",
            description="購入・依頼用の個別チャンネルの管理コマンド",
            color=discord.Color.purple()
        )
        p3.add_field(name="/ticket", value="チケット作成ボタンが設置されたパネルを作成します。", inline=False)
        p3.add_field(name="/youtube-download", value="YouTubeの動画を指定したフォーマットでダウンロードします。", inline=False)
        p3.add_field(name="/slot_create", value="一時的な個別チャンネル（スロット）を作成します。", inline=False)
        pages.append(p3)

        # --- 4ページ目：IPAパッチ (2コマンド) ---
        p4 = discord.Embed(
            title=f"📖 機能一覧 4/{total_pages}：IPAパッチ",
            description="IPAファイル（iOSアプリ）の改造に関するコマンド",
            color=discord.Color.red()
        )
        p4.add_field(name="/offset-set", value="IPAパッチに使用するオフセット情報（改造箇所）を登録します。", inline=False)
        p4.add_field(name="/offset-patch", value="P12証明書とIPAファイルを使用してパッチを適用します。", inline=False)
        pages.append(p4)
        
        # --- 5ページ目：バックアップ認証 (5コマンド) ---
        p5 = discord.Embed(
            title=f"📖 機能一覧 5/{total_pages}：バックアップ認証",
            description="メンバーの認証情報バックアップと復元に関するコマンド",
            color=discord.Color.orange()
        )
        p5.add_field(name="/backup-verify", value="復元可能な認証を設置できます。", inline=False)
        p5.add_field(name="/backup-call", value="認証済みメンバーをサーバーに呼び戻す処理を実行します。", inline=False)
        p5.add_field(name="/backup-count", value="バックアップに登録されている認証済みメンバーの総数を表示します。", inline=False)
        p5.add_field(name="/bot-link", value="BOTが導入されているサーバー情報と招待リンクをEmbedで表示します。", inline=False)
        pages.append(p5)

        # --- 6ページ目：LEVEL5 ID・その他ユーティリティ (4コマンド) ---
        # ★★★ 修正箇所: level5-auto を level5-create に変更し、ログイン/acc-checkを修正後の内容に合わせる ★★★
        p6 = discord.Embed(
            title=f"📖 機能一覧 6/{total_pages}：ぷにぷに系統",
            description="「妖怪ウォッチぷにぷに」に関するコマンド",
            color=discord.Color.yellow()
        )
        p6.add_field(name="/level5-create", value="一時メールとランダムまたは指定パスワードでLEVEL5 IDを自動生成します。", inline=False)
        p6.add_field(name="/level5-show", value="保存済みLEVEL5 IDアカウント情報の一覧を確認します。", inline=False)
        p6.add_field(name="/level5-pass-change", value="LEVEL5 IDのパスワードを変更します。", inline=False)
        p6.add_field(name="/level5-email-change", value="LEVEL5 IDのメールアドレスを変更します。", inline=False)
        pages.append(p6)
        # ★★★ 修正終わり ★★★


        # ページ指定の処理
        start_idx = (page - 1) if page and 1 <= page <= len(pages) else 0
        
        view = HelpPaginatorView(pages, start_page=start_idx)
        # followup.send で送信し、メッセージオブジェクトを View に渡す
        view.message = await interaction.followup.send(embed=pages[start_idx], view=view, ephemeral=ephemeral)


    # =========================
    # /debug-commands（オーナー専用） (app_commands.command を使用)
    # =========================
    @app_commands.command(name="debug-commands", description="このサーバーで見えるコマンド名一覧（オーナー専用）")
    async def debug_commands(self, interaction: discord.Interaction, ephemeral: bool = True):
        # interaction.user.id でオーナー認証
        if interaction.user.id != HELP_OWNER_ID: 
            return await interaction.response.send_message("❌ オーナー専用コマンドです。", ephemeral=True) 

        # 応答を保留 (defer)
        await interaction.response.defer(ephemeral=ephemeral)
        
        try:
            command_list = []
            
            # bot.tree.get_commands(guild=interaction.guild) を使うのがより正確
            # ただし、commands属性が取得できればそちらを使用
            commands_obj = getattr(self.bot, 'all_slash_commands', self.bot.commands) 
            
            # commands.Cog の commands 属性を直接イテレートするのは困難な場合があるため、
            # bot.treeから取得するのが最も確実だが、ここでは単純なイテレーションを試みる
            if hasattr(self.bot, 'tree'):
                app_commands_list = await self.bot.tree.fetch_commands(guild=interaction.guild_id) if interaction.guild_id else await self.bot.tree.fetch_commands()
                for command in app_commands_list:
                    command_list.append(f"/{command.name}: {command.description}")
            
            if not command_list:
                msg = "このサーバーには登録されているスラッシュコマンドが見つかりませんでした。"
            else:
                msg = "このサーバーで利用可能なコマンド一覧:\n" + "\n".join(command_list)
                
            await interaction.followup.send(msg, ephemeral=ephemeral) 
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {e}", ephemeral=True)


async def setup(bot):
    # Cog を追加
    await bot.add_cog(HelpCog(bot))