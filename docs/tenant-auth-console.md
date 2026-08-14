# テナント分離・認証・運用コンソール仕様

| 項目 | 内容 |
|---|---|
| 文書バージョン | v1.3 |
| 対象 | Koebinar 運用者コンソール / API |
| 状態 | 実装契約 |

## 1. 目的

複数の組織が同じ Koebinar 環境を利用しても、資料、ウェビナー、生成ジョブ、質問分析、外部サービスの API キーを相互に参照・操作できないようにする。運用者はログイン画面から自分のワークスペースへ入り、サイドバーからウェビナーと連携設定を移動できる。

公開済みウェビナーの `/watch/{id}` は従来どおり視聴者向けの公開導線とし、運用者ログインの対象外とする。

## 2. テナントと認証

### 2.1 テナント設定

`KOEBINAR_TENANTS_JSON` にワークスペースを JSON 配列で設定する。

```json
[
  {"id":"acme","name":"Acme株式会社","access_token":"replace-with-a-long-random-token"},
  {"id":"globex","name":"Globex株式会社","access_token":"replace-with-another-long-random-token"}
]
```

- `id`: URLセーフな英小文字・数字・ハイフン。永続データの `tenant_id` になるため、運用開始後は変更しない。
- `name`: 画面表示名。
- `access_token`: 推測困難なテナント固有トークン。複数テナントで共有しない。
- 同じ `id` または `access_token` の重複、形式不正は認証設定エラーとして扱う。

`KOEBINAR_TENANTS_JSON` が空で `KOEBINAR_DEFAULT_AUTH_TOKEN` が設定済みの場合は、後方互換として `id=default`、`name=Koebinar` の単一テナントを構成する。既存データに `tenant_id` がない場合も `default` として読み込む。

### 2.2 ログインフロー

1. 運用者は `/login` でワークスペースIDとアクセストークンを入力する。
2. `POST /api/v1/auth/login` が組み合わせを検証し、テナント情報と Bearer token を返す。
3. Web UI は token とテナント情報をブラウザの `localStorage` に保存し、以後の運用者 API に `Authorization: Bearer ...` を付ける。
4. 起動時は `GET /api/v1/auth/session` で保存済み token を再検証する。401 の場合は保存情報を破棄してログイン画面へ戻す。
5. ログアウトはブラウザ内の認証情報を削除する。サーバー側セッションは保持しない。

外部プロバイダーのAPIキー登録時にOrcaRouter / ElevenLabsが返す401・403等は、Koebinarの認証失効ではない。`POST /api/v1/integrations/{provider}` はこれらを安全なdetailの422へ正規化し、Web UIはログイン情報を維持したまま連携設定画面に検証エラーを表示する。ElevenLabsの応答は構造化されたcode/messageだけを採用し、APIキーを伏せて長さを制限する。非構造化のレスポンス本文は画面・API・ログへ転送しない。

トークン全文を API レスポンス、ログ、画面のログイン後領域へ再表示しない。比較には定時間比較を使う。

## 3. テナント分離の境界

次の運用者向けデータは作成時に認証主体の `tenant_id` を付与し、一覧・取得・更新・削除時にも一致を必須とする。

- ナレッジ資料とチャンク
- ウェビナー、生成物、生成ジョブ
- 質問、回答、Intent Signal、分析エクスポート
- OrcaRouter / ElevenLabs の暗号化 API キーと Voice 参照

別テナントのIDを指定した場合は、存在の有無を漏らさないため `404 Not Found` を返す。ウェビナー作成時に指定した `document_ids` は全件が同じテナントに属することを検証し、1件でも不一致なら作成しない。非同期 Worker はジョブ対象ウェビナーの `tenant_id` を引き継ぎ、そのテナントの BYOK キーだけを使用する。

公開ウェビナー API は、公開済みかつ生成完了済みのウェビナーだけをIDで取得できる。公開レスポンスに `tenant_id`、APIキー、資料本文、運用指示を含めない。

## 4. API 契約

| Method | Path | 認証 | 用途 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | 不要 | ワークスペースIDとトークンの検証 |
| GET | `/api/v1/auth/session` | Bearer | 現在のテナント情報取得 |
| GET | `/api/v1/integrations` | Bearer | 現在のテナントの連携状態一覧 |
| POST | `/api/v1/integrations/{provider}` | Bearer | 現在のテナントへ BYOK キーを登録・検証 |
| DELETE | `/api/v1/integrations/{provider}` | Bearer | 現在のテナントの連携を解除 |
| GET | `/api/v1/integrations/elevenlabs/voices` | Bearer | 現在のテナントのキーで Voice 一覧取得 |

ログイン成功レスポンスとセッションレスポンスのテナント表現は次のとおり。

```json
{
  "tenant": {"id":"acme","name":"Acme株式会社"},
  "token":"returned-only-by-login"
}
```

`GET /auth/session` は `tenant` のみを返し、token は返さない。

## 5. Web UI

- 未認証時はログイン画面だけを表示する。
- ログイン後は左サイドバーにブランド、ワークスペース名、`ウェビナー`、`連携設定`、`ログアウト`を表示する。
- モバイル幅ではサイドバーを上部ナビゲーションへ折り返す。
- 連携設定では OrcaRouter と ElevenLabs をカード表示し、接続状態、マスク済みキー、最終検証時刻、プラン/残クレジット/警告を確認できる。
- API キー登録時はサーバー検証が成功してから接続済みにする。キー全文は送信後に入力欄から消す。
- 検証失敗時はintegrationを作成・更新せず、キー無効・期限切れ、必要権限・IP制限、レート制限、外部障害等の安全な原因別エラーを表示する。ElevenLabsは安全化済みの構造化code/messageを併記するが、非構造化本文やキー全文はAPIレスポンス・ログへ出さない。
- 各APIキー入力欄の`[i]`ヒントはクリックとキーボードで開閉でき、OrcaRouterは`GET /v1/models`と`POST /v1/chat/completions`、ElevenLabsは必須の`GET /v1/voices`（Voices Read）、任意の`GET /v1/user/subscription`（User Read / `user_read`）、生成時の`POST /v1/text-to-speech/{voice_id}`（Text to Speech）の用途を説明する。期限・IP制限・スコープ・利用上限も案内し、モバイル幅でviewport外へはみ出さない。
- ElevenLabsのUser Readがない場合もTTS + Voices Readキーの登録は成功させ、プラン・使用量を表示できない旨を警告する。
- ElevenLabs 接続後は Voice 一覧を再読込できる。Free tier の登録は利用条件への明示同意を必須とする。

## 6. 受入条件

1. 正しいワークスペースIDとトークンでログインでき、誤った組み合わせは401になる。
2. テナントAが作成した資料・ウェビナー・連携情報・分析をテナントBの一覧に表示しない。
3. テナントBがテナントAのリソースIDを直接指定しても404になり、更新や生成再実行ができない。
4. 非同期生成がテナントAの BYOK キーを使用し、他テナントのキーへフォールスルーしない。
5. ログイン後にサイドバーからウェビナー一覧と連携設定へ移動できる。
6. ログアウト後は運用者画面へアクセスできず、公開視聴ページは引き続き表示できる。
7. 外部プロバイダーのキー検証が401/403等で失敗してもKoebinarのログインセッションを削除せず、検証前のintegrationを作成・更新しない。
8. OrcaRouter / ElevenLabsの必要アクセス範囲を、両カードで同じ操作・アクセシビリティの`[i]`ヒントから確認できる。
