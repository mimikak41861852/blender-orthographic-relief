# Orthographic Relief Extension 配布ガイド

## 配布ファイル

配布するファイルは次の1点です。

```text
dist/orthographic_relief-1.1.0.zip
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
4. `orthographic_relief-1.1.0.zip` を指定します。
5. 3D Viewでメッシュを選択し、`N` パネル → `Relief` を開きます。
6. 投影方向や寸法を設定して `Generate Relief` を押します。

アンダーカットなしの保証は選択した投影方向に対して適用されます。

## 配布ZIPの再ビルド

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_manual_extension.ps1
```

スクリプトはソース検証、ZIP生成、完成ZIP検証を順に実行します。Blenderの場所が異なる場合:

```powershell
.\scripts\build_manual_extension.ps1 -BlenderPath "C:\path\to\blender.exe"
```

## ライセンス

GPL-3.0-or-later。再配布時はZIPを改変せず、そのまま渡すのが簡単です。
