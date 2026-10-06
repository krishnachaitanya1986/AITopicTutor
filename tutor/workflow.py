from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from tutor.models import SPECS

class TutorState(TypedDict, total=False):
    topic: str
    language: str
    audience: str
    sections: dict

def build_graph(client):
    builder = StateGraph(TutorState)
    previous = START
    for key, title, schema, instruction in SPECS:
        def agent(state, key=key, schema=schema, instruction=instruction):
            sections = state.get('sections', {})
            # Reuse validated sections when retrying an interrupted lesson.
            if key in sections:
                schema.model_validate(sections[key])
                return {}
            context = {'topic': state['topic'], 'language': state['language'], 'audience': state['audience']}
            if key == 'summary':
                # Bounded extracts of ALL sections, preserving room for schema and output.
                import json
                context['previous_sections'] = {k: json.dumps(v, ensure_ascii=False)[:2400] for k, v in sections.items()}
            elif 'architecture' in sections:
                context['architecture_overview'] = sections['architecture']['overview']
            result = client.generate(schema, instruction, context)
            return {'sections': {**sections, key: result}}
        builder.add_node(key, agent)
        builder.add_edge(previous, key)
        previous = key
    builder.add_edge(previous, END)
    return builder.compile()
