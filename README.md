# Blender Relief MCP

選択した Blender メッシュを正投影の深度画像へ変換し、Gaussian blur をかけ、投影方向にアンダーカットのないソリッドなレリーフへ再構築します。生成物には `Relief Corrective Smooth` モディファイアーも追加されます。

## Blender 5.2 LTS 手動専用版

Blender 5.2.3 LTS には、MCP・ソケット・ネットワーク機能を含まない手動操作専用Extensionを用意しています。

- 配布ZIP: [`dist/orthographic_relief-1.2.0.zip`](dist/orthographic_relief-1.2.0.zip)
- ソース: [`blender_extension/orthographic_relief`](blender_extension/orthographic_relief)
- 配布・インストール手順: [`DISTRIBUTION.md`](DISTRIBUTION.md)

Blender 5.2.3では `N` パネル → `Relief` → `Generate Relief` から操作します。MCP版は既存のBlender 3.6環境用として分離してあり、5.2.3では有効化していません。

バージョン1.2.0では、投影された元メッシュの外形に合わせて背面と側壁も切り抜く `Source Silhouette` を既定にしました。リンゴなら矩形プレートではなく、リンゴの輪郭を持つ閉じたソリッドとして出力されます。従来の箱型は `Rectangle` で選択できます。

深度解像度の上限は1024、既定値は512です。投影形状の縦横比に合わせて短辺側の頂点数を自動調整します。

## 仕組み

1. 指定メッシュの評価済み形状へ平行レイを飛ばし、最前面の深度画像を作成します。
2. 深度を 0–1 の高さ画像へ正規化し、指定ピクセル半径の Gaussian blur を適用します。
3. 画像を単一値の高さ場へ変換し、投影外形に沿った背面と側壁で閉じます。
4. 表面だけを対象に Corrective Smooth を追加します。

高さ場なので、選択した投影方向に対して凹み返しや裏側へ回り込む面は作られません。これはその方向からの成形・切削で扱いやすい形状です。

## セットアップ

動作確認済みの既定値は Blender 3.6、MCP 用 Python 3.11、ポート `127.0.0.1:9876` です。

この節はMCP版のセットアップです。Blender 5.2 LTSへ手動版だけを入れる場合は [`DISTRIBUTION.md`](DISTRIBUTION.md) を参照してください。

```powershell
# 初回だけ: 公式 uv バイナリを .tools/uv へ展開した後
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

このリポジトリにはプロジェクト単位の設定例 [`.codex/config.example.toml`](.codex/config.example.toml) があります。パスを環境に合わせて書き換え、`.codex/config.toml` として保存すると、Codex/ChatGPT Desktop から STDIO MCP サーバーを起動できます。設定を読み直すには Codex を再起動してください。

Blender の起動後、アドオンは自動でローカルブリッジを開始します。3D View の `N` パネル → `Relief MCP` でも開始状態と手動生成を確認できます。

## MCP tools

- `ping_blender`: Blender とアドオンの接続確認
- `list_mesh_objects`: 現在のメッシュ一覧とアクティブオブジェクト
- `generate_relief`: 指定メッシュからレリーフ生成

代表的な指定例:

```text
source_object="Suzanne"
projection="Z"
resolution=256
relief_height=0.25
base_thickness=0.10
base_shape="SILHOUETTE"
blur_radius=2.0
```

`base_shape="SILHOUETTE"` は元メッシュの投影外形だけを残します。従来の矩形プレートが必要な場合は `RECTANGLE` を指定します。`projection="Z"` は +Z 側から -Z へ見た投影です。カメラの向きを使う場合は `CAMERA` を指定します。画像保存先 `//relief_output` は保存済み `.blend` と同じフォルダー基準で、未保存なら Blender の相対パス解決先になります。

## テスト

```powershell
& "C:\Program Files\Blender Foundation\Blender 3.6\blender.exe" `
  --background --factory-startup --python .\tests\blender_integration.py
```
