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
        # 実行ファイルのパスを確認
        self.exiftool_path = shutil.which("exiftool.exe") or shutil.which("exiftool") or "exiftool"

    def _get_metadata(self, image_path: Path) -> PhotoMetadata:
        # PyExifToolの標準的な呼び出し方
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
        """フォントを探し、見つからなければエラーを出す"""
        tried_fonts = []
        for name in font_list:
            tried_fonts.append(name)
            try:
                # フォントの読み込みを試行
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        
        # すべての候補で見つからなかった場合
        print(f"\n[!] ERROR: 指定されたフォントが見つかりません。")
        print(f"    探した名前/パス: {tried_fonts}")
        print(f"    Windowsの場合、'C:/Windows/Fonts/arial.ttf' のようにフルパスで書くと確実です。")
        
        # 続行せず停止させる場合
        sys.exit(1)

    def process_image(self, path: Path):
        try:
            img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
            meta = self._get_metadata(path)
            meta_dict = asdict(meta)
            
            w, h = img.size
            long_side = max(w, h)
            
            main_fs = self._calculate_font_size(long_side, self.config.fonts.main_size)
            sub_fs = self._calculate_font_size(long_side, self.config.fonts.sub_size)
            f_main = self._get_font(self.config.fonts.bold, main_fs)
            f_sub = self._get_font(self.config.fonts.regular, sub_fs)

            side_m = int(long_side * self.config.ratios.side_margin)
            bott_m = int(long_side * self.config.ratios.bottom_margin)
            canvas_w = w + side_m * 2
            canvas_h = h + side_m + bott_m
            
            canvas = Image.new("RGB", (canvas_w, canvas_h), self.config.colors.bg)
            canvas.paste(img, (side_m, side_m))
            draw = ImageDraw.Draw(canvas)

            text_top = self.config.layout.top.format(**meta_dict)
            text_bottom = self.config.layout.bottom.format(**meta_dict)

            y_base = h + side_m
            y_top_line = y_base + int(bott_m * self.config.layout.top_padding_ratio)
            y_bottom_line = y_top_line + self.config.layout.line_spacing_px

            for text, font, color, y in [
                (text_top, f_main, self.config.colors.main, y_top_line),
                (text_bottom, f_sub, self.config.colors.sub, y_bottom_line)
            ]:
                tw = draw.textbbox((0, 0), text, font=font)[2]
                draw.text(((canvas_w - tw) // 2, y), text, fill=color, font=font)

            out_dir = path.parent / self.config.output.dir_name
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / f"{self.config.output.prefix}{path.stem}.jpg"
            canvas.save(out_path, "JPEG", quality=self.config.output.quality, subsampling=0)
            print(f"Success: {path.name}")

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

        for f in valid_files:
            self.process_image(f)

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
    
    print("\nProcessing completed.")
    input("Press Enter to exit...")