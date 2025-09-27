import discord
from discord.ext import commands
from discord import app_commands # 追加
import os
import json
import hashlib
from typing import Optional

# --- VendingMachine クラス (VendingMachine.pyと同一だが、ここでは自己完結させる) ---
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
        # ... (購入ロジックは管理コマンドでは不要なので省略)
        pass

# --- VMCogBase (vm_management.py用) ---
class VMCogBase(commands.Cog):
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
        # ファイル名 (ハッシュ) のリスト
        return [f.replace('.json', '') for f in os.listdir(dir_path) if f.endswith('.json')]
    
    def _get_all_vm_names(self, guild_id):
        # 全てのVMの名前を取得
        names = []
        dir_path = os.path.join("vending_machines", str(guild_id))
        if not os.path.exists(dir_path):
            return []
            
        for filename in os.listdir(dir_path):
            if filename.endswith(".json"):
                file_path = os.path.join(dir_path, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                        names.append(data['name'])
                    except:
                        continue
        return names


# --- ConfirmDeleteVMView, Buttons (コールバックは変更なし) ---
class ConfirmDeleteVMView(discord.ui.View):
    def __init__(self, file_path, vm_name):
        super().__init__(timeout=30)
        self.file_path = file_path
        self.vm_name = vm_name
        
        self.add_item(ConfirmDeleteVMButton(self))
        self.add_item(CancelDeleteVMButton(self))

class ConfirmDeleteVMButton(discord.ui.Button):
    def __init__(self, parent):
        super().__init__(label="削除する", style=discord.ButtonStyle.danger, emoji="🗑️")
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        try:
            os.remove(self.parent.file_path)
            await interaction.response.send_message(
                f"✅ 自販機`{self.parent.vm_name}`を削除しました。",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)

class CancelDeleteVMButton(discord.ui.Button):
    def __init__(self, parent):
        super().__init__(label="キャンセル", style=discord.ButtonStyle.secondary, emoji="❌")
        self.parent = parent

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("削除をキャンセルしました。", ephemeral=True)


# --- VMMangementCog (変更) ---
class VMMangementCog(VMCogBase, commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @app_commands.command(name="vm-delete", description="自動販売機を完全に削除します。") # 変更
    @app_commands.describe(vm_name="削除する自動販売機の名前")
    async def delete_vm(self, interaction: discord.Interaction, vm_name: str): # 変更: ctx -> interaction
        if interaction.guild is None:
            return await interaction.response.send_message("このコマンドはサーバーでのみ実行可能です。", ephemeral=True)
            
        file_path = self._get_vm_filepath(interaction.guild_id, vm_name)

        if not os.path.exists(file_path):
            return await interaction.response.send_message(f"❌ 自動販売機`{vm_name}`は見つかりませんでした。", ephemeral=True) # 変更

        view = ConfirmDeleteVMView(file_path, vm_name)
        
        await interaction.response.send_message( # 変更
            f"⚠️ **最終確認**: 本当に自動販売機`{vm_name}`を削除しますか？\nこの操作は元に戻せません。", 
            view=view, 
            ephemeral=True
        )

    @app_commands.command(name="vm-list", description="このサーバーにある全ての自動販売機のリストを表示します。") # 変更
    async def list_vms(self, interaction: discord.Interaction): # 変更: ctx -> interaction
        if interaction.guild is None:
            return await interaction.response.send_message("このコマンドはサーバーでのみ実行可能です。", ephemeral=True)
            
        vm_names = self._get_all_vm_names(interaction.guild_id)
        
        if not vm_names:
            embed = discord.Embed(
                title="自動販売機一覧",
                description="現在、自動販売機は作成されていません。\n`/vm-create`で作成できます。",
                color=discord.Color.orange()
            )
            return await interaction.response.send_message(embed=embed, ephemeral=True) # 変更

        vm_list_text = "\n".join([f"• {name}" for name in vm_names])
        embed = discord.Embed(
            title="✅ 自動販売機一覧",
            description=vm_list_text,
            color=discord.Color.blue()
        )
        
        await interaction.response.send_message(embed=embed, ephemeral=True) # 変更

    # --- vm-add-product ---
    @app_commands.command(name="vm-add-product", description="自動販売機に新しい商品を追加します。") # 変更
    @app_commands.describe(
        vm_name="商品を追加する自動販売機の名前",
        product_name="追加する商品の名前",
        price="商品の販売価格 (例: 500)",
        description="商品の簡単な説明 (任意)",
        infinite_stock="在庫を無限にするか (True/False)"
    )
    async def add_product(self, interaction: discord.Interaction, vm_name: str, product_name: str, price: int, description: str = "", infinite_stock: bool = False): # 変更
        if interaction.guild is None:
            return await interaction.response.send_message("このコマンドはサーバーでのみ実行可能です。", ephemeral=True)

        vm = self._load_vm(interaction.guild_id, vm_name)
        if not vm:
            return await interaction.response.send_message(f"❌ 自動販売機`{vm_name}`は見つかりませんでした。", ephemeral=True)

        if product_name in vm.products:
            return await interaction.response.send_message(f"❌ 商品`{product_name}`は既に存在します。", ephemeral=True)

        try:
            vm.add_product(product_name, price, description, infinite_stock)
            self._save_vm(interaction.guild_id, vm)
            await interaction.response.send_message(f"✅ 自販機`{vm_name}`に商品`{product_name}`を追加しました。\n価格: {price}円, 在庫: {'無限' if infinite_stock else '0個'}", ephemeral=True) # 変更
        except Exception as e:
            await interaction.response.send_message(f"❌ エラーが発生しました: {str(e)}", ephemeral=True) # 変更

    # --- vm-remove-product ---
    @app_commands.command(name="vm-remove-product", description="自動販売機から商品を削除します。") # 変更
    @app_commands.describe(
        vm_name="商品を削除する自動販売機の名前",
        product_name="削除する商品の名前"
    )
    async def remove_product(self, interaction: discord.Interaction, vm_name: str, product_name: str): # 変更
        if interaction.guild is None:
            return await interaction.response.send_message("このコマンドはサーバーでのみ実行可能です。", ephemeral=True)

        vm = self._load_vm(interaction.guild_id, vm_name)
        if not vm:
            return await interaction.response.send_message(f"❌ 自動販売機`{vm_name}`は見つかりませんでした。", ephemeral=True)

        if product_name not in vm.products:
            return await interaction.response.send_message(f"❌ 商品`{product_name}`は存在しません。", ephemeral=True)

        try:
            vm.remove_product(product_name)
            self._save_vm(interaction.guild_id, vm)
            await interaction.response.send_message(f"✅ 自販機`{vm_name}`から商品`{product_name}`を削除しました。", ephemeral=True) # 変更
        except Exception as e:
            await interaction.response.send_message(f"❌ エラーが発生しました: {str(e)}", ephemeral=True) # 変更

    # --- vm-add-stock ---
    @app_commands.command(name="vm-add-stock", description="商品の在庫を追加します。（アイテムを改行区切りで入力）") # 変更
    @app_commands.describe(
        vm_name="在庫を追加する自動販売機の名前",
        product_name="在庫を追加する商品の名前",
        items="在庫として追加するアイテム（改行区切り）"
    )
    async def add_stock(self, interaction: discord.Interaction, vm_name: str, product_name: str, items: str): # 変更
        if interaction.guild is None:
            return await interaction.response.send_message("このコマンドはサーバーでのみ実行可能です。", ephemeral=True)

        vm = self._load_vm(interaction.guild_id, vm_name)
        if not vm:
            return await interaction.response.send_message(f"❌ 自動販売機`{vm_name}`は見つかりませんでした。", ephemeral=True)

        if product_name not in vm.products:
            return await interaction.response.send_message(f"❌ 商品`{product_name}`は存在しません。", ephemeral=True)
            
        if vm.products[product_name].get("infinite_stock", False):
            return await interaction.response.send_message(f"❌ 商品`{product_name}`は無限在庫設定のため、在庫追加はできません。`/vm-set-infinite-item`で無限アイテムを設定してください。", ephemeral=True)

        try:
            item_list = [i.strip() for i in items.split('\n') if i.strip()]
            if not item_list:
                 return await interaction.response.send_message("❌ 追加するアイテムが入力されていません。", ephemeral=True)
                 
            vm.add_stock(product_name, item_list)
            self._save_vm(interaction.guild_id, vm)
            await interaction.response.send_message(f"✅ 自販機`{vm_name}`の商品`{product_name}`に在庫を**{len(item_list)}**個追加しました。\n現在の在庫: {vm.get_stock_count(product_name)}個", ephemeral=True) # 変更
        except Exception as e:
            await interaction.response.send_message(f"❌ エラーが発生しました: {str(e)}", ephemeral=True) # 変更

    # --- vm-show-stock ---
    @app_commands.command(name="vm-show-stock", description="商品の現在の在庫を表示します。") # 変更
    @app_commands.describe(
        vm_name="在庫を表示する自動販売機の名前",
        product_name="在庫を表示する商品の名前"
    )
    async def show_stock(self, interaction: discord.Interaction, vm_name: str, product_name: str): # 変更
        if interaction.guild is None:
            return await interaction.response.send_message("このコマンドはサーバーでのみ実行可能です。", ephemeral=True)

        vm = self._load_vm(interaction.guild_id, vm_name)
        if not vm:
            return await interaction.response.send_message(f"❌ 自動販売機`{vm_name}`は見つかりませんでした。", ephemeral=True)

        if product_name not in vm.products:
            return await interaction.response.send_message(f"❌ 商品`{product_name}`は存在しません。", ephemeral=True)
            
        product = vm.products[product_name]
        stock_count = vm.get_stock_count(product_name)
        
        embed = discord.Embed(
            title=f"📦 {vm_name} - {product_name} の在庫状況",
            color=discord.Color.gold()
        )
        embed.add_field(name="価格", value=f"**{product['price']}**円", inline=True)
        embed.add_field(name="在庫数", value=f"**{stock_count}**個", inline=True)
        embed.add_field(name="無限在庫設定", value="✅ ON" if product.get("infinite_stock", False) else "❌ OFF", inline=True)
        
        if product.get("infinite_stock", False):
            embed.add_field(name="提供アイテム (無限)", value=f"```{product.get('infinite_item', '未設定')}```", inline=False)
        else:
            stock_preview = "\n".join([f"`{i[:20]}...`" if len(i) > 20 else f"`{i}`" for i in product["stock"][:5]])
            if stock_count > 5:
                stock_preview += f"\n...他 {stock_count - 5}個"
            embed.add_field(name="在庫アイテム (先頭5件)", value=stock_preview if stock_preview else "なし", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True) # 変更

async def setup(bot): # 変更: async setup
    # VMMangementCog と AddProductToVMCog は同一クラス VMMangementCog に統合されていると仮定
    # (元のコードのsetupに AddProductToVMCog(bot) が含まれていたが、クラス定義がないためここでは VMMangementCog のみ登録)
    await bot.add_cog(VMMangementCog(bot)) # 変更