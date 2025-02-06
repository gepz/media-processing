# %%
from llama_index.core.instrumentation import get_dispatcher
from llama_index.core.instrumentation.event_handlers import BaseEventHandler
from llama_index.core.instrumentation.events import BaseEvent
from llama_index.core.instrumentation.events.agent import (
    AgentChatWithStepEndEvent,
    AgentChatWithStepStartEvent,
    AgentRunStepEndEvent,
    AgentRunStepStartEvent,
    AgentToolCallEvent,
)
from llama_index.core.instrumentation.events.chat_engine import (
    StreamChatDeltaReceivedEvent,
    StreamChatErrorEvent,
)
from llama_index.core.instrumentation.events.embedding import (
    EmbeddingEndEvent,
    EmbeddingStartEvent,
)
from llama_index.core.instrumentation.events.llm import (
    LLMChatEndEvent,
    LLMChatInProgressEvent,
    LLMChatStartEvent,
    LLMCompletionEndEvent,
    LLMCompletionStartEvent,
    LLMPredictEndEvent,
    LLMPredictStartEvent,
    LLMStructuredPredictEndEvent,
    LLMStructuredPredictStartEvent,
)
from llama_index.core.instrumentation.events.query import (
    QueryEndEvent,
    QueryStartEvent,
)
from llama_index.core.instrumentation.events.rerank import (
    ReRankEndEvent,
    ReRankStartEvent,
)
from llama_index.core.instrumentation.events.retrieval import (
    RetrievalEndEvent,
    RetrievalStartEvent,
)
from llama_index.core.instrumentation.events.span import (
    SpanDropEvent,
)
from llama_index.core.instrumentation.events.synthesis import (
    GetResponseEndEvent,
    GetResponseStartEvent,
    SynthesizeEndEvent,
    SynthesizeStartEvent,
)
from treelib import Tree


class ExampleEventHandler(BaseEventHandler):
    """Example event handler.

    This event handler is an example of how to create a custom event handler.

    In general, logged events are treated as single events in a point in time,
    that link to a span. The span is a collection of events that are related to
    a single task. The span is identified by a unique span_id.

    While events are independent, there is some hierarchy.
    For example, in query_engine.query() call with a reranker attached:
    - QueryStartEvent
    - RetrievalStartEvent
    - EmbeddingStartEvent
    - EmbeddingEndEvent
    - RetrievalEndEvent
    - RerankStartEvent
    - RerankEndEvent
    - SynthesizeStartEvent
    - GetResponseStartEvent
    - LLMPredictStartEvent
    - LLMChatStartEvent
    - LLMChatEndEvent
    - LLMPredictEndEvent
    - GetResponseEndEvent
    - SynthesizeEndEvent
    - QueryEndEvent
    """

    events: list[BaseEvent] = []

    @classmethod
    def class_name(cls) -> str:
        """Class name."""
        return "ExampleEventHandler"

    def handle(self, event: BaseEvent, **kwargs) -> None:
        """Logic for handling event."""
        print("-----------------------")
        # all events have these attributes
        print(event.id_)
        print(event.timestamp)
        print(event.span_id)

        # event specific attributes
        print(f"Event type: {event.class_name()}")
        if isinstance(event, AgentRunStepStartEvent):
            print(event.task_id)
            print(event.step)
            print(event.input)
        if isinstance(event, AgentRunStepEndEvent):
            print(event.step_output)
        if isinstance(event, AgentChatWithStepStartEvent):
            print(event.user_msg)
        if isinstance(event, AgentChatWithStepEndEvent):
            print(event.response)
        if isinstance(event, AgentToolCallEvent):
            print(event.arguments)
            print(event.tool.name)
            print(event.tool.description)
            print(event.tool.to_openai_tool())
        if isinstance(event, StreamChatDeltaReceivedEvent):
            print(event.delta)
        if isinstance(event, StreamChatErrorEvent):
            print(event.exception)
        if isinstance(event, EmbeddingStartEvent):
            print(event.model_dict)
        if isinstance(event, EmbeddingEndEvent):
            print(event.chunks)
            print(event.embeddings[0][:5])  # avoid printing all embeddings
        if isinstance(event, LLMPredictStartEvent):
            print(event.template)
            print(event.template_args)
        if isinstance(event, LLMPredictEndEvent):
            print(event.output)
        if isinstance(event, LLMStructuredPredictStartEvent):
            print(event.template)
            print(event.template_args)
            print(event.output_cls)
        if isinstance(event, LLMStructuredPredictEndEvent):
            print(event.output)
        if isinstance(event, LLMCompletionStartEvent):
            print(event.model_dict)
            print(event.prompt)
            print(event.additional_kwargs)
        if isinstance(event, LLMCompletionEndEvent):
            print(event.response)
            print(event.prompt)
        if isinstance(event, LLMChatInProgressEvent):
            print(event.messages)
            print(event.response)
        if isinstance(event, LLMChatStartEvent):
            print(event.messages)
            print(event.additional_kwargs)
            print(event.model_dict)
        if isinstance(event, LLMChatEndEvent):
            print(event.messages)
            print(event.response)
        if isinstance(event, RetrievalStartEvent):
            print(event.str_or_query_bundle)
        if isinstance(event, RetrievalEndEvent):
            print(event.str_or_query_bundle)
            print(event.nodes)
        if isinstance(event, ReRankStartEvent):
            print(event.query)
            print(event.nodes)
            print(event.top_n)
            print(event.model_name)
        if isinstance(event, ReRankEndEvent):
            print(event.nodes)
        if isinstance(event, QueryStartEvent):
            print(event.query)
        if isinstance(event, QueryEndEvent):
            print(event.response)
            print(event.query)
        if isinstance(event, SpanDropEvent):
            print(event.err_str)
        if isinstance(event, SynthesizeStartEvent):
            print(event.query)
        if isinstance(event, SynthesizeEndEvent):
            print(event.response)
            print(event.query)
        if isinstance(event, GetResponseStartEvent):
            print(event.query_str)
        if isinstance(event, GetResponseStartEvent):
            print(event.query_str)

        self.events.append(event)
        print("-----------------------")

    def _get_events_by_span(self) -> dict[str, list[BaseEvent]]:
        events_by_span: dict[str, list[BaseEvent]] = {}
        for event in self.events:
            if event.span_id in events_by_span:
                events_by_span[event.span_id].append(event)
            elif event.span_id is not None:
                events_by_span[event.span_id] = [event]
        return events_by_span

    def _get_event_span_trees(self) -> list[Tree]:
        events_by_span = self._get_events_by_span()

        trees = []
        tree = Tree()

        for span, sorted_events in events_by_span.items():
            # create root node i.e. span node
            tree.create_node(
                tag=f"{span} (SPAN)",
                identifier=span,
                parent=None,
                data=sorted_events[0].timestamp,
            )

            for event in sorted_events:
                tree.create_node(
                    tag=f"{event.class_name()}: {event.id_}",
                    identifier=event.id_,
                    parent=event.span_id,
                    data=event.timestamp,
                )

            trees.append(tree)
            tree = Tree()
        return trees

    def print_event_span_trees(self) -> None:
        """Method for viewing trace trees."""
        trees = self._get_event_span_trees()
        for tree in trees:
            print(tree.show(stdout=False, sorting=True, key=lambda node: node.data))
            print("")


main_event_handler = ExampleEventHandler()


def start():
    root_dispatcher = get_dispatcher()
    root_dispatcher.event_handlers = []
    root_dispatcher.add_event_handler(main_event_handler)


def stop():
    root_dispatcher = get_dispatcher()
    root_dispatcher.event_handlers = []
