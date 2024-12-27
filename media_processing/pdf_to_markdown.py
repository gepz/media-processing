# %%
import sys
from dataclasses import dataclass

from tap import Tap


@dataclass(frozen=True)
class BaseArgs:
    in_path: str
    out_dir: str
    out_file: str


class MainArgs(Tap):
    in_path: str  # Path to input file
    out_dir: str  # Directory for output files
    out_file: str = "output.md"  # Name of output file


main_args = BaseArgs(
    in_path="test/fixture/scientific_article_1.pdf",
    out_dir="test/output",
    out_file="output.md",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    main_args = MainArgs().parse_args()

import re
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.types.doc.base import ImageRefMode


# %%
def convert_pdf_to_markdown(args: BaseArgs | MainArgs):
    output_path = Path(args.out_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    converter = DocumentConverter()
    result = converter.convert(args.in_path)
    full_text = re.sub(
        "\r\n",
        "\n",
        result.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED),
    )

    with open(output_path / args.out_file, "w", encoding="utf-8") as f:
        f.write(full_text)


if __name__ == "__main__":
    convert_pdf_to_markdown(main_args)

# %%
