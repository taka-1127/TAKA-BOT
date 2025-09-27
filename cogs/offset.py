import discord
from discord.ext import commands
import zipfile, os, io, json, re, asyncio, time, datetime
from typing import Dict, List, Tuple, Optional
import lief
from subprocess import run, CalledProcessError
import shutil
from discord import app_commands # app_commandsを追加

# ==== 解析パターン（元スクリプト準拠） ====
PATTERNS: List[Tuple[str, bytes, int, int]] = [
    ("ワンパン", bytes.fromhex("69029f1a"), 0x14, 1),
    ("倍速", bytes.fromhex("0895881a"), -0x10, 2),
    ("遅延", bytes.fromhex("0018281e"), 0x0, 14),
    ("無敵", bytes.fromhex("e10740b9"), 0x0, 3),
    ("スコア", bytes.fromhex("0100158b"), 0x0, 2),
    ("ダメージ100万", bytes.fromhex("69029f1a"), -0x34, 1),
    ("スコアタ用", bytes.fromhex("69029f1a"), 0x34, 1),
    ("各泥", bytes.fromhex("29b19b9a"), 0xA4, 1),
    ("妖怪泥無効", bytes.fromhex("29b19b9a"), 0xAC, 1),
    ("リザルトスキップ", bytes.fromhex("fa079f1a"), -0x68, 7),
    ("即技", bytes.fromhex("60029f1a"), 0x10, 1),
    ("振ぷにサイズ", bytes.fromhex("48079f1a"), -0xAC, 1),
    ("ぷに1色", bytes.fromhex("49149f1a"), -0x10, 1),
    ("虫眼鏡無効", bytes.fromhex("21319b9a"), 0xA3EF8, 25),
    ("お宝演出無効", bytes.fromhex("08318a9a"), 0xd8, 6),
]

# HTML の機能名マップ（テンプレに合わせる）
NAME_TO_JS: Dict[str, str] = {
    "ワンパン": "onepan",
    "倍速": "speed",
    "遅延": "Falling",
    "無敵": "invincible",
    "スコア": "score",
    "ダメージ100万": "damage",
    "スコアタ用": "damage2",
    "各泥": "drop",
    "妖怪泥無効": "drop2",
    "リザルトスキップ": "result",
    "即技": "soku",
    "振ぷにサイズ": "punisize",
    "ぷに1色": "onecolor",
    "虫眼鏡無効": "nomagnifier",
    "お宝演出無効": "notreasure",
}

DATA_DIR = "data/offsets"
os.makedirs(DATA_DIR, exist_ok=True)

# ==== JST の翌日0:00で失効 ====
JST = datetime.timezone(datetime.timedelta(hours=9))

def _next_jst_midnight_ts(now: Optional[datetime.datetime] = None) -> int:
    if now is None:
        now = datetime.datetime.now(JST)
    else:
        # 念のためJST化
        if now.tzinfo is None:
            now = now.replace(tzinfo=JST)
        else:
            now = now.astimezone(JST)
    tomorrow = now.date() + datetime.timedelta(days=1)
    expiry_dt = datetime.datetime.combine(tomorrow, datetime.time(0, 0, 0), tzinfo=JST)
    return int(expiry_dt.timestamp())

def _state_path(guild_id: int) -> str:
    return os.path.join(DATA_DIR, f"{guild_id}.json")

def _load_state(guild_id: int) -> Dict:
    p = _state_path(guild_id)
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"offsets": {}, "updated_by": None, "version": None, "set_at": None, "expiry_at": None}

