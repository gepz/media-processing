# %%
import sys
from dataclasses import dataclass

from tap import Tap


@dataclass(frozen=True)
class BaseArgs:
    in_path: str
    out_path: str


class MainArgs(Tap):
    in_path: str  # Path to input file
    out_path: str  # Path to output file


g_main_args = BaseArgs(
    in_path="../../test/fixture/scientific_article_2.pdf",
    out_path="../../test/output/output.md",
)

if __name__ == "__main__" and "ipykernel" not in sys.modules:
    g_main_args = MainArgs().parse_args()

import re
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.types.doc.base import ImageRefMode


# %%
def markdown_from_pdf(in_path: str) -> str:
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=PdfPipelineOptions(ocr_options=RapidOcrOptions())
            )
        }
    )
    result = converter.convert(in_path)
    return re.sub(
        "\r\n",
        "\n",
        result.document.export_to_markdown(image_mode=ImageRefMode.REFERENCED),
    )


if __name__ == "__main__":
    g_result = markdown_from_pdf(g_main_args.in_path)
    g_output_path = Path(g_main_args.out_path)
    g_output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(g_output_path, "w", encoding="utf-8") as f:
        f.write(g_result)

# %%
