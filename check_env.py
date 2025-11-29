import os
from dotenv import load_dotenv

# 今のフォルダにあるファイルを全部表示する
print("📂 今のフォルダにあるファイル一覧:")
files = os.listdir('.')
print(files)

print("-" * 20)

# .envがあるかチェック
if ".env" in files:
    print("✅ .env ファイルは見つかりました！")
    
    # 中身を読み込んでみる
    load_dotenv()
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.getenv("LINE_USER_ID")
    
    if token:
        print(f"🆗 トークン読み込み成功: {token[:10]}...") # 最初の10文字だけ表示
    else:
        print("❌ トークンが読み込めません（中身の書き方が間違っています）")
        
    if user_id:
        print(f"🆗 ID読み込み成功: {user_id}")
    else:
        print("❌ User IDが読み込めません")

elif ".env.txt" in files:
    print("😱 ファイル名が惜しい！ '.env.txt' になっています。名前の変更で '.txt' を消してください。")

else:
    print("❌ '.env' が見つかりません。保存場所が違うか、名前が間違っています。")