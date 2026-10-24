# Orthographic Relief Extension 配布ガイド

## 配布ファイル

配布する本体と検証用チェックサムは次の2点です。

```text
dist/orthographic_relief-1.3.0.zip
dist/orthographic_relief-1.3.0.zip.sha256
```

Blender 5.2.3 LTSの公式Extensionビルダーで生成し、完成ZIPを公式バリデーターで検証しています。対象はBlender 5.2.0以降です。

このZIPには以下だけが含まれます。

- `blender_manifest.toml`
- `__init__.py`
- `core.py`
- `README.md`

MCPサーバー、TCPソケット、ネットワーク接続、テレメトリー、外部Python依存関係は含みません。Blender同梱のPythonとNumPyだけを使用します。

## 利用者側のインストール

1. Blender 5.2以降を起動します。
2. `Edit` → `Preferences` → `Get Extensions` を開きます。
3. 右上メニューから `Install from Disk...` を選びます。
4. `orthographic_relief-1.3.0.zip` を指定します。
5. 3D Viewでメッシュを選択し、`N` パネル → `Relief` を開きます。
6. `Base Shape` は通常 `Source Silhouette` のまま、投影方向や寸法を設定して `Generate Relief` を押します。

`Source Silhouette` は元メッシュの投影外形に沿った背面と側壁を持つ閉じたソリッドを作ります。従来の矩形プレートが必要な場合は `Rectangle` を選択します。アンダーカットなしの保証は選択した投影方向に対して適用されます。

## Rhino / STEP用のクワッド作成

1. 生成したレリーフを選択します。
2. `CAD / Rhino Quad Mesh` の `Target Quad Faces` を指定します。
3. `Create CAD Quad Copy` を押します。
4. 作られた複製をOBJで書き出します。STLはクワッドを三角形化するため使用しません。
5. RhinoでOBJを読み込み、`ToSubD` を `MeshCreases=Yes` で実行します。
6. `ToNURBS` でNURBSへ変換し、STEPを書き出します。

`Preserve Sharp Edges` は既定で有効です。壁との境界などにできる開放シームは、Rhinoでクリースとして扱うため意図的に許可しています。全フェースが四角形で、3面以上が集まる分岐エッジや孤立頂点がなければ合格です。閉じたソリッドが必要な場合だけ、この設定を無効にしてください。

## 配布ZIPの再ビルド

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_manual_extension.ps1
```

スクリプトはソース検証、ZIP生成、完成ZIP検証、SHA-256ファイル生成を順に実行します。Blenderの場所が異なる場合:

```powershell
.\scripts\build_manual_extension.ps1 -BlenderPath "C:\path\to\blender.exe"
```

## ライセンス

GPL-3.0-or-later。再配布時はZIPを改変せず、そのまま渡すのが簡単です。
