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
    input_path="test/fixture/scientific_article_example.md",
    output_dir="test/output",
    output_file="output.md",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    main_args = MainArgs().parse_args()


import asyncio
from pathlib import Path
from typing import Sequence

from chonkie import SDPMChunker
from llama_index.core import SimpleDirectoryReader
from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode, Document, TextNode
from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)
from llama_index.embeddings.voyageai import VoyageEmbedding
from llama_index.llms.openrouter import OpenRouter
from llama_index.utils.workflow import (
    draw_all_possible_flows,
    draw_most_recent_execution,
)
from rapidfuzz import fuzz

# from media_processing import event_logging

# event_logging.start()


# %%
def non_empty_stripped_texts(documents: Sequence[Document]) -> list[str]:
    return [
        stripped
        for doc in documents
        for stripped in [doc.text.strip()]
        if len(stripped) > 0
    ]


input_documents = SimpleDirectoryReader(input_files=[main_args.input_path]).load_data()
example_documents = SimpleDirectoryReader(
    input_files=[
        "test/fixture/markdown_to_slideshow/source_scientific_article_example.md"
    ]
).load_data()
non_empty_texts = non_empty_stripped_texts(input_documents)
non_empty_example_texts = non_empty_stripped_texts(input_documents)


@dataclass
class Section:
    level: int
    title: str | None
    content: str


def parse_text_block(text: str) -> Section:
    lines = text.split("\n\r\n", 1)
    title = lines[0]
    content = lines[1] if len(lines) > 1 else ""
    match title.split():
        case []:
            level, clean_title = 1, title
        case [first, *rest] if any(char.isdigit() for char in first):
            level, clean_title = first.count(".") + 1, " ".join(rest)
        case _:
            level, clean_title = 1, title.strip()

    return Section(level=level, title=clean_title, content=content)


sections = [parse_text_block(text) for text in non_empty_texts]

primary_blocks: list[Section] = []
supportive_blocks: list[Section] = []

METADATA_KEYWORDS = ["ccs concepts", "keywords", "references", "acknowledgments"]

for section in sections:
    similarity_threshold = 80
    if any(
        fuzz.partial_ratio(
            keyword.lower(), section.title.lower() if section.title else ""
        )
        >= similarity_threshold
        for keyword in METADATA_KEYWORDS
    ):
        supportive_blocks.append(section)
    else:
        primary_blocks.append(section)

# %%
splitter = SentenceSplitter()

# %%
llm = OpenRouter(
    max_tokens=1048,
    context_window=16384,
    model="meta-llama/llama-3.1-8b-instruct",
)


class SlideCreateEvent(Event):
    index: int
    section: Section


class SlideCreatedEvent(Event):
    index: int
    content: str


class SlideShowWorkflow(Workflow):
    @step
    async def start(self, ctx: Context, ev: StartEvent) -> SlideCreateEvent | None:
        await ctx.set("slide_count", len(ev.sections))
        for i, section in enumerate(ev.sections):
            section: Section
            interval = 1 / 30
            await asyncio.sleep(interval)
            ctx.send_event(SlideCreateEvent(index=i, section=section))

    @step
    async def make_slide(self, ev: SlideCreateEvent) -> SlideCreatedEvent:
        print("make slide")
        message = ChatMessage(
            role=MessageRole.USER,
            content="For the following text, give a slide page title, describe it in a short bullet points"
            f', and write the corresponding speaker note: """{ev.section.content}"""',
        )
        print(message)
        response = await llm.achat([message])
        print(f'{ev.index}:\n"""{response}"""')
        return SlideCreatedEvent(index=ev.index, content=str(response.message.content))

    @step
    async def collect_slides(
        self, ctx: Context, ev: SlideCreatedEvent
    ) -> StopEvent | None:
        print("slide made")
        events = ctx.collect_events(
            ev, [SlideCreatedEvent] * await ctx.get("slide_count")
        )
        if events is None:
            return None
        slides_dict = {
            x.index: str(x.content) for x in events if isinstance(x, SlideCreatedEvent)
        }
        slides = []
        for i in range(max(slides_dict.keys())):
            slides.append(slides_dict[i])
        return StopEvent(result=slides)


slides: list[str] = []
workflow = SlideShowWorkflow(timeout=60)
# draw_all_possible_flows(workflow)


def triple_quote(content: str) -> str:
    return f'"""\n{content}\n"""'


def create_conversion_prompt(example_text: str, example_slide: str, text: str) -> str:
    return (
        "I have the following academic text:\n"
        f"{triple_quote(example_text)}"
        "For reference, here's how it was converted into slide format:"
        f"{triple_quote(example_slide)}"
        "Please convert the following academic text into a concise, high-level overview using a similar format. The slide content should be brief, and the speaker notes should reference the slide content without adding concluding remarks.\n"
        f"{triple_quote(text)}"
    )


prompt = create_conversion_prompt("", "", "")


async def main(args: BaseArgs):
    global slides
    slides = await workflow.run(sections=primary_blocks)
    # draw_most_recent_execution(workflow)
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    full_text = f"\n{"-" * 10}\n".join(x for x in slides)

    with open(output_path / args.output_file, "w", encoding="utf-8") as f:
        f.write(full_text)


# %%
if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
        await main(main_args)  # type: ignore  # noqa: F704
    except RuntimeError:
        asyncio.run(main(main_args))

# %%
