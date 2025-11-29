import streamlit as st
import pandas as pd
import time
import os
import base64
import requests
from datetime import datetime, timedelta
from email.utils import parseaddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from groq import Groq
from dotenv import load_dotenv

# ==========================================
# ⚙️ 設定・初期化
# ==========================================

load_dotenv()

# 関数：環境変数またはSecretsから鍵を取得
def get_secret(key):
    value = os.getenv(key)
    if value:
        return value
    if key in st.secrets:
        return st.secrets[key]
    return None

GROQ_API_KEY = get_secret("GROQ_API_KEY")
LINE_CHANNEL_ACCESS_TOKEN = get_secret("LINE_CHANNEL_ACCESS_TOKEN")
LINE_USER_ID = get_secret("LINE_USER_ID")

# token.jsonの復元（クラウド対応）
if not os.path.exists("token.json"):
    if "GOOGLE_TOKEN_JSON" in st.secrets:
        with open("token.json", "w") as f:
            f.write(st.secrets["GOOGLE_TOKEN_JSON"])

# ページ設定
st.set_page_config(page_title="Auto-Reply Pro", page_icon="📨", layout="wide")

# 📱 スマホ対応CSS（タイトルサイズ調整など）
st.markdown("""
    <style>
        /* スマホ画面（幅が狭いとき）の設定 */
        @media (max-width: 640px) {
            /* タイトル文字を小さくして改行を防ぐ */
            h1 {
                font-size: 1.8rem !important;
            }
            /* 全体の余白を調整 */
            .block-container {
                padding-top: 2rem !important;
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }
            /* ボタンを押しやすく */
            .stButton button {
                min-height: 45px;
            }
        }
    </style>
""", unsafe_allow_html=True)

# セッション初期化
if "reply_count" not in st.session_state:
    st.session_state.reply_count = 0
if "log_data" not in st.session_state:
    st.session_state.log_data = []
if "next_run_time" not in st.session_state:
    st.session_state.next_run_time = None

# ==========================================
# 🛠️ 関数定義
# ==========================================

def init_groq():
    if not GROQ_API_KEY:
        return None
    try:
        return Groq(api_key=GROQ_API_KEY)
    except:
        return None

def summarize(text, client):
    if not client or not text:
        return "（要約不可）"
    try:
        resp = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "メールの要約を日本語で3行で作成してください。"},
                {"role": "user", "content": text}
            ],
            temperature=0.5,
            max_tokens=300
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"AIエラー: {e}"

def line_push_message(text):
    if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_USER_ID:
        st.error("⚠️ LINE設定エラー")
        return False

    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }
    data = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": text}]
    }
    resp = requests.post(url, headers=headers, json=data)
    
    if resp.status_code != 200:
        st.error(f"LINE送信エラー({resp.status_code})")
        return False
    return True

def create_reply(to_addr_full, subject, thread_id, message_id_reply, reply_subject, reply_body, pdf_bytes, pdf_filename):
    _, clean_addr = parseaddr(to_addr_full)
    msg = MIMEMultipart()
    msg["to"] = clean_addr
    
    if reply_subject:
        msg["subject"] = reply_subject
    else:
        msg["subject"] = subject if subject.startswith("Re:") else f"Re: {subject}"
        
    msg["In-Reply-To"] = message_id_reply
    msg["References"] = message_id_reply

    msg.attach(MIMEText(reply_body, "plain"))

    if pdf_bytes and pdf_filename:
        pdf = MIMEApplication(pdf_bytes, _subtype="pdf")
        pdf.add_header("Content-Disposition", "attachment", filename=pdf_filename)
        msg.attach(pdf)

    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode(), "threadId": thread_id}

def get_body(payload):
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain":
                if "data" in part["body"]:
                    body += base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="ignore")
            elif "parts" in part:
                body += get_body(part)
    else:
        if "body" in payload and "data" in payload["body"]:
            body += base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="ignore")
    return body

