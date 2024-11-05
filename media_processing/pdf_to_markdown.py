# %%
import sys
from dataclasses import dataclass

from tap import Tap


@dataclass
class BaseArgs:
    input_path: str
    output_dir: str
    output_file: str


class MainArgs(Tap, BaseArgs):
    input_path: str  # Path to input file
    output_dir: str  # Directory for output files
    output_file: str = "output.md"  # Name of output file


main_args = BaseArgs(
    input_path="test/fixture/main.pdf",
    output_dir="test/output",
    output_file="output.md",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    main_args = MainArgs().parse_args()

from pathlib import Path

from docling.document_converter import DocumentConverter


# %%
def convert_pdf_to_markdown(args: BaseArgs):
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    converter = DocumentConverter()
    result = converter.convert(args.input_path)
    full_text = result.document.export_to_markdown()

    with open(output_path / args.output_file, "w", encoding="utf-8") as f:
        f.write(full_text)


if __name__ == "__main__":
    convert_pdf_to_markdown(main_args)
