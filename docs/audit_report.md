# 監査レポート — ai_webinar_agent_requirements_and_spec v1.0 → v1.1

| 項目 | 内容 |
|---|---|
| 監査日 | 2026-08-08 |
| 対象 | requirements.md v1.0 / specification.md v1.0（ChatGPT生成） |
| 結論 | **修正必須**。技術選定・フェーズ構成・スコープの3点で発注者意図と乖離 |

## 1. 重大な乖離（Must Fix）

### A-1. フェーズ構成の逆転
- **v1.0の問題**: ウェビナー動画生成・TTS・AI登壇をPhase 2以降に後送りし、MVPを「既存ウェビナーへの後付けRAG Q&A + Intent Scoring + CRM Agent」と定義していた。
- **発注者意図**: ハッカソンの中核は**ウェビナー動画の自動生成**（台本→スライド→ナレーション→動画）。
- **修正**: Phase 1（ハッカソンMVP）を動画生成パイプラインに再定義。RAG Q&Aはデモ効果と実装コストのバランスからサブ機能として残置。Intent Scoringは簡易版（構造化JSON抽出＋ローカル集計）に縮小。

### A-2. OrcaRouter必須要件の欠落
- **v1.0の問題**: 「LLM Provider抽象化を自前実装し1社から開始」（OD-03、NFR-06、AI-06）。
- **発注者意図**: ハッカソン規定によりOrcaRouter経由でのAI組み込みが**必須**。
- **修正**: 全LLM呼び出しをOrcaRouter（OpenAI互換API、`https://api.orcarouter.ai/v1`）経由に統一。これに伴い:
  - 自前のProvider抽象化レイヤーは**実装不要**（要件から削除）
  - PIIマスキング・プロンプトインジェクション対策・不適切表現フィルタ等のガードレール要件の一部をOrcaRouterの統合ガードレール機能へ委譲
  - コスト監視（token/cost per event）はOrcaRouterの可観測性機能を利用
  - embeddingsのOrcaRouter経由可否は要確認（未決事項OD-03に変更）

### A-3. 動画生成の技術選定が未定義
- **v1.0の問題**: 動画生成に関する技術要件が存在しない（Phase 2の抽象記述のみ）。
- **修正**: **Remotionを主レンダラーとして採用**。理由:
  - 成果物として確定的にMP4を出力できる（daida-aiの成果物は音声埋め込みPPTX＋自動再生設定であり、動画ファイルではない）
  - React componentでスライドを宣言的に記述でき、音声とフレーム単位で同期可能
  - daida-aiはClaude Code対話型プラグインであり、プロダクトのバックエンドサービスとして組み込む形態に不向き
- **daida-aiからの設計流用**（実装コスト削減、発注者意図どおり）:
  - パイプライン段階構成: アウトライン→スライド→トークスクリプト→音声合成→合成物埋め込み→再生設定
  - スライドテンプレート3種の思想（tech / casual / formal）
  - 発音辞書（pronunciation_dict.tsv）によるTTS読み誤り補正
  - 話法スタイルプリセット（casual / keynote / formal / humorous）
  - ステップ単位の再実行（「Step 4からやり直す」）の設計

### A-4. TTS選定が未定義
- **修正**: 言語ルーティング型TTS Adapterを新設。
  - **英語**: ElevenLabs ボイスクローン（クラウドAPI）
  - **日本語**: Irodori-TTS（ローカル、参照音声10〜30秒によるゼロショットクローン、絵文字による感情制御対応）
- **設計上の制約を要件化**:
  - Irodori-TTSはローカル動作のためGPU環境が必要 → デモは事前バッチ生成を基本とする
  - 漢字の読み誤りが発生しうるため、文単位分割生成＋発音辞書＋リテイク運用を仕様化
  - 参照音声・クローン音声は**本人同意を得た音声のみ**使用（両サービスの利用規約遵守を受入条件に追加）

## 2. スコープ過剰（ハッカソンに不適合、削減済み）

| v1.0の要件 | v1.1での扱い |
|---|---|
| マルチテナントSaaS、テナント分離 | 削除（シングルテナント）。将来拡張として付記 |
| HubSpot / Salesforce CRM同期、冪等キー、DLQ | Phase 3へ後送り。MVPはCSV/JSONエクスポートで代替 |
| 5ロールRBAC | 削除（管理者/視聴者の2区分に簡素化） |
| 月間99.9% SLO、日次バックアップ、データ保持ジョブ | 削除（ハッカソンでは非現実的）。デモ成立条件に置換 |
| モデレーターコンソール（SCR-05） | 簡易承認UI（生成台本・回答のプレビューと修正）に縮小 |
| Webhook署名検証、replay attack対策等 | 外部ウェビナー基盤連携自体をPhase 2へ後送りしたため削除 |
| OIDC/SSO、Secrets Manager、監査ログ100% | 環境変数管理＋最小限の生成ログに簡素化 |

## 3. 軽微な修正

