import os
from google_auth_oauthlib.flow import InstalledAppFlow

# Gmailを読み書きする権限の設定
SCOPES = ['https://www.googleapis.com/auth/gmail.modify']

def main():
    # 認証フローを開始
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', SCOPES)
    
    # ブラウザを立ち上げて認証する
    creds = flow.run_local_server(port=0)
    
    # 結果を token.json に保存
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
    print("成功です！ token.json が作成されました。")

if __name__ == '__main__':
    main()