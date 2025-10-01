import discord
from discord.ext import commands
from discord import app_commands # ★ discord.py 2.0+ のスラッシュコマンド用
import requests
import random
import string
import secrets
import asyncio
import json
import os
import time
from bs4 import BeautifulSoup
from pathlib import Path
from typing import Optional # ★ 任意の引数（Optional）のためにインポート

# アカウント情報保存用ディレクトリの準備
os.makedirs("userdata", exist_ok=True)

class Level5IDCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def safe_username(self, name):
        """ユーザー名をファイル名として安全な形式に変換する"""
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)

    def get_user_folder(self, user: discord.User):
        """ユーザーごとのアカウント保存フォルダのパスを取得・作成する"""
        uname = self.safe_username(user.name)
        folder = os.path.join("userdata", uname)
        os.makedirs(folder, exist_ok=True)
        return folder

    def get_account_file(self, user: discord.User):
        """ユーザーのアカウント情報ファイルパスを取得する"""
        return os.path.join(self.get_user_folder(user), "accounts.json")

    def load_accounts(self, user: discord.User):
        """ユーザーのアカウント情報をJSONファイルから読み込む"""
        fpath = self.get_account_file(user)
        if os.path.exists(fpath):
            with open(fpath, encoding="utf-8") as f:
                return json.load(f)
        return []

    def save_accounts(self, user: discord.User, accounts):
        """ユーザーのアカウント情報をJSONファイルに保存する"""
        fpath = self.get_account_file(user)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2, ensure_ascii=False)

    def add_account(self, user: discord.User, email, password, mailtm_pass):
        """新しいアカウント情報をユーザーのファイルに追加する"""
        accounts = self.load_accounts(user)
        accounts.append({"email": email, "password": password, "mailtm_pass": mailtm_pass})
        self.save_accounts(user, accounts)

    def random_address(self):
        """ランダムなメールアドレスのユーザー部分を生成する"""
        return ''.join(random.choices(string.ascii_lowercase, k=10))

    def create_mailtm_account(self):
        """mail.tmで一時メールアカウントを作成する"""
        domain_resp = requests.get("https://api.mail.tm/domains")
        domain_resp.raise_for_status()
        domain_data = domain_resp.json()
        domain = domain_data['hydra:member'][0]['domain']
        address = f"{self.random_address()}@{domain}"
        # mail.tmのパスワードはランダム生成のまま
        password = ''.join(random.choices(string.ascii_letters + string.digits, k=10)) 
        res = requests.post("https://api.mail.tm/accounts", json={"address": address, "password": password})
        if res.status_code != 201:
            raise Exception(f"mail.tmアカウント作成失敗: {res.text}")
        res = requests.post("https://api.mail.tm/token", json={"address": address, "password": password})
        if res.status_code != 200:
            raise Exception(f"mail.tmトークン取得失敗: {res.text}")
        token = res.json()["token"]
        return {"address": address, "password": password, "token": token}

    def get_latest_mailtm_url(self, token, timeout=90):
        """mail.tmの受信箱から最新のメールの認証URLを探す"""
        headers = {"Authorization": f"Bearer {token}"}
        import re
        for _ in range(max(1, timeout // 3)):
            res = requests.get("https://api.mail.tm/messages", headers=headers)
            messages = res.json().get('hydra:member', [])
            for msg in messages:
                if "レベルファイブ" in msg.get("subject", "") or "LEVEL5" in msg.get("subject", ""):
                    msg_id = msg["id"]
                    msg_res = requests.get(f"https://api.mail.tm/messages/{msg_id}", headers=headers)
                    msg_full = msg_res.json()
                    # HTMLとTextの両方から検索
                    body = (msg_full.get("text") or msg_full.get("html") or "")
                    # 認証URLのパターンにマッチするものを探す
                    urls = re.findall(r"https://auth\.level5-id\.com/user_registration/verify/[a-zA-Z0-9_\-]+", body)
                    if urls:
                        return urls[0]
            time.sleep(3)
        return None

    def generate_password(self, length=10):
        """ランダムなパスワードを生成する"""
        alphabet = string.ascii_letters + string.digits
        return ''.join(secrets.choice(alphabet) for _ in range(length))

    def level5_send_registration_mail(self, email):
        """LEVEL5 IDの登録確認メールを送信する"""
        session = requests.Session()
        reg_page = session.get("https://auth.level5-id.com/user_registration?locale=ja")
        soup = BeautifulSoup(reg_page.text, "html.parser")
        token_input = soup.find("input", {"name": "authenticity_token"})
        if not token_input:
            return False, "認証ページ取得失敗"
        csrf_token = token_input["value"]
        # country_idを日本(287)に固定
        data = {"utf8": "✓", "authenticity_token": csrf_token, "form[country_id]": "287", "form[email]": email, "form[mail_received]": "true"}
        resp = session.post("https://auth.level5-id.com/user_registration?locale=ja", data=data)
        if "確認メールを送信" in resp.text or "確認メール送信完了" in resp.text:
            return True, ""
        soup = BeautifulSoup(resp.text, "html.parser")
        error_div = soup.find("div", class_="error")
        if error_div:
            return False, error_div.text.strip()
        return False, "登録リクエスト失敗"

    def extract_level5_email_from_html(self, html):
        """HTMLからLEVEL5 IDのメールアドレスを抽出する"""
        soup = BeautifulSoup(html, "html.parser")
        email_input = soup.find("input", {"id": "form_email"})
        if email_input and email_input.get("value"):
            return email_input["value"]
        sent_txt = soup.find("p", class_="sec-border02 sentTxt")
        if sent_txt:
            return sent_txt.text.strip()
        return None

    # ★ パスワード引数を追加
    def level5_verify_and_set_password(self, verify_url, fallback_email=None, user_password: Optional[str] = None):
        """認証URLからパスワードを設定する"""
        session = requests.Session()
        page = session.get(verify_url)
        soup = BeautifulSoup(page.text, "html.parser")
        token_input = soup.find("input", {"name": "authenticity_token"})
        if not token_input:
            return False, fallback_email or "取得不可", None, "認証ページ取得エラー"
        csrf_token = token_input["value"]
        email = self.extract_level5_email_from_html(page.text) or fallback_email or "取得不可"
        
        # ★ パスワードをユーザー指定のもの、またはランダムなものにする
        password = user_password if user_password else self.generate_password()
        
        data = {
            "utf8": "✓",
            "authenticity_token": csrf_token,
            "form[password]": password,
            "form[password_confirmation]": password
        }
        form = soup.find("form")
        if not form or not form.get("action"):
            return False, email, None, "パスワード入力フォーム取得失敗"
        post_url = "https://auth.level5-id.com" + form["action"]
        resp = session.post(post_url, data=data)
        if "登録完了" in resp.text:
            return True, email, password, ""
        soup = BeautifulSoup(resp.text, "html.parser")
        error_div = soup.find("div", class_="error")
        if error_div:
            return False, email, None, error_div.text.strip()
        return False, email, None, "パスワード登録失敗"

    def level5_login(self, session, email, password):
        """LEVEL5 IDにログインし、セッションを返す"""
        login_url = "https://auth.level5-id.com/login"
        login_page = session.get(login_url)
        soup = BeautifulSoup(login_page.text, "html.parser")
        csrf_token = soup.find("input", {"name": "authenticity_token"})["value"]
        
        data = {
            "utf8": "✓",
            "authenticity_token": csrf_token,
            "form[email]": email,
            "form[password]": password,
            "form[remember_me]": "1",
            "commit": "ログイン"
        }
        
        res = session.post(login_url, data=data)
        if "マイページ" in res.text:
            return True
        return False

    def change_password_process(self, email, old_password, new_password):
        """パスワード変更のウェブ操作を自動化"""
        session = requests.Session()
        
        if not self.level5_login(session, email, old_password):
            return False, "ログインに失敗しました。メールアドレスまたは現在のパスワードが間違っています。"
        
        change_url = "https://auth.level5-id.com/user_settings/edit?locale=ja"
        change_page = session.get(change_url)
        soup = BeautifulSoup(change_page.text, "html.parser")
        csrf_token = soup.find("input", {"name": "authenticity_token"})["value"]
        
        data = {
            "utf8": "✓",
            "authenticity_token": csrf_token,
            "form[password]": new_password,
            "form[password_confirmation]": new_password,
            "form[current_password]": old_password,
        }
        
        res = session.post(change_url, data=data)
        
        if "パスワードが更新されました。" in res.text:
            return True, "パスワードが正常に変更されました。"
        else:
            return False, "パスワードの変更に失敗しました。現在のパスワードが正しくない可能性があります。"

    def change_email_process(self, old_email, old_password, new_email):
        """メールアドレス変更のウェブ操作を自動化"""
        session = requests.Session()
        
        if not self.level5_login(session, old_email, old_password):
            return False, "ログインに失敗しました。メールアドレスまたは現在のパスワードが間違っています。"
        
        change_url = "https://auth.level5-id.com/user_settings/edit?locale=ja"
        change_page = session.get(change_url)
        soup = BeautifulSoup(change_page.text, "html.parser")
        csrf_token = soup.find("input", {"name": "authenticity_token"})["value"]
        
        data = {
            "utf8": "✓",
            "authenticity_token": csrf_token,
            "form[email]": new_email,
            "form[current_password]": old_password,
        }
        
        res = session.post(change_url, data=data)
        
        if "新しいメールアドレスに確認メールを送信しました" in res.text:
            return True, "メールアドレス変更のリクエストを送信しました。新しいメールアドレス宛に届いた確認メールから手続きを完了させてください。"
        else:
            return False, "メールアドレスの変更に失敗しました。現在のパスワードが正しくない可能性があります。"

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"お、BOTが正常に起動したゾ botName ▶{self.bot.user}")
        # ★ commands.Botにtree属性がある場合、app_commandsの同期を実行
        try:
            if hasattr(self.bot, 'tree') and self.bot.tree:
                await self.bot.tree.sync()
                print("スラッシュコマンドをグローバルに同期しました。(app_commands)")
            elif hasattr(self.bot, 'sync_commands'):
                 await self.bot.sync_commands()
                 print("スラッシュコマンドを同期しました。(commands.Bot)")
        except Exception as e:
            print(f"スラッシュコマンドの同期中にエラーが発生: {e}")


    # ★ コマンド名を level5-create に変更 (level5-auto -> level5-create)
    # ★ app_commands.command を使用
    @app_commands.command(
        name="level5-create",
        description="完全自動でLEVEL5 IDを生成します。パスワードは任意で指定可能です。"
    )
    # ★ パスワード引数を追加し、app_commands.describe で説明を追加
    @app_commands.describe(
        count="作成するアカウント数 (1～1000)",
        password="設定したい任意のパスワード (任意、全て同じパスになります)"
    )
    async def l5_create_command(self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 1000] = 1, password: Optional[str] = None):
        
        # interaction.response.defer() で「BOTが考え中」を表示
        await interaction.response.defer(ephemeral=True)
        
        if not 1 <= count <= 1000:
            await interaction.followup.send("作成するアカウント数は1から1000の範囲で指定してください。", ephemeral=True)
            return

        success = 0
        fails = []
        
        pass_info = f"指定されたパスワード（`{password}`）を全てのアカウントに設定します。" if password else "パスワードはランダムに生成されます。"

        try:
            await interaction.followup.send(f"**LEVEL5 ID 生成開始**\nアカウント数: `{count}`件\n{pass_info}", ephemeral=True)
            
            for idx in range(1, count + 1):
                try:
                    # ステータスを逐次更新
                    await interaction.followup.send(f"**{idx}/{count} 件目:** アドレスを生成中…", ephemeral=True)
                    
                    mtm = await asyncio.to_thread(self.create_mailtm_account)
                    ok, err = await asyncio.to_thread(self.level5_send_registration_mail, mtm['address'])
                    
                    if not ok:
                        fails.append(f"{idx}: 送信失敗 {err}")
                        await asyncio.sleep(1)
                        continue
                        
                    await interaction.followup.send(f"**{idx}/{count} 件目:** 認証メール待機中…", ephemeral=True)
                    verify_url = await asyncio.to_thread(self.get_latest_mailtm_url, mtm['token'], 90)
                    
                    if not verify_url:
                        fails.append(f"{idx}: 認証メール未着 (90秒タイムアウト)")
                        await asyncio.sleep(1)
                        continue
                        
                    # ★ ユーザー指定のパスワードを渡す
                    ok, email, set_password, err = await asyncio.to_thread(
                        self.level5_verify_and_set_password, 
                        verify_url, 
                        mtm['address'], 
                        password # ★ ユーザー指定パスワード
                    )
                    
                    if not ok:
                        fails.append(f"{idx}: 認証失敗 {err or 'エラー'}")
                        await asyncio.sleep(1)
                        continue
                        
                    self.add_account(interaction.user, email, set_password, mtm["password"])
                    
                    # 成功した場合、DMで詳細を送信
                    emb = discord.Embed(title="✅ LEVEL5 ID 新規発行完了", description=f"**{idx}/{count}** 件目", color=0x5a4fff)
                    emb.add_field(name="メールアドレス", value=email, inline=False)
                    emb.add_field(name="パスワード", value=set_password, inline=True)
                    emb.add_field(name="mail.tmログインパス", value=mtm["password"], inline=True)
                    emb.set_footer(text="※この情報を大切に保存してください")
                    
                    await interaction.user.send(embed=emb)
                    
                    success += 1
                    
                    await asyncio.sleep(2) # レートリミット回避のため

                except Exception as e:
                    fails.append(f"{idx}: 例外 {type(e).__name__}: {e}")
                    await asyncio.sleep(1)
                    
            # 最終結果の報告
            final_message = f"**LEVEL5 ID 生成処理完了** ({success} / {count} 件成功)"
            if success:
                final_message += "\n✅ **成功:** 詳細をDMで送信しました。"
            if fails:
                txt = "❌ **失敗内訳（一部）**：\n" + "\n".join(fails[:10])
                if len(fails) > 10:
                    txt += f"\n…ほか {len(fails)-10} 件"
                final_message += f"\n\n{txt}"
                
            await interaction.followup.send(final_message, ephemeral=True)

        except Exception as e:
            await interaction.followup.send(f"全体エラーが発生しました: {type(e).__name__}: {e}", ephemeral=True)


    # ★ app_commands.command に置き換え (level5-show)
    @app_commands.command(
        name="level5-show",
        description="自分のLEVEL5アカウント情報を確認"
    )
    async def l5_show_accounts(self, interaction: discord.Interaction):
        # interaction.response.defer() を使用
        await interaction.response.defer(ephemeral=True)

        # interaction.user を使用
        accounts = self.load_accounts(interaction.user)
        if not accounts:
            await interaction.followup.send("アカウント情報がありません。", ephemeral=True)
            return
        
        # 応答には interaction.followup.send() を使用
        if len(accounts) <= 5:
            emb = discord.Embed(title="LEVEL5アカウント情報一覧", color=0x5a4fff)
            for idx, acc in enumerate(accounts, 1):
                emb.add_field(name=f"**{idx}. メールアドレス**", value=acc["email"], inline=False)
                emb.add_field(name="パスワード", value=acc["password"], inline=True)
                emb.add_field(name="mail.tmログインパス", value=acc["mailtm_pass"], inline=True)
            await interaction.followup.send(embed=emb, ephemeral=True)
        else:
            text = "LEVEL5アカウント情報一覧\n"
            for idx, acc in enumerate(accounts, 1):
                text += f"\n**{idx}. メールアドレス:** {acc['email']}\nパスワード: {acc['password']}\nmail.tmログインパス: {acc['mailtm_pass']}\n"
            await interaction.followup.send(text, ephemeral=True)


    # ★ app_commands.command に置き換え (level5-pass-change)
    @app_commands.command(
        name="level5-pass-change",
        description="LEVEL5 IDのパスワードを変更します。"
    )
    # ★ 日本語の引数名を英語に置き換え、@app_commands.describe で分かりやすい説明を付ける
    @app_commands.describe(
        email="変更したいアカウントのメールアドレス",
        current_password="現在のパスワード",
        new_password="新しく設定するパスワード"
    )
    async def change_password(
        self,
        interaction: discord.Interaction,
        email: str,
        current_password: str,
        new_password: str
    ):
        await interaction.response.defer(ephemeral=True)
        success, message = await asyncio.to_thread(
            self.change_password_process, 
            email, 
            current_password, 
            new_password
        )
        await interaction.followup.send(message, ephemeral=True)

    # ★ app_commands.command に置き換え (level5-email-change)
    @app_commands.command(
        name="level5-email-change",
        description="LEVEL5 IDのメールアドレスを変更します。"
    )
    # ★ 日本語の引数名を英語に置き換え、@app_commands.describe で分かりやすい説明を付ける
    @app_commands.describe(
        old_email="変更元のアカウントのメールアドレス",
        current_password="現在のパスワード",
        new_email="新しく設定するメールアドレス"
    )
    async def change_email(
        self,
        interaction: discord.Interaction,
        old_email: str,
        current_password: str,
        new_email: str
    ):
        await interaction.response.defer(ephemeral=True)
        success, message = await asyncio.to_thread(
            self.change_email_process,
            old_email,
            current_password,
            new_email
        )
        await interaction.followup.send(message, ephemeral=True)

# Cogのセットアップ関数は変更なし
async def setup(bot: commands.Bot):
    await bot.add_cog(Level5IDCog(bot))