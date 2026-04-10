import json
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog

from vision_structure_jd import structure_jd_images


def main() -> None:
    try:
        root = tk.Tk()
        root.withdraw()

        selected_files = filedialog.askopenfilenames(
            title="Select PNG files",
            filetypes=[("PNG files", "*.png"), ("All files", "*.*")],
        )
        root.destroy()

        if not selected_files:
            print("No files selected.")
            return

        image_paths = [Path(file_path) for file_path in selected_files]

        # Validate file types
        for image_path in image_paths:
            if image_path.suffix.lower() != ".png":
                raise ValueError(f"PNG 파일만 지원합니다: {image_path}")

        print("선택된 이미지:")
        for idx, image_path in enumerate(image_paths, start=1):
            print(f"{idx}. {image_path.name}")

        confirm = input("\n선택된 이미지 순서가 맞으면 y, 아니면 n 입력: ").strip().lower()
        if confirm != "y":
            print("작업을 종료합니다.")
            return

        print("\nGemini Vision으로 이미지를 분석 중...")
        structured = structure_jd_images([str(path) for path in image_paths])

        output_dir = Path("output")
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"jd_{timestamp}.json"

        with output_path.open("w", encoding="utf-8") as f:
            json.dump(structured, f, ensure_ascii=False, indent=2)

        print(f"\n✓ Saved structured JD JSON to: {output_path}")
        print(f"  회사: {structured['company']}")
        print(f"  직급: {structured['role']}")
    except Exception as error:
        print(f"[ERROR] {error}")


if __name__ == "__main__":
    main()
