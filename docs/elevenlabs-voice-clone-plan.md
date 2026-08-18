# ElevenLabs Voice Clone 実装計画

## 目的

運用者がKoebinarの「連携設定」から離れずにElevenLabs Instant Voice Cloneを作成し、ウェビナーで利用可能なVoiceとして登録できるようにする。

## スコープ

- 対象: ElevenLabs Instant Voice Clone（IVC）
- 対象外: Professional Voice Cloneの学習ジョブ、Voice削除、サンプル音声の永続保存、ブラウザ録音
- 前提: 対象ワークスペースでElevenLabs BYOKが接続済みで、Voices Write権限がある

## 実装ステップ

1. ElevenLabs HTTP clientに`POST /v1/voices/add`のmultipart送信を追加し、既存の安全化済みエラー変換を再利用する。
2. IntegrationsServiceにIVC作成ユースケースを追加する。BYOK限定を検証し、成功したVoiceをtenantに登録して現行バージョンの同意証跡を記録する。
3. FastAPIにmultipart endpointを追加する。名前、件数、拡張子、個別/合計サイズ、同意フラグ、attestation versionをサーバー側で検証する。
4. Web API clientをFormDataに対応させ、「連携設定」のElevenLabsカードに作成フォームを追加する。成功時はVoice一覧に同意済みで追加する。
5. HTTP client、service/API、Web API client/UIの自動テストを追加し、バックエンドtest suite、Web test/lint/buildを実行する。
6. `claude -p --model fable`に仕様・実装・テスト・差分をレビューさせ、妥当な指摘を反映して再検証する。

## 受入条件

- ElevenLabs未接続では作成APIを利用できない。
- 権利確認なし、未対応形式、上限超過、空ファイルはElevenLabsへ送信されず4xxになる。
- 有効な入力は登録済みBYOKでmultipart送信され、音声バイトとAPIキーはKoebinarに永続化されない。
- 作成されたVoiceは同一tenantの`cloned` Voice、`active=true`、`consent_status=attested`、`usable=true`として即時返却される。
- 別tenantのintegration / Voice証跡に読み書きしない。
- ElevenLabs上の作成失敗時は安全化したエラーだけを表示し、Voice証跡を残さない。外部作成後のローカル保存失敗は次回同期で未同意Voiceとして回復できる。
- 作成後のVoiceがVoice一覧に表示され、既存のウェビナーVoice選択に利用できる。

## 検証チェックポイント

- バックエンド: 成功、provider 4xx、同意不足、不正ファイル、サイズ上限、tenant分離
- フロントエンド: FormData契約、送信防止、成功/失敗表示、Voice一覧更新、レスポンシブ表示
- リグレッション: 既存のBYOK登録、Voice同期、同意取消、TTS経路