- 改訂履歴の作成者「OpenAI / Draft」→ 実チーム名に更新（プレースホルダ化）
- 「既存ウェビナー基盤(Zoom/EventHub等)連携」前提の記述を、MVPでは自己完結型（アップロード資料→動画生成→自社プレイヤーで配信）に変更
- KPIを事業KPI中心からハッカソン審査観点（デモ完遂・生成品質・OrcaRouter活用度）に再構成

## 4. 残した v1.0 の良い部分

- Grounded by default（KB根拠のある回答のみ自動投稿）の設計原則
- 構造化出力スキーマ（answer_text / confidence / citations / answerability）
- Golden Dataset による回答品質評価の考え方（件数は50件→20件に縮小）
- プロンプトインジェクション対策の基本方針（OrcaRouterガードレールとの二層防御として残置）

## 5. 未決事項（実装前に決めること）

| ID | 論点 | 推奨 |
|---|---|---|
| OD-01 | 動画の想定尺・解像度 | 5分 / 1080p / 30fps から開始 |
| OD-02 | Remotionのレンダリング環境 | ローカル `@remotion/renderer` で開始、必要ならLambda |
| OD-03 | embeddingsをOrcaRouter経由にできるか | 対応モデルを確認。不可なら埋め込みのみ直接プロバイダー |
| OD-04 | Irodori-TTS実行環境 | チーム内GPU機 or クラウドGPUでバッチ生成 |
| OD-05 | ElevenLabsのクローン方式 | Instant Voice Cloneで開始（提出音声の同意確認込み） |
| OD-06 | Q&A機能をデモに含めるか | 動画生成完成後の残り時間で判断 |


---

## 追記: v1.1 → v1.2（2026-08-08）

開発期間が約1週間であることを踏まえ、発注者判断によりTTSを**ElevenLabs（Eleven v3）一本化**に変更した。

- 削除: Irodori-TTS、TTS言語ルーティング、GPUワーカー（tts-worker）、GPU関連リスク・未決事項
- 変更: 日英とも同一クローンVoiceで生成する構成に統一（「本人の声のまま2言語」がデモの訴求点になる）
- 維持: 発音辞書＋文単位分割・リテイクの仕組み（適用先をElevenLabsの日本語読み誤り対策に変更）、TTS Adapter interface（将来Irodori-TTS等を追加可能）、音声クローン同意フラグとAI生成表記
- 追加: ElevenLabs単一依存リスクと、edge-tts等へのデモ保険フォールバックフラグ


## 追記: v1.2 → v1.3（2026-08-08）

発注者要望により、ElevenLabsの**APIキー持ち込み（BYOK）**を仕様化した。

- 追加: FR-006a（キー登録・検証・削除）、FR-006b（Voice一覧・選択）、Integrations API 4本、integrationsエンティティ（アプリ層暗号化キー保存、マスク表示）
- キー解決順序: 運用者の持ち込みキー → システムフォールバックキー（構成フラグで有効時のみ、デモ用）
- 検証フロー: subscription照会（有効性・tier・残クレジット）＋Voicesスコープ確認。Freeプランには商用不可警告
- セキュリティ: 平文保存・ログ出力・フロント返却の禁止、制限付きキー（スコープ・クレジット上限・有効期限）発行の推奨案内
- ElevenLabs API側の対応確認済み: xi-api-keyヘッダー認証、キー単位のスコープ制限・クレジット上限・IPアローリスト、GET /v1/user/subscriptionによるプラン/残量照会が利用可能


## 追記: v1.3 → v1.4（2026-08-08）

発注者要望により、**OrcaRouterもBYOK化**し、外部プロバイダーのキー管理をintegrations共通機構に統一した。

- Integrations APIを `POST/DELETE /api/v1/integrations/{provider}`（orcarouter / elevenlabs）に共通化。GETは全プロバイダー一括の接続状態を返す
- integrationsエンティティのproviderをenum化し、プロバイダー固有情報（ELのtier/残量等）はmeta_jsonへ
- キー解決順序を全プロバイダー共通ルール化: ①運用者の登録キー → ②システムフォールバックキー（`ALLOW_SYSTEM_LLM_KEY` / `ALLOW_SYSTEM_TTS_KEY` で個別制御）
- OrcaRouterキーの登録時検証はモデル一覧取得等の軽量呼び出しで実施。残高照会APIの有無は未決事項OD-09として確認対象に
- コスト可観測性の位置づけを変更: BYOKにより各運用者が自分のOrcaRouterダッシュボードで消費を確認する構成に
- リスク追加: 持ち込みOrcaRouterキーの残高不足（登録時検証＋失敗時案内＋デモ用フォールバックで緩和）


## 追記: v1.4 → v1.5（2026-08-08）

プロダクト名を **Koebinar（コエビナー）** に決定し、全文書のプロダクト名を差し替えた（旧称: AI Webinar Agent）。タグライン「あなたの声が、あなたの代わりに登壇する。」を追加。簡易確認の結果、主要ドメイン（.com/.ai/.app/.dev/.jp）のDNS応答なし、GitHub org / npm / PyPI の `koebinar` は空き。正式利用前にWHOISおよび商標データベース（J-PlatPat等）での確認を推奨。
