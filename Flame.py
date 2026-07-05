import sys
import shutil
import yaml
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional

import exiftool  # PyExifTool ライブラリ
from PIL import Image, ImageDraw, ImageFont, ImageOps

@dataclass
class PhotoMetadata:
    camera: str
    lens: str
    focal_length: str
    iso: str
    f_number: str
    shutter: str
    exposure_bias: str
    exposure_mode: str
    picture_control: str

class Config:
    def __init__(self, data):
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, Config(value))
            else:
                setattr(self, key, value)

class ExifConverter:
    @staticmethod
    def to_shutter_speed(exposure_time: Any) -> str:
        try:
            val = float(exposure_time)
            if val <= 0: return "-"
            if val < 1.0:
                denom = 1.0 / val
                denom_str = f"{denom:.1f}".rstrip('0').rstrip('.') if denom < 10 else f"{int(round(denom))}"
                return f"1/{denom_str}"
            sec_str = f"{val:.1f}".rstrip('0').rstrip('.') if val % 1 != 0 else str(int(val))
            return f"{sec_str}\""
        except: return str(exposure_time)

    @staticmethod
    def to_exposure_mode(code: Any) -> str:
        return {1: "M", 2: "P", 3: "A", 4: "S", 0: "AUTO"}.get(int(code or 0), f"({code})")

    @staticmethod
    def format_name(name: Optional[str]) -> str:
        if not name or name == 'Unknown': return "Unknown"
        name_str = str(name)
        name_str = name_str.replace('_3', 'III').replace('_2', 'II').replace('_4', 'IV').replace('_5', 'V')
        replacements = {"NIKON": "Nikon", "SONY": "Sony", "CANON": "Canon", "FUJIFILM": "Fujifilm"}
        for old, new in replacements.items():
            if name_str.upper().startswith(old.upper()):
                name_str = name_str.replace(name_str[:len(old)], new)
        return name_str

