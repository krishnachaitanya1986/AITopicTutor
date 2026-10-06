"""Validated contracts between the seven specialist agents."""
import re
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=16000)]

class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)

class Node(Contract):
    id: Annotated[str, Field(pattern=r'^[A-Za-z][A-Za-z0-9_]{0,30}$')]
    label: Annotated[str, Field(min_length=1, max_length=100)]

class Edge(Contract):
    source: str
    target: str
    label: Annotated[str, Field(max_length=80)] = ''

class Diagram(Contract):
    nodes: list[Node] = Field(min_length=3, max_length=12)
    edges: list[Edge] = Field(min_length=2, max_length=24)

    @model_validator(mode='after')
    def check_references(self):
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError('Diagram node IDs must be unique')
        if any(e.source not in ids or e.target not in ids for e in self.edges):
            raise ValueError('All edge endpoints must reference existing node IDs')
        touched = {v for e in self.edges for v in (e.source, e.target)}
        if ids != touched:
            raise ValueError('Every node must participate in the flow')
        return self

class Architecture(Contract):
    overview: Text
    components: list[Text] = Field(min_length=3, max_length=10)
    steps: list[Text] = Field(min_length=3, max_length=10)
    diagram: Diagram

class Explanation(Contract):
    explanation: Text
    key_points: list[Text] = Field(min_length=3, max_length=8)
    pitfalls: list[Text] = Field(min_length=2, max_length=5)

class Layman(Contract):
    analogy: Text
    mapping: list[Text] = Field(min_length=3, max_length=8)
    limits_of_analogy: Text

class ComparisonRow(Contract):
    related_topic: Text
    similarity: Text
    difference: Text
    when_to_choose: Text

class Comparison(Contract):
    rows: list[ComparisonRow] = Field(min_length=3, max_length=6)

class Example(Contract):
    title: Text
    scenario: Text
    walkthrough: list[Text] = Field(min_length=3, max_length=8)
    expected_result: Text
    code: str = Field(max_length=12000)
    code_language: str = Field(max_length=30)

class Examples(Contract):
    examples: list[Example] = Field(min_length=3, max_length=5)

class EndToEnd(Contract):
    prerequisites: list[Text] = Field(min_length=2, max_length=8)
    steps: list[Text] = Field(min_length=5, max_length=12)
    failure_handling: list[Text] = Field(min_length=2, max_length=6)
    verification: list[Text] = Field(min_length=2, max_length=6)
    diagram: Diagram

class Summary(Contract):
    sentences: list[Text] = Field(min_length=2, max_length=2)

    @field_validator('sentences')
    @classmethod
    def exactly_two_sentences(cls, values):
        for value in values:
            # Deliberately strict: ask the model to avoid abbreviations and decimals.
            if len(re.findall(r'[.!?。！？]+', value)) != 1 or value[-1] not in '.!?。！？':
                raise ValueError('Each entry must be exactly one sentence, ending in one sentence terminator; avoid abbreviations or decimals')
        return values

SPECS = [
    ('architecture', 'Architecture and flow diagram', Architecture,
     'Explain components and their responsibilities, numbered architecture steps, and a connected directed flow diagram. For nontechnical topics use a conceptual process architecture.'),
    ('professional', 'Professional explanation', Explanation,
     'Explain precise terminology, how and why it works, tradeoffs, and common misconceptions. Be accurate and professional.'),
    ('layman', 'Plain-language understanding', Layman,
     'Use an everyday analogy, map it to the real concepts, and explain where the analogy stops being accurate.'),
    ('comparison', 'Comparison with related topics', Comparison,
     'Compare the requested topic with at least three distinct related topics; give meaningful similarities, differences, and selection guidance.'),
    ('examples', 'Three or more worked examples', Examples,
     'Provide at least three distinct examples: beginner, practical real-world, and advanced or failure case. Walk through each and state the result. Include short code only if useful; otherwise use empty strings for code and code_language. Code is illustrative and is never executed.'),
    ('end_to_end', 'Complete end-to-end flow', EndToEnd,
     'Cover prerequisites, every major step from initial input to final result, failure handling, and verification. Include a connected flow diagram. Avoid claiming all details of an arbitrarily broad topic fit in one lesson.'),
    ('summary', 'Two-sentence summary', Summary,
     'Summarize all six sections in exactly two sentences total. Synthesize architecture, professional explanation, analogy, comparisons, examples, and end-to-end outcome. No abbreviations, decimals, bullet points, or extra sentence terminators.'),
]
