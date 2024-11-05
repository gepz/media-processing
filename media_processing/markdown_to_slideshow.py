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
    input_path="test/fixture/main.md",
    output_dir="test/output",
    output_file="output.md",
)
if __name__ == "__main__" and "ipykernel" not in sys.modules:
    main_args = MainArgs().parse_args()


import asyncio
from pathlib import Path

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

from media_processing import event_logging

# %%
# event_logging.start()

# %%
reader = SimpleDirectoryReader(input_files=[main_args.input_path])
documents = reader.load_data()
non_empty_stripped_doc_texts = [
    stripped
    for doc in documents
    for stripped in [doc.text.strip()]
    if len(stripped) > 0
]

primary_text: list[str] = []
supporting_text: list[str] = []
context_keywords = ["ccs concepts", "keywords", "references", "acknowledgments"]

for text in non_empty_stripped_doc_texts:
    SIMILARITY_THRESHOLD = 80
    if any(
        fuzz.partial_ratio(keyword.lower(), text[:15].lower()) >= SIMILARITY_THRESHOLD
        for keyword in context_keywords
    ):
        supporting_text.append(text)
    else:
        primary_text.append(text)

# %%
splitter = SentenceSplitter()
primary_nodes = [
    x
    for x in splitter.get_nodes_from_documents([Document(text=x) for x in primary_text])
    if isinstance(x, TextNode)
]

# %%
llm = OpenRouter(
    max_tokens=1048,
    context_window=16384,
    model="meta-llama/llama-3.1-8b-instruct",
)


class SlideCreateEvent(Event):
    index: int
    node: TextNode


class SlideCreatedEvent(Event):
    index: int
    content: str


class SlideShowWorkflow(Workflow):
    @step
    async def start(self, ctx: Context, ev: StartEvent) -> SlideCreateEvent | None:
        await ctx.set("slide_count", len(ev.nodes))
        for i, node in enumerate(ev.nodes):
            node: TextNode
            SLEEP_DURATION = 1 / 14
            await asyncio.sleep(SLEEP_DURATION)
            ctx.send_event(SlideCreateEvent(index=i, node=node))

    @step
    async def make_slide(self, ev: SlideCreateEvent) -> SlideCreatedEvent:
        print("make slide")
        message = ChatMessage(
            role=MessageRole.USER,
            content="For the following text, give a slide page title, describe it in a short bullet points"
            f', and write the corresponding speaker note: """{ev.node.text}"""',
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
        for i in range(max(slides_dict.keys()) + 1):
            slides.append(slides_dict[i])
        return StopEvent(result=slides)


slides: list[str] = []
workflow = SlideShowWorkflow(timeout=60)
# draw_all_possible_flows(workflow)


async def main(args: BaseArgs):
    global slides
    slides = await workflow.run(nodes=primary_nodes)
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