class ImageProcessor:
    def __init__(self, config_path: Path):
        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)
        self.config = Config(raw_config)
        self.exiftool_path = shutil.which("exiftool.exe") or shutil.which("exiftool") or "exiftool"
        
        # ロゴファイルのパス設定
        self.logo_path = Path("nikon_logo.png")

    def _get_metadata(self, image_path: Path) -> PhotoMetadata:
        with exiftool.ExifToolHelper(executable=self.exiftool_path) as et:
            m = et.get_metadata(str(image_path))[0]
        
        bias_val = float(m.get("EXIF:ExposureCompensation", 0))
        bias_str = f"{bias_val:+.1f}" if bias_val != 0 else "0.0"

        return PhotoMetadata(
            camera=ExifConverter.format_name(m.get("EXIF:Model")),
            lens=ExifConverter.format_name(m.get("EXIF:LensModel")),
            focal_length=str(m.get("EXIF:FocalLength", "-")).replace(" mm", ""),
            iso=str(m.get("EXIF:ISO", "-")),
            f_number=str(m.get("EXIF:FNumber", "-")),
            shutter=ExifConverter.to_shutter_speed(m.get("EXIF:ExposureTime")),
            exposure_bias=bias_str,
            exposure_mode=ExifConverter.to_exposure_mode(m.get("EXIF:ExposureProgram")),
            picture_control=m.get("MakerNotes:PictureControlName", "-"),
        )

    def _calculate_font_size(self, long_side: int, config_val: float) -> int:
        if self.config.fonts.size_type == "px":
            return int(config_val)
        return int(long_side * config_val)

    def _get_font(self, font_list: list, size: int):
        tried_fonts = []
        for name in font_list:
            tried_fonts.append(name)
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        print(f"\n[!] ERROR: 指定されたフォントが見つかりません。")
        print(f"    探した名前/パス: {tried_fonts}")
        sys.exit(1)

    def process_image(self, path: Path, current: int, total: int):
        # 進捗表示の作成
        progress_pct = int((current / total) * 100)
        progress_str = f"[{progress_pct:3d}%] ({current}/{total}) {path.name}"

        try:
            # 画像読み込み
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            meta = self._get_metadata(path)
            meta_dict = asdict(meta)
            
            w, h = img.size
            long_side = max(w, h)
            
            # フォント設定
            main_fs = self._calculate_font_size(long_side, self.config.fonts.main_size)
            sub_fs = self._calculate_font_size(long_side, self.config.fonts.sub_size)
            f_main = self._get_font(self.config.fonts.bold, main_fs)
            f_sub = self._get_font(self.config.fonts.regular, sub_fs)

            # 余白設定
            side_m = int(long_side * self.config.ratios.side_margin)
            bott_m = int(long_side * self.config.ratios.bottom_margin)
            canvas_w = w + side_m * 2
            canvas_h = h + side_m + bott_m
            
            # キャンバス作成
            canvas = Image.new("RGB", (canvas_w, canvas_h), self.config.colors.bg)
            canvas.paste(img, (side_m, side_m))
            draw = ImageDraw.Draw(canvas)

            # テキスト生成
            text_top = self.config.layout.top.format(**meta_dict)
            text_bottom = self.config.layout.bottom.format(**meta_dict)

            y_base = h + side_m
            y_top_line = y_base + int(bott_m * self.config.layout.top_padding_ratio)
            y_bottom_line = y_top_line + self.config.layout.line_spacing_px

            # --- ロゴ描画処理 ---
            text_top_x = 0
            if self.logo_path.exists() and "Nikon" in meta.camera:
                try:
                    logo = Image.open(self.logo_path).convert("RGBA")
                    logo_h = int(main_fs * 1.2)
                    logo_w = int(logo.width * (logo_h / logo.height))
                    logo = logo.resize((logo_w, logo_h), Image.Resampling.LANCZOS)
                    
                    tw_top = draw.textbbox((0, 0), text_top, font=f_main)[2]
                    spacing = int(main_fs * 0.5)
                    total_content_w = logo_w + spacing + tw_top
                    
                    start_x = (canvas_w - total_content_w) // 2
                    logo_y = y_top_line + (main_fs - logo_h) // 2
                    
                    canvas.paste(logo, (start_x, logo_y), logo)
                    text_top_x = start_x + logo_w + spacing
                except Exception as logo_err:
                    text_top_x = (canvas_w - draw.textbbox((0, 0), text_top, font=f_main)[2]) // 2
            else:
                text_top_x = (canvas_w - draw.textbbox((0, 0), text_top, font=f_main)[2]) // 2

            # --- テキスト描画 ---
            draw.text((text_top_x, y_top_line), text_top, fill=self.config.colors.main, font=f_main)
            tw_bottom = draw.textbbox((0, 0), text_bottom, font=f_sub)[2]
            draw.text(((canvas_w - tw_bottom) // 2, y_bottom_line), text_bottom, fill=self.config.colors.sub, font=f_sub)

            # 保存
            out_dir = path.parent / self.config.output.dir_name
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / f"{self.config.output.prefix}{path.stem}.jpg"
            canvas.save(out_path, "JPEG", quality=self.config.output.quality, subsampling=0)
            
            # 成功時の表示
            print(progress_str)

        except Exception as e:
            print(f"Error: {path.name} - {e}")

    def run(self, target: Path):
        if target.is_file():
            files = [target]
        else:
            files = list(target.iterdir())
            
        valid_extensions = {'.jpg', '.jpeg', '.png', '.nef', '.arw', '.dng'}
        valid_files = [f for f in files if f.suffix.lower() in valid_extensions]
        
        if not valid_files:
            print("No valid image files found.")
            return

        total_files = len(valid_files)
        # enumerateを使って現在の番号(i)を取得
        for i, f in enumerate(valid_files, 1):
            self.process_image(f, i, total_files)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python main.py <image_path_or_dir> [config_path]")
        sys.exit(1)

    input_path = Path(sys.argv[1]).resolve()
    conf_path = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else Path("config.yaml").resolve()

    if not conf_path.exists():
        print(f"Config file not found: {conf_path}")
        sys.exit(1)

    processor = ImageProcessor(conf_path)
    processor.run(input_path)