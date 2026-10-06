import json
from unittest.mock import patch
import httpx
import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest
from tutor.models import SPECS, Diagram, Summary, Examples, Explanation
from tutor.grok_client import GrokClient, TutorError, DEFAULT_MODEL
from tutor.workflow import build_graph
from tutor.render import export_markdown, export_pdf

D={'nodes':[{'id':k,'label':k} for k in 'abc'],'edges':[{'source':'a','target':'b'},{'source':'b','target':'c'}]}
DATA={
'architecture':{'overview':'Input is transformed into output.','components':['Input','Processor','Output'],'steps':['Receive','Process','Return'],'diagram':D},
'professional':{'explanation':'Processing transforms data.','key_points':['Validation','Transformation','Observability'],'pitfalls':['Data loss','Duplication']},
'layman':{'analogy':'A restaurant kitchen.','mapping':['Order is input','Kitchen processes','Meal is output'],'limits_of_analogy':'Data can be copied.'},
'comparison':{'rows':[{'related_topic':n,'similarity':'Processes data','difference':'Execution model','when_to_choose':'When constraints fit'} for n in ['Batch','Streaming','Request response']]},
'examples':{'examples':[{'title':n,'scenario':'Validate a request.','walkthrough':['Accept','Validate','Return'],'expected_result':'Valid response','code':'','code_language':''} for n in ['Basic','Practical','Failure']]},
'end_to_end':{'prerequisites':['Input','Output'],'steps':['Receive','Validate','Transform','Store','Return'],'failure_handling':['Reject','Retry'],'verification':['Check response','Check logs'],'diagram':D},
'summary':{'sentences':['The architecture and analogy explain the process and its related approaches.','The examples and full flow demonstrate implementation and verification.']}}
class Fake:
    def __init__(self):
        self.calls=[]
        self.usage={'input_tokens':0, 'output_tokens':0, 'reported_responses':0}
    def resolve_model(self): return DEFAULT_MODEL
    def generate(self,schema,instruction,context):
        key=next(k for k,_,s,_ in SPECS if s==schema); self.calls.append(key)
        return schema.model_validate(DATA[key]).model_dump()

def state(sections=None): return {'topic':'Processing','language':'English','audience':'Beginner','sections':sections or {}}

def test_seven_agents_export():
    client=Fake(); result=build_graph(client).invoke(state())
    assert client.calls==[s[0] for s in SPECS]
    text=export_markdown('Processing',result['sections'])
    assert text.count('\n## ')==7 and '```dot' in text and '| Related topic |' in text
    pdf = export_pdf('Processing', result['sections'])
    assert pdf.startswith(b'%PDF') and len(pdf) > 100

def test_resume():
    client=Fake(); build_graph(client).invoke(state({'architecture':DATA['architecture']}))
    assert len(client.calls)==6 and 'architecture' not in client.calls

def test_diagram_validation():
    with pytest.raises(ValidationError): Diagram.model_validate({**D,'edges':[{'source':'missing','target':'a'},{'source':'b','target':'c'}]})

def test_minimum_examples():
    with pytest.raises(ValidationError): Examples.model_validate({'examples':DATA['examples']['examples'][:2]})

@pytest.mark.parametrize('values',[['First. Extra.','Second.'],['Only one.']])
def test_summary_validation(values):
    with pytest.raises(ValidationError): Summary(sentences=values)

def test_ui(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    app=AppTest.from_file('../app.py').run(); assert not app.exception
    next(b for b in app.button if b.label == 'Explain in seven steps').click().run(); assert len(app.warning)==1
    with patch('tutor.grok_client.GrokClient',return_value=Fake()):
        app.text_area[0].set_value('Processing'); next(b for b in app.button if b.label == 'Explain in seven steps').click().run(timeout=20)
        assert not app.exception
        assert len(app.session_state['lesson']['sections'])==7 and len(app.expander)==7

def test_partial_failure(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    class Failing(Fake):
        def generate(self,schema,instruction,context):
            if schema==Explanation: raise TutorError('Simulated outage')
            return super().generate(schema,instruction,context)
    app=AppTest.from_file('../app.py').run()
    with patch('tutor.grok_client.GrokClient',return_value=Failing()):
        app.text_area[0].set_value('Processing'); next(b for b in app.button if b.label == 'Explain in seven steps').click().run(timeout=20)
        assert not app.exception and len(app.session_state['lesson']['sections'])==1
        assert any('Simulated outage' in e.value for e in app.error)

def test_real_graph_with_mocked_gemini_responses():
    requests=[]
    def handler(request):
        body=json.loads(request.content)
        requests.append(body)
        name=body['text']['format']['name']
        key=next(k for k,_,schema,_ in SPECS if schema.__name__==name)
        return httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(DATA[key])}]}]})
    client=GrokClient(api_key='test-key',transport=httpx.MockTransport(handler))
    result=build_graph(client).invoke(state())
    assert len(requests)==7 and len(result['sections'])==7
    summary_context=json.loads(requests[-1]['input'][1]['content'])
    assert set(summary_context['previous_sections'])==set(DATA)-{'summary'}
    assert 'test-key' not in json.dumps(result)

def test_ui_missing_key(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    app=AppTest.from_file('../app.py').run()
    app.text_area[0].set_value('Processing')
    next(b for b in app.button if b.label=='Explain in seven steps').click().run()
    assert not app.exception
    assert any('API key' in w.value for w in app.warning)

def test_ui_retry_completes_without_repeating_architecture(monkeypatch):
    monkeypatch.setenv('GEMINI_API_KEY','test-key')
    class Failing(Fake):
        def generate(self,schema,instruction,context):
            if schema==Explanation: raise TutorError('Simulated outage')
            return super().generate(schema,instruction,context)
    app=AppTest.from_file('../app.py').run()
    with patch('tutor.grok_client.GrokClient',return_value=Failing()):
        app.text_area[0].set_value('Processing')
        next(b for b in app.button if b.label=='Explain in seven steps').click().run()
    succeeding=Fake()
    with patch('tutor.grok_client.GrokClient',return_value=succeeding):
        # Rerun to expose the stable retry button above the result.
        app.run()
        next(b for b in app.button if b.label=='Retry remaining sections').click().run()
    assert not app.exception
    assert len(app.session_state['lesson']['sections'])==7
    assert len(succeeding.calls)==6 and 'architecture' not in succeeding.calls