def _save_state(guild_id: int, data: Dict):
    with open(_state_path(guild_id), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _is_expired(st: Dict) -> bool:
    exp = st.get("expiry_at")
    if not exp:
        return True
    return time.time() >= float(exp)

def _ensure_valid_or_clear(guild_id: int) -> Dict:
    st = _load_state(guild_id)
    if _is_expired(st):
        st = {"offsets": {}, "updated_by": None, "version": None, "set_at": None, "expiry_at": None}
        _save_state(guild_id, st)
    return st

# ==== IPA 読み出し・スキャン ====
async def _read_ipa_binary(payload_bytes: bytes) -> Optional[bytes]:
    loop = asyncio.get_running_loop()
    def _extract() -> Optional[bytes]:
        with zipfile.ZipFile(io.BytesIO(payload_bytes)) as z:
            ywp_path = None
            for name in z.namelist():
                # ほとんどのゲームのバイナリは Payload/*.app/ExecutableName の形式
                if re.search(r"Payload/.+\.app/[^/]+$", name):
                    ywp_path = name
                    break
            if not ywp_path:
                return None
            return z.read(ywp_path)
    return await loop.run_in_executor(None, _extract)

def _scan_binary_for_offsets(binary: bytes) -> Dict[str, int]:
    offsets: Dict[str, int] = {}
    for name, pattern, offset_add, num_bytes in PATTERNS:
        match = re.search(pattern, binary)
        if match:
            # マッチしたアドレス + 指定オフセット値
            offsets[name] = match.start() + offset_add
    return offsets

async def _patch_ipa(ipa_data: bytes, offsets: Dict[str, int], p12_path: str, p12_password: str) -> Optional[bytes]:
    loop = asyncio.get_running_loop()

    def _patch() -> Optional[bytes]:
        # 1. IPAからバイナリ抽出
        try:
            with zipfile.ZipFile(io.BytesIO(ipa_data)) as z:
                ywp_path = None
                for name in z.namelist():
                    if re.search(r"Payload/.+\.app/[^/]+$", name):
                        ywp_path = name
                        break
                if not ywp_path:
                    print("Error: Executable not found in IPA.")
                    return None
                
                # 実行ファイルを一時ファイルに書き出し
                temp_bin_path = f"temp_bin_{os.getpid()}"
                with open(temp_bin_path, "wb") as f:
                    f.write(z.read(ywp_path))

                # 2. LIEFでバイナリをロードし、パッチ
                binary = lief.MachO.parse(temp_bin_path)
                if binary is None:
                    os.remove(temp_bin_path)
                    return None

                # LIEFのセグメントオフセットを取得
                text_segment = binary.get_segment("__TEXT")
                if not text_segment:
                    os.remove(temp_bin_path)
                    print("Error: __TEXT segment not found.")
                    return None
                text_segment_offset = text_segment.file_offset
                
                # パッチ処理
                for name, offset in offsets.items():
                    # LIEFでパッチするアドレスはファイルオフセット
                    file_offset = offset - text_segment_offset
                    
                    # ゼロフィル
                    for i in range(4): # 4バイト
                        binary.patch_address(offset + i, [0x00])

                # 3. 新しいバイナリを書き出す
                builder = lief.MachO.Builder(binary)
                builder.build()
                
                patched_bin_path = f"patched_bin_{os.getpid()}"
                builder.write(patched_bin_path)
                
                # 4. パッチ済みバイナリでIPAを再作成
                output_buffer = io.BytesIO()
                with zipfile.ZipFile(output_buffer, "w", zipfile.ZIP_DEFLATED) as z_out:
                    for name in z.namelist():
                        if name == ywp_path:
                            # 実行ファイルをパッチ済みに置き換え
                            z_out.write(patched_bin_path, name)
                        else:
                            # 他のファイルはそのままコピー
                            z_out.writestr(name, z.read(name))

                # 5. 再署名
                temp_ipa_path = f"temp_ipa_{os.getpid()}.ipa"
                with open(temp_ipa_path, "wb") as f:
                    f.write(output_buffer.getvalue())

                # codesign_tool が外部ツールと仮定
                # 処理結果は標準出力ではなく、ファイルに書き込まれると想定
                signed_ipa_path = f"signed_ipa_{os.getpid()}.ipa"
                
                # 例: 外部のcodesignツールを実行
                run_args = [
                    "codesign_tool", # 実際のツール名に置き換えてください
                    "-i", temp_ipa_path,
                    "-p", p12_path,
                    "-P", p12_password,
                    "-o", signed_ipa_path
                ]
                
                # 外部コマンド実行（CalledProcessErrorで失敗を検出）
                run(run_args, check=True, capture_output=True)

                with open(signed_ipa_path, "rb") as f:
                    final_ipa_data = f.read()

                # クリーンアップ
                os.remove(temp_bin_path)
                os.remove(patched_bin_path)
                os.remove(temp_ipa_path)
                os.remove(signed_ipa_path)
                
                return final_ipa_data

        except CalledProcessError as e:
            print(f"Codesign Tool Error: {e.stderr.decode()}")
            raise e # エラーを上位に伝播
        except Exception as e:
            print(f"Patching Error: {e}")
            return None
    
    return await loop.run_in_executor(None, _patch)


async def _get_data_file(ipa_data: bytes) -> Optional[Dict]:
    loop = asyncio.get_running_loop()
    def _extract_data() -> Optional[Dict]:
        with zipfile.ZipFile(io.BytesIO(ipa_data)) as z:
            data_file_path = None
            for name in z.namelist():
                # Info.plistを探す
                if re.search(r"Payload/.+\.app/Info\.plist$", name):
                    data_file_path = name
                    break
            if not data_file_path:
                return None
            
            # plistを読み込んでJSONライクな形式で返す (ここでは簡易的に)
            try:
                # plistlibなどが必要だが、ここでは簡略化し、JSONとして処理できると仮定
                # 実際にはplistのパースが必要
                return {"Version": "Unknown (Placeholder)"} # 実際のInfo.plistからバージョンを抽出する処理が必要です
            except:
                return None
    return await loop.run_in_executor(None, _extract_data)


class OffsetCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="offset-set", description="最新版のゲームデータからオフセット情報を設定・更新します。") # 変更
    async def set_offset(self, interaction: discord.Interaction, file: discord.Attachment): # 変更
        await interaction.response.defer(ephemeral=True) # 変更
        
        if interaction.guild_id is None:
            await interaction.followup.send("❌ このコマンドはサーバーでのみ実行できます。", ephemeral=True)
            return

        if file.filename.endswith((".ipa", ".zip")) is False:
            await interaction.followup.send("❌ 添付ファイルはIPAまたはZIP形式である必要があります。", ephemeral=True)
            return
        
        await interaction.followup.send("🛠 IPAファイルの解析を開始します。完了まで数分かかる場合があります…", ephemeral=True) # 変更

        ipa_data = await file.read()
        offsets_binary = await _read_ipa_binary(ipa_data)

        if offsets_binary is None:
            return await interaction.edit_original_response(content="❌ IPAの解析に失敗しました。ファイルが壊れていないか確認してください。") # 変更

        # オフセットのスキャンは同期処理なのでto_threadを使う
        offsets = await asyncio.to_thread(_scan_binary_for_offsets, offsets_binary)
        
        version_data = await _get_data_file(ipa_data)
        if version_data is None:
            version = "不明"
        else:
            version = version_data.get("Version") or "不明"

        st = _ensure_valid_or_clear(interaction.guild_id) # 変更
        st["offsets"] = offsets
        st["updated_by"] = interaction.user.id # 変更
        st["version"] = version
        st["set_at"] = int(time.time())
        st["expiry_at"] = _next_jst_midnight_ts()
        _save_state(interaction.guild_id, st) # 変更

        # 結果を表示
        offset_count = len(offsets)
        next_midnight = datetime.datetime.fromtimestamp(st["expiry_at"], JST).strftime("%Y/%m/%d 00:00:00 JST")
        
        embed = discord.Embed(
            title="✅ オフセット情報の登録が完了しました",
            description=f"検出されたオフセット数: **{offset_count}**",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now(JST)
        )
        embed.add_field(name="バージョン", value=version, inline=True)
        embed.add_field(name="更新者", value=f"<@{interaction.user.id}>", inline=True) # 変更
        embed.add_field(name="有効期限", value=f"{next_midnight}", inline=False)
        
        await interaction.edit_original_response(content="", embed=embed) # 変更


    @app_commands.command(name="offset-get", description="設定されているオフセット情報を表示します。") # 変更
    async def get_offset(self, interaction: discord.Interaction): # 変更
        if interaction.guild_id is None:
            await interaction.response.send_message("❌ このコマンドはサーバーでのみ実行できます。", ephemeral=True) # 変更
            return
            
        st = _ensure_valid_or_clear(interaction.guild_id) # 変更
        offsets: Dict[str, int] = st.get("offsets", {})

        if not offsets:
            await interaction.response.send_message("❌ オフセット情報が未設定か、有効期限が切れました。", ephemeral=True) # 変更
            return

        offset_count = len(offsets)
        updated_by_id = st.get("updated_by", "不明")
        version = st.get("version", "不明")
        set_at_ts = st.get("set_at")
        expiry_at_ts = st.get("expiry_at")
        
        set_at = datetime.datetime.fromtimestamp(set_at_ts, JST).strftime("%Y/%m/%d %H:%M:%S JST") if set_at_ts else "不明"
        expiry_at = datetime.datetime.fromtimestamp(expiry_at_ts, JST).strftime("%Y/%m/%d 00:00:00 JST") if expiry_at_ts else "不明"

        embed = discord.Embed(
            title="⚙️ オフセット情報",
            description=f"検出されたオフセット数: **{offset_count}**",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now(JST)
        )
        embed.add_field(name="バージョン", value=version, inline=False)
        embed.add_field(name="更新者", value=f"<@{updated_by_id}>" if updated_by_id != "不明" else "不明", inline=True)
        embed.add_field(name="設定日時", value=set_at, inline=True)
        embed.add_field(name="有効期限", value=expiry_at, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True) # 変更


    @app_commands.command(name="offset-patch", description="IPAファイルにオフセットを適用し、改造版を作成します。") # 変更
    async def patch_ipa(
        self, 
        interaction: discord.Interaction, # 変更
        ipa_file: discord.Attachment, 
        p12_file: discord.Attachment, 
        p12_password: str
    ):
        await interaction.response.defer(ephemeral=True) # 変更
        
        if interaction.guild_id is None:
            return await interaction.followup.send("❌ このコマンドはサーバーでのみ実行できます。", ephemeral=True) # 変更

        if not ipa_file.filename.endswith((".ipa")):
            return await interaction.followup.send("❌ `ipa_file`はIPAファイルである必要があります。", ephemeral=True) # 変更
        if not p12_file.filename.endswith((".p12")):
            return await interaction.followup.send("❌ `p12_file`はP12証明書ファイルである必要があります。", ephemeral=True) # 変更
        
        st = _ensure_valid_or_clear(interaction.guild_id) # 変更
        offsets: Dict[str, int] = st.get("offsets", {})
        if not offsets:
            return await interaction.followup.send("❌ オフセットが未設定か、有効期限が切れました。先に `/offset-set` を実行してください。", ephemeral=True) # 変更

        await interaction.followup.send("🛠 IPAのパッチを開始します。完了まで数分かかる場合があります…", ephemeral=True) # 変更

        temp_dir = f"temp_{int(time.time())}_{interaction.id}"
        os.makedirs(temp_dir, exist_ok=True)
        p12_path = os.path.join(temp_dir, "cert.p12")
        
        patched_ipa = None
        try:
            ipa_data = await ipa_file.read()
            with open(p12_path, "wb") as f:
                f.write(await p12_file.read())

            patched_ipa = await asyncio.to_thread(_patch_ipa, ipa_data, offsets, p12_path, p12_password)

            if patched_ipa is None:
                return await interaction.edit_original_response(content="❌ IPAのパッチに失敗しました。詳細なエラーはコンソールを確認してください。") # 変更

            fp = io.BytesIO(patched_ipa)
            fp.seek(0)
            
            await interaction.edit_original_response( # 変更
                content="✅ 新しいIPAファイルが作成されました。ダウンロードしてお使いください。", 
                file=discord.File(fp, filename="patched.ipa")
            )
        except CalledProcessError as e:
            await interaction.edit_original_response(content=f"❌ 署名ツールでエラーが発生しました。P12ファイルとパスワードを確認してください。\nエラー: `{e.stderr.decode('utf-8', errors='ignore')}`", embed=None) # 変更
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ パッチ処理中に予期せぬエラーが発生しました: {e}", embed=None) # 変更
        finally:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

async def setup(bot): # 変更
    await bot.add_cog(OffsetCog(bot)) # 変更