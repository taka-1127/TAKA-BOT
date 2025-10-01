# cogs/vm_management.py

import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import hashlib
from typing import Optional, List, Dict, Any
from io import BytesIO

# --- ファイルパス設定 ---
VM_CONFIG_DIR = "vm_config"
if not os.path.exists(VM_CONFIG_DIR):
    os.makedirs(VM_CONFIG_DIR)

# =========================================================
# 1. VendingMachine クラス (自販機のコアロジックとファイル操作)
# =========================================================
class VendingMachine:
    # VendingMachine g.pyとvm_management g.pyの両方の機能を統合し、重複を排除
    def __init__(self, name: str, vm_id: str, guild_id: int):
        self.name = name
        self.vm_id = vm_id
        self.guild_id = guild_id
        self.products: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _get_vm_file_path(vm_id: str) -> str:
        return os.path.join(VM_CONFIG_DIR, f"{vm_id}.json")

    @staticmethod
    def get_vm_id_by_name(guild_id: int, vm_name: str) -> Optional[str]:
        """ギルドIDとVM名からVM IDを検索"""
        for filename in os.listdir(VM_CONFIG_DIR):
            if filename.endswith(".json"):
                vm_id = filename.replace(".json", "")
                try:
                    data = VendingMachine.load_vm(vm_id)
                    # 文字列比較を推奨
                    if str(data.get("guild_id")) == str(guild_id) and data.get("name") == vm_name:
                        return vm_id
                except:
                    continue
        return None

    @staticmethod
    def load_vm(vm_id: str) -> Dict[str, Any]:
        """VM IDから自販機の状態を読み込み"""
        file_path = VendingMachine._get_vm_file_path(vm_id)
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"VM ID {vm_id} のファイルが見つかりません。")
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_vm(self):
        """自販機の状態をファイルに保存"""
        data = {
            "name": self.name,
            "vm_id": self.vm_id,
            "guild_id": self.guild_id,
            "products": self.products
        }
        with open(VendingMachine._get_vm_file_path(self.vm_id), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VendingMachine':
        """辞書からVendingMachineインスタンスを再構築"""
        vm = cls(data["name"], data["vm_id"], data["guild_id"])
        vm.products = data["products"]
        return vm
        
    def create_embed(self, selected_product_name: Optional[str] = None) -> discord.Embed:
        """自販機の表示用Embedを作成"""
        # (ロジックが長くなるため、簡略化してここでは基本的な表示のみ)
        embed = discord.Embed(
            title=f"🛒 {self.name} - 自動販売機",
            description="商品を選択して購入ボタンを押してください。",
            color=discord.Color.blue()
        )
        for name, info in self.products.items():
            stock_count = "∞" if info.get("infinite_stock", False) else len(info.get("stock", []))
            value_text = f"価格: **¥{info['price']}** | 在庫: **{stock_count}**個"
            embed.add_field(name=name, value=value_text, inline=False)
            
        if selected_product_name and selected_product_name in self.products:
            embed.title = f"🛒 {self.name} - {selected_product_name} 選択中"
            
        return embed
        
    def purchase_item(self, product_name: str) -> Optional[str]:
        """在庫からアイテムを取り出し、在庫を減らす"""
        if product_name not in self.products:
            return None
            
        product = self.products[product_name]
        
        if product.get("infinite_stock", False):
            return product.get("infinite_item", "無限アイテム (未設定)")
        
        if product["stock"]:
            item = product["stock"].pop(0) # 最初のアイテムを取り出す
            self.save_vm() # 在庫が減ったので保存
            return item
        
        return None # 在庫切れ

# =========================================================
# 2. Cog: 自販機の作成・削除
#    - コマンド名を /vm_create に変更
# =========================================================
class CreateVMCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="vm_create", # 🔥 修正コマンド名
        description="新しい自動販売機を作成します。"
    )
    @app_commands.describe(vm_name="自販機の名前")
    async def vm_create_command(self, interaction: discord.Interaction, vm_name: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ このコマンドは管理者のみ実行できます。", ephemeral=True)
            
        await interaction.response.defer(ephemeral=True)
        
        if VendingMachine.get_vm_id_by_name(interaction.guild_id, vm_name):
            return await interaction.followup.send(f"❌ 自販機`{vm_name}`は既に存在します。", ephemeral=True)

        # VM IDを生成
        input_str = f"{interaction.guild_id}_{vm_name}_{os.urandom(8).hex()}"
        vm_id = hashlib.sha256(input_str.encode()).hexdigest()[:16]
        
        try:
            vm = VendingMachine(vm_name, vm_id, interaction.guild_id)
            vm.save_vm()

            await interaction.followup.send(f"✅ 自販機`{vm_name}`を作成しました！ID: `{vm_id}`", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"❌ エラーが発生しました: {str(e)}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CreateVMCog(bot))
    # (削除や在庫管理などの他の管理コグもここに追加されます)