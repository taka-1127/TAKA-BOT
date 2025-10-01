# cogs/vending_machine.py

import discord
from discord.ext import commands
from discord import app_commands
import os
import json
from datetime import datetime
import asyncio
from typing import Optional, List
# 🔥 修正: VendingMachineクラスとファイル操作をvm_managementからインポート
from .vm_management import VendingMachine
# 🔥 修正: 通知関数を purchase_notifications.py からインポート
from .purchase_notifications import send_purchase_notification 

# --- UI Components (購入ロジックを含む) ---

class PurchaseButton(discord.ui.Button):
    def __init__(self, vm_id: str, product_name: str, custom_id: str):
        super().__init__(label="購入", style=discord.ButtonStyle.green, custom_id=custom_id)
        self.vm_id = vm_id
        self.product_name = product_name
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        # VMのロードと購入処理
        try:
            vm_data = VendingMachine.load_vm(self.vm_id)
            vm = VendingMachine.from_dict(vm_data)
            
            # アイテムを購入 (在庫が減る場合はvm_management側で保存される)
            item = vm.purchase_item(self.product_name)
            
            if not item:
                return await interaction.followup.send("❌ 在庫切れ、または商品が見つかりません。", ephemeral=True)
            
            # 購入通知を送信 (この関数は purchase_notifications.py で定義されています)
            await send_purchase_notification(
                bot=interaction.client,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                product_name=self.product_name,
                price=vm.products[self.product_name]["price"],
                item_content=item
            )
            
            # 購入者にDMでアイテムを送信
            try:
                await interaction.user.send(
                    f"🎉 **ご購入ありがとうございます！**\n"
                    f"商品: `{self.product_name}`\n"
                    f"--- アイテム内容 ---\n"
                    f"```{item}```"
                )
                await interaction.followup.send("✅ DMに商品を送りました。", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("❌ DMを送信できませんでした。DM設定を確認してください。", ephemeral=True)

        except FileNotFoundError:
            await interaction.followup.send("❌ この自販機は削除されたか、見つかりません。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 購入中にエラーが発生しました: {str(e)}", ephemeral=True)


class ProductSelect(discord.ui.Select):
    def __init__(self, vm_id: str, options: list):
        super().__init__(
            custom_id=f"vm_select_{vm_id}",
            placeholder="商品を選択してください...",
            options=options
        )
        self.vm_id = vm_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_product_name = self.values[0]
        
        try:
            vm_data = VendingMachine.load_vm(self.vm_id)
            vm = VendingMachine.from_dict(vm_data)

            # Viewを再構築
            new_view = VendingMachineView(self.vm_id)
            new_view.children = [c for c in new_view.children if not isinstance(c, PurchaseButton)]
            
            # 新しいボタンを作成してViewに追加
            purchase_button = PurchaseButton(
                vm_id=self.vm_id,
                product_name=selected_product_name,
                custom_id=f"purchase_{self.vm_id}_{selected_product_name}"
            )
            new_view.add_item(purchase_button)

            # Embedを更新
            embed = vm.create_embed(selected_product_name)

            # メッセージを更新
            await interaction.edit_original_response(embed=embed, view=new_view)
            
        except FileNotFoundError:
            await interaction.followup.send("❌ この自販機は削除されたか、見つかりません。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 選択中にエラーが発生しました: {str(e)}", ephemeral=True)


class VendingMachineView(discord.ui.View):
    def __init__(self, vm_id: str):
        super().__init__(timeout=None)
        self.vm_id = vm_id
        self.add_item(ProductSelect(vm_id, options=[]))
        # 初期の購入ボタンは無効で追加しておく
        self.add_item(PurchaseButton(vm_id, "default", f"purchase_{vm_id}_default_disabled"))


# --- Cog: 自販機の表示 (/vmpost) ---
class CreateVendingMachineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._registered_views = set() 

    @app_commands.command(
        name="vmpost", # 🔥 修正コマンド名
        description="指定した自動販売機をチャンネルに表示します。"
    )
    @app_commands.describe(vm_name="表示したい自動販売機の名前")
    async def vmpost_command(self, interaction: discord.Interaction, vm_name: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        
        try:
            vm_id = VendingMachine.get_vm_id_by_name(interaction.guild_id, vm_name)
            if not vm_id:
                return await interaction.followup.send(f"❌ 自販機`{vm_name}`が見つかりません。", ephemeral=True)
                
            vm_data = VendingMachine.load_vm(vm_id)
            vm = VendingMachine.from_dict(vm_data)

            view = VendingMachineView(vm_id)
            embed = vm.create_embed()

            # オプションの構築
            options = []
            for product_name, product_info in vm.products.items():
                stock_count = "∞" if product_info.get("infinite_stock", False) else len(product_info.get("stock", []))
                stock_display = f"{stock_count}個"
                price = product_info["price"]
                label = f"{product_name} - ¥{price}"
                description = f"{price}円｜在庫: {stock_display} / {product_info['description'][:50]}"
                
                options.append(discord.SelectOption(
                    label=label,
                    value=product_name,
                    description=description
                ))
            
            # セレクトコンポーネントにオプションを設定
            select_component = next((c for c in view.children if isinstance(c, ProductSelect)), None)
            if select_component:
                select_component.options = options
            
            # 永続Viewの登録
            if vm_id not in self._registered_views:
                self.bot.add_view(view)
                self._registered_views.add(vm_id)
            
            await interaction.channel.send(embed=embed, view=view)
            await interaction.followup.send(f"✅ 自販機`{vm_name}`をこのチャンネルに表示しました。", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)


# --- Cog: 商品の追加 (/vm_add_product) ---
class AddProductToVMCog(commands.Cog):
    # ...
    @app_commands.command(
        name="vm_add_product", # 🔥 修正コマンド名
        description="自販機に新しい商品スロットを追加します。"
    )
    @app_commands.describe(
        vm_name="自販機の名前",
        product_name="商品名",
        price="価格",
        description="商品の説明"
    )
    async def vm_add_product_command(self, interaction: discord.Interaction, vm_name: str, product_name: str, price: int, description: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        
        vm_id = VendingMachine.get_vm_id_by_name(interaction.guild_id, vm_name)
        if not vm_id:
            return await interaction.followup.send(f"❌ 自販機`{vm_name}`が見つかりません。", ephemeral=True)

        try:
            vm_data = VendingMachine.load_vm(vm_id)
            # 商品データを直接更新
            vm_data["products"][product_name] = {
                "price": price,
                "description": description,
                "stock": [],
                "infinite_stock": False,
                "infinite_item": ""
            }
            
            # VendingMachineクラスのsave_vmを再利用する
            vm = VendingMachine.from_dict(vm_data)
            vm.save_vm()
                
            await interaction.followup.send(f"✅ 自販機`{vm_name}`に商品`{product_name}` (¥{price}) を追加しました。", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CreateVendingMachineCog(bot))
    await bot.add_cog(AddProductToVMCog(bot))
    # (永続Viewの再ロードロジックもここに追加されます)import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import asyncio
from typing import Optional, List, Dict, Any
# vm_management.pyからコアクラスと通知関数をインポート
from .vm_management import VendingMachine
from .purchase_notifications import send_purchase_notification 

# --- UI Components (購入ロジックを含む) ---

class PurchaseButton(discord.ui.Button):
    def __init__(self, vm_id: str, product_name: str, custom_id: str):
        super().__init__(label=f"『{product_name}』を購入", style=discord.ButtonStyle.green, custom_id=custom_id)
        self.vm_id = vm_id
        self.product_name = product_name
    
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        
        # Paypay連携ロジックなどが入る場合もありますが、ここでは直接購入処理を実行します
        
        try:
            vm_data = VendingMachine.load_vm(self.vm_id)
            vm = VendingMachine.from_dict(vm_data)
            
            # アイテムを購入 (在庫が減る場合はvm_management側で保存される)
            item = vm.purchase_item(self.product_name)
            
            if not item:
                return await interaction.followup.send(f"❌ 商品`{self.product_name}`は現在、在庫切れです。", ephemeral=True)
            
            # 購入通知を送信
            await send_purchase_notification(
                bot=interaction.client,
                guild_id=interaction.guild_id,
                user_id=interaction.user.id,
                product_name=self.product_name,
                price=vm.products[self.product_name]["price"],
                item_content=item
            )
            
            # 購入者にDMでアイテムを送信
            try:
                await interaction.user.send(
                    f"🎉 **ご購入ありがとうございます！**\n"
                    f"自販機: `{vm.name}`\n"
                    f"商品: `{self.product_name}`\n"
                    f"--- アイテム内容 ---\n"
                    f"```{item}```"
                )
                await interaction.followup.send("✅ DMに商品を送りました。ご確認ください。", ephemeral=True)
            except discord.Forbidden:
                await interaction.followup.send("❌ DMを送信できませんでした。あなたのDM設定（サーバーメンバーからのDM）を確認してください。", ephemeral=True)

        except FileNotFoundError:
            await interaction.followup.send("❌ この自販機は削除されたか、見つかりません。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 購入中に予期せぬエラーが発生しました: {str(e)}", ephemeral=True)


class ProductSelect(discord.ui.Select):
    def __init__(self, vm_id: str, options: list):
        super().__init__(
            custom_id=f"vm_select_{vm_id}",
            placeholder="商品を選択してください...",
            options=options
        )
        self.vm_id = vm_id

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        selected_product_name = self.values[0]
        
        try:
            vm_data = VendingMachine.load_vm(self.vm_id)
            vm = VendingMachine.from_dict(vm_data)

            # Viewを再構築
            new_view = VendingMachineView(self.vm_id)
            # 既存のSelect以外のコンポーネントをクリア
            new_view.children = [c for c in new_view.children if not isinstance(c, PurchaseButton)]
            
            # 新しいボタンを作成してViewに追加
            purchase_button = PurchaseButton(
                vm_id=self.vm_id,
                product_name=selected_product_name,
                custom_id=f"purchase_{self.vm_id}_{selected_product_name}"
            )
            new_view.add_item(purchase_button)
            
            # Selectコンポーネントにオプションを再設定（選択状態を維持）
            select_component = next((c for c in new_view.children if isinstance(c, ProductSelect)), None)
            if select_component:
                 select_component.options = self.options
                 select_component.default_values = [discord.SelectOption(label=selected_product_name, value=selected_product_name)]

            # Embedを更新
            embed = vm.create_embed(selected_product_name)

            # メッセージを更新
            await interaction.edit_original_response(embed=embed, view=new_view)
            
        except FileNotFoundError:
            await interaction.followup.send("❌ この自販機は削除されたか、見つかりません。", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ 選択中にエラーが発生しました: {str(e)}", ephemeral=True)


class VendingMachineView(discord.ui.View):
    def __init__(self, vm_id: str):
        super().__init__(timeout=None)
        self.vm_id = vm_id
        # Selectは初期化時にオプションなしで追加
        self.add_item(ProductSelect(vm_id, options=[]))
        # 初期の購入ボタンは仮で追加しておく (Selectで選択されたら置き換えられる)
        self.add_item(PurchaseButton(vm_id, "商品を選択してください", f"purchase_{vm_id}_default_disabled"))


# --- Cog: 自販機の表示 (/vmpost) ---
class CreateVendingMachineCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # 永続Viewの登録管理用（gファイルに倣い、このCogで管理）
        self._registered_views: set = set() 

    @app_commands.command(
        name="vmpost", 
        description="指定した自動販売機をチャンネルに表示します（管理者専用）。"
    )
    @app_commands.describe(vm_name="表示したい自動販売機の名前")
    async def vmpost_command(self, interaction: discord.Interaction, vm_name: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        
        try:
            vm_id = VendingMachine.get_vm_id_by_name(interaction.guild_id, vm_name)
            if not vm_id:
                return await interaction.followup.send(f"❌ 自販機`{vm_name}`が見つかりません。", ephemeral=True)
                
            vm_data = VendingMachine.load_vm(vm_id)
            vm = VendingMachine.from_dict(vm_data)

            view = VendingMachineView(vm_id)
            embed = vm.create_embed()

            # オプションの構築
            options = []
            for product_name, product_info in vm.products.items():
                stock_count = "∞" if product_info.get("infinite_stock", False) else len(product_info.get("stock", []))
                stock_display = f"{stock_count}個"
                price = product_info["price"]
                label = f"{product_name} - ¥{price:,}"
                description = f"{price:,}円｜在庫: {stock_display} / {product_info['description'][:50]}"
                
                options.append(discord.SelectOption(
                    label=label,
                    value=product_name,
                    description=description
                ))
            
            # セレクトコンポーネントにオプションを設定
            select_component = next((c for c in view.children if isinstance(c, ProductSelect)), None)
            if select_component:
                select_component.options = options
            
            # 永続Viewの登録
            if vm_id not in self._registered_views:
                # Bot起動時に永続Viewのリスナーが呼ばれるため、ここでは重複登録を避けるためセットに追加する処理のみ
                # 実際にはsetupフックでボットにViewを add_view する必要があります
                pass 
            
            # 初期ボタンを無効化
            initial_button = next((c for c in view.children if isinstance(c, PurchaseButton)), None)
            if initial_button:
                initial_button.disabled = True

            await interaction.channel.send(embed=embed, view=view)
            await interaction.followup.send(f"✅ 自販機`{vm_name}`をこのチャンネルに表示しました。", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)


# --- Cog: 商品の追加 (/vm_add_product) ---
class AddProductToVMCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="vm_add_product", 
        description="自販機に新しい商品スロットを追加します（管理者専用）。"
    )
    @app_commands.describe(
        vm_name="自販機の名前",
        product_name="商品名",
        price="価格",
        description="商品の説明"
    )
    async def vm_add_product_command(self, interaction: discord.Interaction, vm_name: str, product_name: str, price: int, description: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        
        vm_id = VendingMachine.get_vm_id_by_name(interaction.guild_id, vm_name)
        if not vm_id:
            return await interaction.followup.send(f"❌ 自販機`{vm_name}`が見つかりません。", ephemeral=True)

        try:
            vm_data = VendingMachine.load_vm(vm_id)
            vm = VendingMachine.from_dict(vm_data)
            
            if product_name in vm.products:
                return await interaction.followup.send(f"❌ 商品`{product_name}`は既に存在します。在庫を追加する場合は別のコマンドを使ってください。", ephemeral=True)

            # 商品データを更新
            vm.products[product_name] = {
                "price": price,
                "description": description,
                "stock": [],
                "infinite_stock": False,
                "infinite_item": ""
            }
            vm.save_vm()
                
            await interaction.followup.send(f"✅ 自販機`{vm_name}`に商品`{product_name}` (¥{price:,}) を追加しました。", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)


# =========================================================
# 3. Setup
# =========================================================
async def setup(bot: commands.Bot):
    await bot.add_cog(CreateVendingMachineCog(bot))
    await bot.add_cog(AddProductToVMCog(bot))
    # Botの再起動時に永続Viewを再登録するロジックもここに追加します
    # (例: bot.add_view(VendingMachineView(vm_id)) のような処理)