def process_emails(max_emails, enable_filter, reply_subject, reply_body, pdf_bytes, pdf_filename):
    if not os.path.exists("token.json"):
        st.error("token.jsonなし")
        return

    creds = Credentials.from_authorized_user_file("token.json")
    service = build("gmail", "v1", credentials=creds)
    groq_client = init_groq()

    try:
        results = service.users().messages().list(userId="me", q="is:unread", maxResults=max_emails).execute()
        messages = results.get("messages", [])
    except Exception as e:
        st.error(f"Gmailエラー: {e}")
        return

    if not messages:
        return

    for m in messages:
        msg_data = service.users().messages().get(userId="me", id=m["id"]).execute()
        payload = msg_data["payload"]
        headers = payload["headers"]

        subject = next((h["value"] for h in headers if h["name"] == "Subject"), "No Subject")
        from_addr = next((h["value"] for h in headers if h["name"] == "From"), "Unknown")
        message_id = next((h["value"] for h in headers if h["name"] == "Message-ID"), "")

        status = "Processed"
        ignore_keywords = ["no-reply", "noreply", "mailer-daemon", "google", "amazon", "rakuten", "unknown"]
        is_spam = any(k in from_addr.lower() for k in ignore_keywords)

        if enable_filter and is_spam:
            status = "Skipped"
            service.users().messages().modify(userId='me', id=m["id"], body={"removeLabelIds": ["UNREAD"]}).execute()
        else:
            body = get_body(payload)
            summary = summarize(body, groq_client)
            
            line_push_message(f"📩 受信: {subject}\n\n{summary}")
            
            try:
                reply = create_reply(from_addr, subject, m["threadId"], message_id, reply_subject, reply_body, pdf_bytes, pdf_filename)
                service.users().messages().send(userId="me", body=reply).execute()
                status = "Replied"
                st.session_state.reply_count += 1
            except Exception as e:
                status = f"Error: {str(e)}"

            service.users().messages().modify(userId='me', id=m["id"], body={"removeLabelIds": ["UNREAD"]}).execute()

        log_entry = {
            "Time": datetime.now().strftime("%H:%M"),
            "From": from_addr,
            "Subject": subject,
            "Status": status
        }
        st.session_state.log_data.insert(0, log_entry)

# ==========================================
# 🖥️ フロントエンド
# ==========================================

st.title("📨 自動メール返信ツール")

# --- サイドバー ---
with st.sidebar:
    st.header("🛠️ 設定メニュー")
    is_active = st.toggle("システム稼働スイッチ", value=False)
    
    st.divider()
    st.subheader("基本設定")
    check_interval = st.number_input("チェック間隔（分）", 1, 60, 30)
    max_emails = st.number_input("一度に処理する件数", 1, 20, 10)
    enable_filter = st.checkbox("自動送信メールを除外", value=False)
    if not enable_filter:
        st.warning("⚠️ 全メールに返信します")

    st.divider()
    if st.button("📱 LINE通知テスト"):
        if line_push_message("🔔 テスト通知成功"):
            st.success("成功")
        else:
            st.error("失敗")

    st.divider()
    if st.button("🗑️ ログリセット"):
        st.session_state.reply_count = 0
        st.session_state.log_data = []
        st.rerun()

# --- メインエリア ---

# ステータス表示
col1, col2 = st.columns(2)
with col1:
    if is_active:
        st.success(f"🟢 **稼働中** ({check_interval}分毎)")
    else:
        st.error("🔴 **停止中**")
with col2:
    st.metric("📅 本日の返信", f"{st.session_state.reply_count} 件")

st.divider()

# 📂 タブ切り替え（広々と使う構成を維持）
tab1, tab2 = st.tabs(["📊 処理ログ", "⚙️ 返信 & PDF設定"])

# --- タブ1: ログ ---
with tab1:
    if st.session_state.log_data:
        df = pd.DataFrame(st.session_state.log_data)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("履歴なし")

# --- タブ2: 返信設定 & PDFアップロード ---
with tab2:
    st.subheader("📝 返信内容")
    reply_subject = st.text_input("件名 (空欄=Re:)", value="")
    reply_body = st.text_area("本文", value="お問い合わせありがとうございます。\n資料をお送りいたします。\nご確認のほどよろしくお願いいたします。", height=200)
    
    st.divider()
    
    st.subheader("📎 PDF添付")
    enable_pdf = st.toggle("PDFファイルを添付する", value=True)
    
    pdf_bytes = None
    pdf_filename = None

    if enable_pdf:
        uploaded_file = st.file_uploader("PDFファイルをドラッグ＆ドロップ", type="pdf")
        if uploaded_file is not None:
            st.success(f"セット完了: {uploaded_file.name}")
            pdf_bytes = uploaded_file.getvalue()
            pdf_filename = uploaded_file.name
    else:
        st.info("添付なしで送信します")

# --- 自動実行ループ ---
if is_active:
    now = datetime.now()
    if st.session_state.next_run_time is None or now >= st.session_state.next_run_time:
        with st.spinner(f'チェック中...'):
            process_emails(max_emails, enable_filter, reply_subject, reply_body, pdf_bytes, pdf_filename)
        
        st.session_state.next_run_time = now + timedelta(minutes=check_interval)
        st.rerun()
    else:
        remaining = st.session_state.next_run_time - now
        secs_left = int(remaining.total_seconds())
        st.caption(f"⏳ 次回チェックまで: {secs_left} 秒")
        time.sleep(1)
        st.rerun()
else:
    st.session_state.next_run_time = None



