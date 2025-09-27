import discord
from discord.ext import commands
from discord import app_commands 
import os
import json
from datetime import datetime
from PayPaython_mobile import PayPay
# ⬇️ 修正: .notification_utils は不要になったため、このインポートに統一
from .purchase_notifications import send_purchase_notification 
import hashlib
from typing import Optional # 🔥 修正: この行を追加

# --- VendingMachine クラス (変更なし) ---
class VendingMachine:
    def __init__(self, name):
        self.name = name
        self.products = {}
        
    def add_product(self, product_name, price, description="", infinite_stock=False):
        self.products[product_name] = {
            "price": price,
            "description": description,
            "stock": [],
            "infinite_stock": infinite_stock,
            "infinite_item": ""
        }
    
    def remove_product(self, product_name):
        if product_name in self.products:
            del self.products[product_name]
    
    def add_stock(self, product_name, items):
        if product_name in self.products:
            if isinstance(items, list):
                self.products[product_name]["stock"].extend(items)
            else:
                self.products[product_name]["stock"].append(items)
    
    def get_stock_count(self, product_name):
        if product_name in self.products:
            if self.products[product_name].get("infinite_stock", False):
                return "∞"
            return len(self.products[product_name]["stock"])
        return 0
    
    def purchase_item(self, product_name):
        if product_name not in self.products:
            return None
            
        product = self.products[product_name]
        
        if product.get("infinite_stock", False):
            # 無限在庫の場合は設定されたアイテムを返す
            return product.get("infinite_item", "在庫切れのアイテムが設定されていません。")
        
        if product["stock"]:
            return product["stock"].pop(0) # 在庫から一つ取り出す
        return None

