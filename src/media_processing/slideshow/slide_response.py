# %%
from dataclasses import dataclass
from typing import Self

from pydantic import BaseModel

import media_processing.slideshow.markdown_slide as ms


class SlideReferenceStatus(BaseModel):
    start: str
    end: str

    @classmethod
    def from_note(cls, note: ms.Note) -> Self:
        try:
            return cls.model_validate_json(
                next(
                    c
                    for c in reversed(note.to_segments())
                    if isinstance(c, ms.JsonObjectString)
                )
            )
        except StopIteration as e:
            print(note.to_segments())
            raise e


@dataclass(frozen=True)
class SlideResponse:
    slide: ms.MarkdownSlide
    reference_status: SlideReferenceStatus | None

    @classmethod
    def from_markdown(cls, markdown: str) -> Self:
        slide = ms.MarkdownSlide.from_markdown(markdown)

        return cls(
            slide=slide,
            reference_status=(
                None
                if slide.note is None
                else SlideReferenceStatus.from_note(slide.note)
            ),
        )


# %%
