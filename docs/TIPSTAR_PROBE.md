# TIPSTAR公開ページ取得診断（実験）

TIPSTAR第17条(21)の無断複製・蓄積、第17条(25)の過度なアクセス制限を確認してください。第25号に配慮しても第21号が解除されるわけではありません。

この機能は本番の自動収集ではありません。取得先のページ構造と公開情報の識別方法を調べるための**手動実行・単発診断**です。自動ログイン・ログインCookie・非公開API・ページの大量列挙・DB保存は行いません。

## SSHで実行

```sh
cd /home/dsktnk/www/keirin
/usr/local/bin/python tools/probe_tipstar.py --url 'https://tipstar.com/user/keirin/2026-10-16_12_05/race_predictors'
```

1回につき1ページだけ。次の取得は最低120秒経過後。結果はHTMLサイズ、回収率ラベルの検出数、予想詳細リンクの数などの**構造情報のみ**を標準出力に表示。HTMLや氏名は保存しません。HTTP 403/429 や想定外のリダイレクトは続行しません。cron登録はまだしないでください。

HTMLがJavaScript実行後に描画される場合、HTMLパーサでは表示データを読めないことがあります。その際はサイト側の許可された提供方法の確認が必要です。

検証用のローカルHTMLでは `--fixture /path/to/sample.html` を指定できます。ネットワークアクセスは行いません。

本当に長期分析へ進む際は、予想詳細のUUIDが**投稿ごとのID**であり、予想師本人の固定IDとは限らない点に注意し、別途安定した人物識別子を確認してください。

## 2026-10-21 さくらSSHの検証結果

単発診断で HTTP のHTML 7093バイト取得、画面文字16文字、回収率検出0件、詳細リンク0件、`client_rendered_possible: true` を確認。**これは実際のTIPSTARの予想師が0人という意味ではありません。** HTMLに初期データがなく、JavaScript描画が考えられるため、静的HTMLパーサでの観測値抽出は保留にします。

### Chrome上でブラウザ表示を確認

1. 本人のブラウザで同じ予想師一覧URLを開く。
2. Chromeの開発者ツール → **Console** で次を実行する。

```js
const body = document.body.innerText;
console.log({
  title: document.title,
  visibleCharacters: body.length,
  roiLabels: (body.match(/回収率/g) || []).length,
  predictorLinks: [...document.querySelectorAll('a[href]')]
      .filter(a => a.href.includes('/race_predictors/')).length
});
```

表示文字数が増えていればブラウザのJavaScriptがDOMを更新しています。次に **Network → Fetch/XHR → Reload** で取得元が画面外部から来ているかを確認します。JSONがない場合はページ埋め込みデータやHTML/GraphQL/WebSocketの可能性も残ります。実際のAPI形式が判明するまでは未確定です。

認証済みセッションを閲覧する場合は、**Cookie、Authorizationヘッダー、トークン、完全なHARを共有しないでください。** ステータス、Content-Type、パス（クエリパラメータは伏せる）だけで一次診断が可能です。サービス側が許可しないAPIやアクセス制限の回避は行いません。

さくらCGI上のPythonはブラウザのJavaScriptを自動実行しません。取得方式は①許可されたデータAPI、②ブラウザ環境での画面描画後の観測、のいずれかを実証して選びます。
