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


g_main_args = BaseArgs(
    in_path="test/fixture/scientific_article_1.pdf",
    out_dir="test/output",
    out_file="output.md",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    g_main_args = MainArgs().parse_args()

import re
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.types.doc.base import ImageRefMode


# %%
def markdown_from_pdf(args: BaseArgs | MainArgs) -> str:
    converter = DocumentConverter()
    result = converter.convert(args.in_path)
    return re.sub(
        "\r\n",
        "\n",
        result.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED),
    )


if __name__ == "__main__":
    g_result = markdown_from_pdf(g_main_args)
    g_output_path = Path(g_main_args.out_dir)
    g_output_path.mkdir(parents=True, exist_ok=True)
    with open(g_output_path / g_main_args.out_file, "w", encoding="utf-8") as f:
        f.write(g_result)

# %%
