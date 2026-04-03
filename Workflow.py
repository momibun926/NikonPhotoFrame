import os
import shutil
import yaml
import subprocess
import time
from pathlib import Path
from datetime import datetime

# ライブラリのインポート確認
try:
    from send2trash import send2trash
except ImportError:
    print("Error: 'send2trash' が未インストールです。 'pip install send2trash' を実行してください。")
    exit()

def main():
    # --- 1. 設定ファイルの読み込み ---
    config_path = Path(__file__).parent / "common".yaml"
    if not config_path.exists():
        print(f"Error: 設定ファイル {config_path} が見つかりません。")
        return

    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    # パスを扱いやすいPathオブジェクトへ変換
    src_base = Path(cfg['srcBase'])
    dst_amazon = Path(cfg['dstAmazon'])
    dst_note = Path(cfg['dstNote'])
    dst_nef_base = Path(cfg['dstNefBase'])
    script_base = Path(cfg['scriptBase'])

    # 保存先フォルダの作成
    dst_amazon.mkdir(parents=True, exist_ok=True)
    dst_note.mkdir(parents=True, exist_ok=True)

    print("\033[96mファイルをスキャン中...\033[0m")
    
    # 対象ファイルの取得
    files = [f for f in src_base.rglob('*') if f.suffix.lower() in ['.jpg', '.nef']]
    total_files = len(files)

    if total_files == 0:
        print("\033[93m対象ファイル(.jpg, .nef)が見つかりませんでした。\033[0m")
        input("Enterキーを押して終了します...")
        return

    # --- 2. コピー処理 ---
    for i, file_path in enumerate(files, 1):
        percent = int((i / total_files) * 100)
        ext = file_path.suffix.upper()
        
        status = f"[{percent:3}%] ({i}/{total_files}) {file_path.name}"
        print(status, end='', flush=True)

        if ext == ".JPG":
            shutil.copy2(file_path, dst_amazon)
            shutil.copy2(file_path, dst_note)
            print(" \033[92m-> Amazon/Noteへコピー完了\033[0m")

        elif ext == ".NEF":
            # ファイルの更新日時から yyyyMM フォルダを作成
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
            yyyy_mm = mtime.strftime("%Y%m")
            target_dir = dst_nef_base / yyy_mm
            target_dir.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(file_path, target_dir)
            print(f" \033[90m-> {yyyy_mm} フォルダへコピー完了\033[0m")

    # --- 3. 外部Pythonスクリプトの起動 ---
    print(f"\n\033[96m全ファイルのコピーが完了しました。Flame.pyを起動します...\033[0m")
    
    try:
        time.sleep(1)
        # 実行
        subprocess.run(
            ["python", cfg['pyScript'], str(dst_note), cfg['flameOption']],
            cwd=script_base,
            check=True
        )
    except Exception as e:
        print(f"\033[91mエラー: スクリプトの起動に失敗しました。\n{e}\033[0m")

    # --- 4. クリーニング (ゴミ箱へ移動) ---
    print("\n\033[93mクリーニングを実行中(ファイルをゴミ箱へ移動)...\033[0m")
    
    for file_path in files:
        try:
            send2trash(str(file_path))
        except Exception as e:
            print(f"\033[91m警告: {file_path.name} の削除に失敗しました。\033[0m")

    print("\n\033[42m全行程が終了しました。元ファイルはゴミ箱へ移動されました。\033[0m")
    input("Enterキーを押して終了してください...")

if __name__ == "__main__":
    main()