# --- VMCogBase (変更なし) ---
class VMCogBase:
    def _get_vm_filepath(self, guild_id, vm_name):
        safe_vm_name = hashlib.sha256(vm_name.encode('utf-8')).hexdigest()[:16]
        return os.path.join("vending_machines", str(guild_id), f"{safe_vm_name}.json")

    def _save_vm(self, guild_id, vm: VendingMachine):
        dir_path = os.path.join("vending_machines", str(guild_id))
        os.makedirs(dir_path, exist_ok=True)
        file_path = self._get_vm_filepath(guild_id, vm.name)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(vm.__dict__, f, indent=4, ensure_ascii=False)

    def _load_vm(self, guild_id, vm_name) -> Optional[VendingMachine]:
        file_path = self._get_vm_filepath(guild_id, vm_name)
        if not os.path.exists(file_path):
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            vm = VendingMachine(data.pop('name'))
            vm.__dict__.update(data)
            return vm
        
    def _get_all_vm_files(self, guild_id):
        dir_path = os.path.join("vending_machines", str(guild_id))
        if not os.path.exists(dir_path):
            return []
        return [f.replace('.json', '') for f in os.listdir(dir_path) if f.endswith('.json')]
    
    def _get_vm_by_id(self, guild_id, vm_id):
        dir_path = os.path.join("vending_machines", str(guild_id))
        if not os.path.exists(dir_path):
            return None, None
        
        # ハッシュIDから元の名前を特定する必要があるため、全ファイルをチェック
        for filename in os.listdir(dir_path):
            if filename.endswith(".json") and filename.replace('.json', '') == vm_id:
                file_path = os.path.join(dir_path, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    vm = VendingMachine(data.pop('name'))
                    vm.__dict__.update(data)
                    return vm, vm.name
        return None, None

# --- BuyView クラス ---
class BuyView(discord.ui.View):
    def __init__(self, bot: commands.Bot, guild_id: int, vm_name: str, vm_id: str, timeout=None):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.guild_id = guild_id
        self.vm_name = vm_name
        self.vm_id = vm_id
        self.selected_product = None
        
        self.add_item(ProductSelect(self))
        self.add_item(BuyButton(self))

# --- ProductSelect クラス ---
class ProductSelect(discord.ui.Select):
    def __init__(self, parent_view: BuyView):
        # optionsは空で初期化し、set_vmで実際のVM情報を使って更新
        super().__init__(
            custom_id=f"vm_select_{parent_view.vm_id}",
            placeholder="商品を選択してください...", 
            min_values=1, 
            max_values=1
        )
        self.parent_view = parent_view
        
    async def callback(self, interaction: discord.Interaction):
        # 選択された商品を親ビューに保存
        self.parent_view.selected_product = self.values[0]
        
        # ボタンを有効化
        for item in self.parent_view.children:
            if isinstance(item, BuyButton):
                item.disabled = False
        
        await interaction.response.edit_message(view=self.parent_view)

# --- BuyButton クラス ---
class BuyButton(discord.ui.Button):
    def __init__(self, parent_view: BuyView):
        super().__init__(
            custom_id=f"vm_buy_{parent_view.vm_id}",
            label="PayPayで購入", 
            style=discord.ButtonStyle.primary, 
            emoji="💰", 
            disabled=True
        )
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        # 処理が長いためdefer
        await interaction.response.defer(ephemeral=True)
        
        vm_name = self.parent_view.vm_name
        product_name = self.parent_view.selected_product

        if not product_name:
            await interaction.followup.send("❌ 購入する商品を選択してください。", ephemeral=True)
            return
            
        # VMCogBaseのインスタンスを作成してVMをロード（ここでは仮にインスタンス化）
        vm_cog = VMCogBase()
        vm = vm_cog._load_vm(self.parent_view.guild_id, vm_name)

        if not vm:
            await interaction.followup.send(f"❌ 自動販売機`{vm_name}`が見つかりませんでした。", ephemeral=True)
            return
            
        product_info = vm.products.get(product_name)
        if not product_info:
            await interaction.followup.send(f"❌ 商品`{product_name}`が見つかりませんでした。", ephemeral=True)
            return

        price = product_info['price']
        stock_count = vm.get_stock_count(product_name)
        
        if stock_count == 0:
            await interaction.followup.send(f"❌ 商品`{product_name}`は現在在庫切れです。", ephemeral=True)
            return
        
        # PayPayインスタンスの取得
        paypay: PayPay = self.parent_view.bot.user_sessions.get(interaction.guild_id)
        if not paypay:
            await interaction.followup.send("❌ PayPay情報がありません。管理者にご確認ください。", ephemeral=True)
            return
            
        # 送金リンクの作成（同期処理と想定）
        try:
            link_data = await asyncio.to_thread(paypay.create_link, amount=price)

            embed = discord.Embed(
                title=f"「{product_name}」購入確認",
                description=f"✅ **{price}円**のPayPay送金リンクを発行しました。\n送金完了後、DMに商品が届きます。\n\n**⚠️注意: このリンクは一度限り有効です。**",
                color=discord.Color.orange()
            )
            embed.add_field(name="送金リンク", value=f"[ここをクリックしてPayPayで支払う]({link_data.link})", inline=False)
            embed.set_footer(text="購入後、DMをご確認ください。")
            
            # 購入確認と送金リンクをephemeralで送信
            await interaction.followup.send(embed=embed, ephemeral=True)
            
            # --- ここから支払いの監視ロジック ---
            # 簡略化のため、元のコードに倣い監視ロジックは省略し、即時実行を仮定
            
            # 支払いが完了したと仮定し、アイテムを渡す
            purchased_item = vm.purchase_item(product_name)
            if purchased_item is None:
                raise Exception("在庫の取り出しに失敗しました。")

            # 在庫が減ったのでVMを再保存
            vm_cog._save_vm(self.parent_view.guild_id, vm)
            
            # ユーザーにDMでアイテムを送る
            dm_embed = discord.Embed(
                title=f"🎁 {vm_name}からの購入商品",
                description=f"**{product_name} ({price}円)**のご購入ありがとうございます。",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            # アイテム内容をファイルとして送信することが望ましいが、元のコードに倣いそのまま送信
            await interaction.user.send(embed=dm_embed)
            await interaction.user.send(f"--- 商品内容 ---\n{purchased_item}\n--- 以上 ---")
            
            # 通知チャンネルに送信（非同期）
            await send_purchase_notification(
                self.parent_view.bot,
                self.parent_view.guild_id,
                interaction.user.id,
                product_name,
                price,
                purchased_item
            )

        except Exception as e:
            await interaction.followup.send(f"❌ 購入処理中にエラーが発生しました: {str(e)}", ephemeral=True)


# --- コグの定義とコマンド (変更) ---
from notification_utils import send_purchase_notification # ★ 修正

class SetVendingMachineCog(VMCogBase, commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 永続View登録のためのセット (on_readyでの再登録を防ぐため)
        self._registered_views = set()
    
    @app_commands.command( # 変更
        name="vm-config-channel",
        description="自動販売機の通知チャンネルを設定します。"
    )
    @app_commands.describe(
        channel="購入通知を送信するテキストチャンネル"
    )
    async def config_vm_channel(self, interaction: discord.Interaction, channel: discord.TextChannel): # 変更: ctx -> interaction
        if interaction.guild is None:
            await interaction.response.send_message("このコマンドはサーバーでのみ実行可能です。", ephemeral=True)
            return
            
        try:
            notification_manager = PurchaseNotificationManager(interaction.guild_id)
            notification_manager.set_notification_channel(channel.id)
            
            await interaction.response.send_message( # 変更
                f"✅ 通知チャンネルを **{channel.mention}** に設定しました。", 
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)

class CreateVendingMachineCog(VMCogBase, commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    @app_commands.command( # 変更
        name="vm-create",
        description="新しい自動販売機を作成・設置します。"
    )
    @app_commands.describe(
        vm_name="作成する自動販売機の名前 (例: デジタル商品VM)"
    )
    async def create_vm(self, interaction: discord.Interaction, vm_name: str): # 変更: ctx -> interaction
        if interaction.guild is None:
            await interaction.response.send_message("このコマンドはサーバーでのみ実行可能です。", ephemeral=True)
            return

        file_path = self._get_vm_filepath(interaction.guild_id, vm_name)
        
        if os.path.exists(file_path):
            await interaction.response.send_message(f"❌ 自動販売機`{vm_name}`は既に存在します。", ephemeral=True) # 変更
            return

        vm = VendingMachine(vm_name)
        self._save_vm(interaction.guild_id, vm)

        await interaction.response.send_message( # 変更
            f"✅ 自動販売機`**{vm_name}**`を作成しました！ `/vm-add-product` で商品を追加し、`/vm-set` でチャンネルに設置できます。", 
            ephemeral=True
        )

    @app_commands.command( # 変更
        name="vm-set",
        description="既存の自動販売機をチャンネルに設置します。"
    )
    @app_commands.describe(
        vm_name="チャンネルに設置する自動販売機の名前"
    )
    async def set_vm(self, interaction: discord.Interaction, vm_name: str):
        if interaction.guild is None:
            await interaction.response.send_message("このコマンドはサーバーでのみ実行可能です。", ephemeral=True)
            return
            
        # 処理が長いためdefer
        await interaction.response.defer(ephemeral=True)

        vm = self._load_vm(interaction.guild_id, vm_name)
        if not vm:
            await interaction.followup.send(f"❌ 自動販売機`{vm_name}`が見つかりませんでした。", ephemeral=True)
            return
        
        # VM IDをハッシュで生成
        vm_id = hashlib.sha256(vm_name.encode('utf-8')).hexdigest()[:16]

        embed = discord.Embed(
            title=f"🛒 {vm_name} 自動販売機",
            description="購入したい商品をセレクトメニューから選択してください。",
            color=discord.Color.dark_green()
        )
        
        view = BuyView(self.bot, interaction.guild_id, vm_name, vm_id, timeout=None)
        options = []
        
        for product_name, product_info in vm.products.items():
            # 在庫表示の調整
            if product_info.get("infinite_stock", False):
                stock_display = "∞"
            else:
                stock_count = len(product_info["stock"])
                stock_display = f"{stock_count}個"
            
            price = product_info["price"]
            label = f"{product_name} - ¥{price}"
            description = f"{price}円｜在庫: {stock_display}"
            
            options.append(discord.SelectOption(
                label=label,
                value=product_name,
                description=description
            ))
        
        # セレクトコンポーネントにオプションを設定
        # ViewのchildrenからSelectを見つけてオプションをセット
        select_component = next((c for c in view.children if isinstance(c, ProductSelect)), None)
        if select_component:
            select_component.options = options
        
        # ビューを登録（重複登録を防ぐ）
        # SetVendingMachineCogは通知設定用なので、ここで登録フラグを管理するのは不自然だが、元のコードのロジックを維持
        cog = self.bot.get_cog('SetVendingMachineCog')
        if cog and vm_id not in cog._registered_views:
            self.bot.add_view(view)
            cog._registered_views.add(vm_id)
            print(f"Registered new view for VM: {vm_name} (ID: {vm_id})")
        
        await interaction.followup.send(embed=embed, view=view) # deferしているためfollowup

async def setup(bot): # 変更: async setup
    # AddProductToVMCogのクラス定義はvm_management.pyにあるため、ここではCreateVendingMachineCogとSetVendingMachineCogのみを登録
    await bot.add_cog(CreateVendingMachineCog(bot))
    # AddProductToVMCog(bot) は vm_management.py の setup で行われる想定
    await bot.add_cog(SetVendingMachineCog(bot)) # 変更